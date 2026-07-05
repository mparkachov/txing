// Action-layer runtime: the mac daemon's board-style AWS IoT session.
// Publication shapes and ordering follow the unit daemon
// (devices/unit/daemon/internal/daemon/runtime.go RunConnectedRuntime),
// trimmed to no hardware worker, no actuator MCP tools, and no
// CloudWatch logging. The runtime is started when the watch layer
// enters REDCON 2 or 1 and stopped (with offline publications) when it
// leaves.
package action

import (
	"context"
	"fmt"
	"sync"
	"time"
)

const (
	videoStatusHeartbeatSeconds = 5
	mqttReconnectDelay          = 3 * time.Second
	offlinePublishTimeout       = 5 * time.Second
)

type Logf func(level string, message string)

// Controller owns the action-layer lifecycle for the state machine:
// targets 1 and 2 keep the runtime running, targets 3 and 4 stop it.
type Controller struct {
	config  Config
	enabled bool
	version string
	logf    Logf

	mu     sync.Mutex
	cancel context.CancelFunc
	done   chan struct{}
}

func NewController(config Config, enabled bool, version string, logf Logf) *Controller {
	return &Controller{config: config, enabled: enabled, version: version, logf: logf}
}

func (c *Controller) SetTarget(redcon uint8) {
	if redcon <= 2 {
		c.start()
		return
	}
	c.stop()
}

func (c *Controller) Running() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.cancel != nil
}

func (c *Controller) Shutdown() {
	c.stop()
}

func (c *Controller) start() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cancel != nil {
		return
	}
	if !c.enabled {
		c.logf("warning", "action layer requested but not configured; add AWS IoT settings from the mac cert bundle to daemon.env")
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	c.cancel = cancel
	c.done = done
	go func() {
		defer close(done)
		run(ctx, c.config, c.version, c.logf)
	}()
	c.logf("info", "action layer starting")
}

func (c *Controller) stop() {
	c.mu.Lock()
	cancel := c.cancel
	done := c.done
	c.cancel = nil
	c.done = nil
	c.mu.Unlock()
	if cancel == nil {
		return
	}
	cancel()
	<-done
	c.logf("info", "action layer stopped")
}

func run(ctx context.Context, config Config, version string, logf Logf) {
	videoEvents := make(chan VideoWorkerEvent, 32)
	mcpEvents := make(chan interface{}, 32)
	if config.VideoEnabled() {
		bridge, err := StartBoardVideoBridgeServer(config, videoEvents, mcpEvents)
		if err != nil {
			logf("warning", fmt.Sprintf("board video bridge failed to start error=%q", err))
		} else {
			defer bridge.Shutdown()
			logf("info", fmt.Sprintf("board video bridge listening socket=%s", config.BridgeSocketPath))
		}
	}
	for {
		publisher, incoming, err := ConnectMQTT(ctx, config)
		if err != nil {
			logf("warning", fmt.Sprintf("action MQTT connect failed error=%q", err))
			select {
			case <-ctx.Done():
				return
			case <-time.After(mqttReconnectDelay):
				continue
			}
		}
		logf("info", fmt.Sprintf("action MQTT connected clientId=%s", config.ClientID))
		err = runSession(ctx, config, version, publisher, incoming, videoEvents, mcpEvents, logf)
		_ = publisher.Stop()
		if ctx.Err() != nil {
			return
		}
		logf("warning", fmt.Sprintf("action MQTT session ended, reconnecting error=%q", err))
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Second):
		}
	}
}

type sessionState struct {
	config  Config
	version string
	video   VideoRuntimeState
	caps    *capabilityPublisher
}

type capabilityPublisher struct {
	capabilities []string
	seq          uint64
}

func (m *capabilityPublisher) publish(ctx context.Context, publisher Publisher, config Config, availability map[string]bool, observedAtMS uint64) error {
	m.seq++
	topic, err := BuildCapabilityStateTopic(config.ThingID)
	if err != nil {
		return err
	}
	payload := BuildCapabilityStatePayload(config.ThingID, m.capabilities, availability, durationMillis(config.CapabilityTTL), observedAtMS, m.seq)
	return publishRetainedDynamicJSON(ctx, publisher, topic, payload, config.CapabilityTTL)
}

func runSession(ctx context.Context, config Config, version string, publisher *MQTTPublisher, incoming <-chan RuntimeMqttEvent, videoEvents <-chan VideoWorkerEvent, mcpEvents <-chan interface{}, logf Logf) error {
	state := &sessionState{
		config:  config,
		version: version,
		caps:    &capabilityPublisher{capabilities: config.Capabilities},
	}
	subscription, err := BuildMCPSessionC2SSubscription(config.ThingID)
	if err != nil {
		return err
	}
	if err := publisher.Subscribe(ctx, subscription); err != nil {
		return err
	}
	if err := state.publishOnline(ctx, publisher, nowMillis()); err != nil {
		return err
	}
	heartbeat := time.NewTicker(config.Heartbeat)
	defer heartbeat.Stop()
	videoStatus := time.NewTicker(videoStatusHeartbeatSeconds * time.Second)
	defer videoStatus.Stop()

	for {
		select {
		case <-ctx.Done():
			offlineCtx, cancel := context.WithTimeout(context.Background(), offlinePublishTimeout)
			err := state.publishOffline(offlineCtx, publisher, nowMillis())
			cancel()
			return err
		case event, ok := <-incoming:
			if !ok || event.Disconnected {
				return fmt.Errorf("action MQTT disconnected")
			}
			state.handleMCPPublish(ctx, publisher, event.Topic, event.Payload, nowMillis())
		case event := <-videoEvents:
			if err := state.handleVideoEvent(ctx, publisher, event, nowMillis()); err != nil {
				logf("warning", fmt.Sprintf("video event handling failed error=%q", err))
			}
		case event := <-mcpEvents:
			state.handleBridgeMCPEvent(event)
		case <-heartbeat.C:
			if err := state.refresh(ctx, publisher, nowMillis()); err != nil {
				logf("warning", fmt.Sprintf("capability refresh failed error=%q", err))
			}
		case <-videoStatus.C:
			if err := state.refreshVideoStatus(ctx, publisher, nowMillis()); err != nil {
				logf("warning", fmt.Sprintf("video status refresh failed error=%q", err))
			}
		}
	}
}

func (s *sessionState) publishOnline(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	if err := s.publishBoardShadow(ctx, publisher, BuildOnlineBoardReport(DiscoverDefaultRouteAddresses())); err != nil {
		return err
	}
	if err := s.publishMCPDiscovery(ctx, publisher, observedAtMS); err != nil {
		return err
	}
	if s.config.VideoEnabled() {
		s.video = VideoRuntimeStarting(observedAtMS)
		videoDescriptorTopic, _ := BuildVideoDescriptorTopic(s.config.ThingID)
		if err := publishJSON(ctx, publisher, videoDescriptorTopic, VideoDescriptor(s.config, s.version), true); err != nil {
			return err
		}
		if err := s.publishVideoStatusAndShadow(ctx, publisher); err != nil {
			return err
		}
	}
	return s.caps.publish(ctx, publisher, s.config, s.onlineCapabilities(), observedAtMS)
}

func (s *sessionState) publishOffline(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	if err := s.publishBoardShadow(ctx, publisher, BuildOfflineBoardReport()); err != nil {
		return err
	}
	statusTopic, _ := BuildMCPStatusTopic(s.config.ThingID)
	if err := publishRetainedDynamicJSON(ctx, publisher, statusTopic, MCPUnavailablePayload(observedAtMS), s.config.CapabilityTTL); err != nil {
		return err
	}
	if err := s.publishMCPShadow(ctx, publisher, s.mcpDescriptor(), MCPUnavailablePayload(observedAtMS)); err != nil {
		return err
	}
	if s.config.VideoEnabled() {
		s.video = VideoRuntimeUnavailable(observedAtMS)
		if err := s.publishVideoStatusAndShadow(ctx, publisher); err != nil {
			return err
		}
	}
	return s.caps.publish(ctx, publisher, s.config, s.offlineCapabilities(), observedAtMS)
}

func (s *sessionState) refresh(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	if err := s.publishMCPStatus(ctx, publisher, observedAtMS); err != nil {
		return err
	}
	return s.caps.publish(ctx, publisher, s.config, s.onlineCapabilities(), observedAtMS)
}

func (s *sessionState) refreshVideoStatus(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	if !s.config.VideoEnabled() {
		return nil
	}
	s.video.UpdatedAtMS = observedAtMS
	return s.publishVideoStatusAndShadow(ctx, publisher)
}

func (s *sessionState) handleVideoEvent(ctx context.Context, publisher Publisher, event VideoWorkerEvent, observedAtMS uint64) error {
	if !s.config.VideoEnabled() {
		return nil
	}
	previousTransport := s.mcpTransportMode()
	s.video.ApplyEvent(event, observedAtMS)
	if previousTransport != s.mcpTransportMode() {
		if err := s.publishMCPDiscovery(ctx, publisher, observedAtMS); err != nil {
			return err
		}
	}
	if err := s.publishVideoStatusAndShadow(ctx, publisher); err != nil {
		return err
	}
	return s.caps.publish(ctx, publisher, s.config, s.onlineCapabilities(), observedAtMS)
}

func (s *sessionState) handleBridgeMCPEvent(event interface{}) {
	switch typed := event.(type) {
	case RuntimeMcpOpenEvent, RuntimeMcpCloseEvent:
		// Read-only stub: sessions carry no state to open or close.
	case RuntimeMcpRequestEvent:
		response := HandleMCPPayload([]byte(typed.Payload), s.version, s.video)
		if typed.Response != nil {
			typed.Response <- response
		}
	}
}

func (s *sessionState) handleMCPPublish(ctx context.Context, publisher Publisher, topic string, payload []byte, observedAtMS uint64) {
	sessionID, ok := ParseMCPSessionC2STopic(s.config.ThingID, topic)
	if !ok {
		return
	}
	_ = observedAtMS
	var response *string
	if s.mcpTransportMode() == MCPTransportWebRTCDataChannel {
		encoded := `{"jsonrpc":"2.0","id":null,"error":{"code":-32000,"message":"MCP is available only over WebRTC data channel while video is ready"}}`
		response = &encoded
	} else {
		response = HandleMCPPayload(payload, s.version, s.video)
	}
	if response == nil {
		return
	}
	responseTopic, err := BuildMCPSessionS2CTopic(s.config.ThingID, sessionID)
	if err != nil {
		return
	}
	_ = publisher.Publish(ctx, PublishedMessage{Topic: responseTopic, Payload: []byte(*response)})
}

func (s *sessionState) onlineCapabilities() map[string]bool {
	return map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: s.video.Ready}
}

func (s *sessionState) offlineCapabilities() map[string]bool {
	return map[string]bool{BoardCapability: false, MCPCapability: false, VideoCapability: false}
}

func (s *sessionState) mcpTransportMode() MCPTransportMode {
	if s.config.VideoEnabled() && s.video.Ready {
		return MCPTransportWebRTCDataChannel
	}
	return MCPTransportMQTT
}

func (s *sessionState) mcpDescriptor() map[string]interface{} {
	return MCPDescriptor(s.config, s.version, string(s.mcpTransportMode()))
}

func (s *sessionState) publishMCPDiscovery(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	descriptor := s.mcpDescriptor()
	statusPayload := MCPStatusPayload(observedAtMS)
	descriptorTopic, _ := BuildMCPDescriptorTopic(s.config.ThingID)
	statusTopic, _ := BuildMCPStatusTopic(s.config.ThingID)
	if err := publishJSON(ctx, publisher, descriptorTopic, descriptor, true); err != nil {
		return err
	}
	if err := publishRetainedDynamicJSON(ctx, publisher, statusTopic, statusPayload, s.config.CapabilityTTL); err != nil {
		return err
	}
	return s.publishMCPShadow(ctx, publisher, descriptor, statusPayload)
}

func (s *sessionState) publishMCPStatus(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	statusPayload := MCPStatusPayload(observedAtMS)
	statusTopic, _ := BuildMCPStatusTopic(s.config.ThingID)
	if err := publishRetainedDynamicJSON(ctx, publisher, statusTopic, statusPayload, s.config.CapabilityTTL); err != nil {
		return err
	}
	return s.publishMCPShadow(ctx, publisher, s.mcpDescriptor(), statusPayload)
}

func (s *sessionState) publishMCPShadow(ctx context.Context, publisher Publisher, descriptor, statusPayload map[string]interface{}) error {
	topic, _ := BuildMCPShadowUpdateTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, map[string]interface{}{
		"state": map[string]interface{}{"reported": map[string]interface{}{"descriptor": descriptor, "status": statusPayload}},
	}, false)
}

func (s *sessionState) publishVideoStatusAndShadow(ctx context.Context, publisher Publisher) error {
	descriptor := VideoDescriptor(s.config, s.version)
	statusPayload := s.videoStatus()
	statusTopic, _ := BuildVideoStatusTopic(s.config.ThingID)
	if err := publishRetainedDynamicJSON(ctx, publisher, statusTopic, statusPayload, s.config.CapabilityTTL); err != nil {
		return err
	}
	topic, _ := BuildVideoShadowUpdateTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, map[string]interface{}{
		"state": map[string]interface{}{"reported": map[string]interface{}{"descriptor": descriptor, "status": statusPayload}},
	}, false)
}

func (s *sessionState) videoStatus() map[string]interface{} {
	return map[string]interface{}{
		"serviceId":       VideoCapability,
		"available":       s.video.Available,
		"ready":           s.video.Ready,
		"status":          s.video.Status,
		"viewerConnected": s.video.ViewerConnected,
		"lastError":       s.video.LastError,
		"updatedAtMs":     s.video.UpdatedAtMS,
	}
}

func (s *sessionState) publishBoardShadow(ctx context.Context, publisher Publisher, report BoardReport) error {
	topic, _ := BuildBoardShadowUpdateTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, BuildBoardShadowUpdate(report), false)
}
