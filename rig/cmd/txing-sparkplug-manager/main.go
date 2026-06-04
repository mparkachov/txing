package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/mparkachov/txing/rig/internal/awsx"
	"github.com/mparkachov/txing/rig/internal/ipc"
	"github.com/mparkachov/txing/rig/internal/manager"
	"github.com/mparkachov/txing/rig/internal/mqttx"
	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/registry"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
	"github.com/mparkachov/txing/rig/internal/sparkplug"
	"github.com/mparkachov/txing/rig/internal/version"
)

const (
	managerID                          = "dev.txing.rig.SparkplugManager"
	nodeBDSeq                          = uint64(1)
	devicePublishInterval              = 2 * time.Second
	boardRetainedCapabilityStateFilter = "txings/+/capability/v2/state"
	shadowUpdateFilter                 = "$aws/things/+/shadow/name/+/update"
)

type runtimeState struct {
	cfg                     rigconfig.Config
	logger                  *awsx.CloudWatchLogger
	broker                  *ipc.Broker
	ipcClient               *ipc.Client
	registry                *registry.Client
	nodeMQTT                *mqttx.Client
	devices                 map[string]*managedDevice
	deviceMu                sync.RWMutex
	boardStateMu            sync.Mutex
	boardStateSubscriptions map[string]struct{}
	inventorySeq            uint64
	nodeSeq                 uint64
	commandSeq              uint64
}

type managedDevice struct {
	state *manager.DeviceRuntimeState
	mqtt  managedMQTTClient
	seq   uint64
}

type nodeMQTTClient interface {
	Subscribe(filter string, handler func(mqttx.Message)) error
	Publish(topic string, payload []byte, retained bool) error
}

type managedMQTTClient interface {
	Publish(topic string, payload []byte, retained bool) error
	Disconnect(quiesce uint)
}

func main() {
	var configDir string
	var dryRun bool
	var showVersion bool
	flag.StringVar(&configDir, "config-dir", "", "rig daemon config directory")
	flag.BoolVar(&dryRun, "dry-run", false, "validate configuration and exit")
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.Parse()

	if showVersion {
		fmt.Println(version.Version)
		return
	}

	cfg, err := rigconfig.Load(configDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "configuration error: %v\n", err)
		os.Exit(2)
	}
	if dryRun {
		fmt.Printf("txing-sparkplug-manager version=%s rig=%s town=%s ipc=%s\n", version.Version, cfg.RigID, cfg.TownID, cfg.IPCSocket)
		return
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, cfg); err != nil {
		fmt.Fprintf(os.Stderr, "sparkplug manager stopped with error: %v\n", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, cfg rigconfig.Config) error {
	awsConfig, err := awsx.LoadConfig(ctx, cfg)
	if err != nil {
		return err
	}
	logger := awsx.NewCloudWatchLogger(
		cloudwatchlogs.NewFromConfig(awsConfig),
		cfg.CloudWatchLogGroup,
		"txing-sparkplug-manager",
		cfg.CloudWatchRetentionDays,
	)
	logger.Ensure(ctx)
	logger.Print(ctx, "info", fmt.Sprintf("version=%s rig=%s town=%s", version.Version, cfg.RigID, cfg.TownID))

	broker := ipc.NewBroker(cfg.IPCSocket)
	brokerErrors := make(chan error, 1)
	go func() { brokerErrors <- broker.Serve(ctx) }()

	ipcClient, err := ipc.Dial(ctx, cfg.IPCSocket)
	if err != nil {
		return err
	}
	defer ipcClient.Close()
	for _, filter := range []string{
		protocol.CapabilityStateTopicPrefix + "/#",
		protocol.CapabilityCommandResultTopicPrefix + "/#",
		protocol.CapabilityHeartbeatTopicPrefix + "/#",
		shadowUpdateFilter,
	} {
		if err := ipcClient.Subscribe(filter); err != nil {
			return err
		}
	}

	state := &runtimeState{
		cfg:                     cfg,
		logger:                  logger,
		broker:                  broker,
		ipcClient:               ipcClient,
		registry:                registry.New(awsConfig),
		devices:                 map[string]*managedDevice{},
		boardStateSubscriptions: map[string]struct{}{},
	}
	if err := state.connectNodeMQTT(ctx); err != nil {
		return err
	}
	if err := state.refreshInventory(ctx); err != nil {
		logger.Print(ctx, "warning", fmt.Sprintf("initial inventory refresh failed error=%q", err))
	}

	inventoryTicker := time.NewTicker(cfg.InventoryInterval)
	defer inventoryTicker.Stop()
	publishTicker := time.NewTicker(devicePublishInterval)
	defer publishTicker.Stop()

	messages := make(chan ipc.Message, 256)
	ipcErrors := make(chan error, 1)
	go func() {
		for {
			message, err := ipcClient.Receive()
			if err != nil {
				ipcErrors <- err
				return
			}
			messages <- message
		}
	}()

	for {
		select {
		case <-ctx.Done():
			state.gracefulShutdown(context.Background())
			return nil
		case err := <-brokerErrors:
			if err != nil {
				return err
			}
		case err := <-ipcErrors:
			return fmt.Errorf("IPC receive failed: %w", err)
		case <-inventoryTicker.C:
			if err := state.refreshInventory(ctx); err != nil {
				logger.Print(ctx, "warning", fmt.Sprintf("inventory refresh failed error=%q", err))
			}
		case <-publishTicker.C:
			state.publishDeviceState(ctx)
		case message := <-messages:
			state.handleIPCMessage(ctx, message)
		}
	}
}

func (s *runtimeState) connectNodeMQTT(ctx context.Context) error {
	willPayload, err := sparkplug.BuildNodeDeathPayload(manager.NodeRedconDead, nodeBDSeq, uint64(time.Now().UnixMilli()))
	if err != nil {
		return err
	}
	initialOnline := make(chan error, 1)
	var initialOnlineDone atomic.Bool
	var client *mqttx.Client
	client, err = mqttx.New(mqttx.Options{
		Config:      s.cfg,
		ClientID:    manager.NodeClientID(s.cfg.RigID),
		WillTopic:   sparkplug.BuildNodeTopic(s.cfg.TownID, "NDEATH", s.cfg.RigID),
		WillPayload: willPayload,
		OnMessage: func(message mqttx.Message) {
			s.handleMQTTMessage(context.Background(), message)
		},
		OnConnectionLost: func(err error) {
			s.logger.Print(context.Background(), "warning", fmt.Sprintf("node MQTT disconnected error=%q", err))
		},
		OnConnection: func() {
			err := s.publishNodeOnline(client)
			if !initialOnlineDone.Load() {
				select {
				case initialOnline <- err:
				default:
				}
			}
			if err != nil {
				s.logger.Print(context.Background(), "warning", fmt.Sprintf("node MQTT online publish failed error=%q", err))
				return
			}
			s.logger.Print(context.Background(), "info", "sparkplug node MQTT connected")
		},
	})
	if err != nil {
		return err
	}
	if err := client.Connect(); err != nil {
		return err
	}
	select {
	case err := <-initialOnline:
		initialOnlineDone.Store(true)
		if err != nil {
			return err
		}
	case <-time.After(30 * time.Second):
		initialOnlineDone.Store(true)
		return fmt.Errorf("node MQTT online publish timed out")
	}
	s.nodeMQTT = client
	return nil
}

func (s *runtimeState) publishNodeOnline(client nodeMQTTClient) error {
	if err := client.Subscribe(sparkplug.BuildDeviceTopic(s.cfg.TownID, "DCMD", s.cfg.RigID, "+"), nil); err != nil {
		return err
	}
	if err := client.Subscribe(boardRetainedCapabilityStateFilter, nil); err != nil {
		return err
	}
	s.resetBoardStateSubscriptions()
	for _, thingName := range s.knownDeviceNames() {
		if err := s.ensureBoardStateSubscription(client, thingName); err != nil {
			return err
		}
	}
	seq := s.nextNodeSeq()
	payload, err := sparkplug.BuildNodeBirthPayload(manager.NodeRedconBorn, nodeBDSeq, seq, uint64(time.Now().UnixMilli()))
	if err != nil {
		return err
	}
	if err := client.Publish(sparkplug.BuildNodeTopic(s.cfg.TownID, "NBIRTH", s.cfg.RigID), payload, false); err != nil {
		return err
	}
	return nil
}

func (s *runtimeState) refreshInventory(ctx context.Context) error {
	loaded, err := s.registry.LoadInventory(ctx, s.cfg.RigID)
	if err != nil {
		return err
	}
	for _, device := range loaded.Devices {
		var created bool
		s.deviceMu.Lock()
		managed := s.devices[device.ThingName]
		if managed == nil {
			managed = &managedDevice{state: manager.NewDeviceRuntimeState(device)}
			s.devices[device.ThingName] = managed
			created = true
		} else {
			managed.state.ReplaceInventory(device)
		}
		s.deviceMu.Unlock()

		if created {
			if err := s.ensureDeviceMQTT(device.ThingName, managed); err != nil {
				s.logger.Print(ctx, "warning", fmt.Sprintf("device MQTT connect failed thing=%s error=%q", device.ThingName, err))
			}
		}
		if s.nodeMQTT != nil {
			if err := s.ensureBoardStateSubscription(s.nodeMQTT, device.ThingName); err != nil {
				s.logger.Print(ctx, "warning", fmt.Sprintf("board retained state subscribe failed thing=%s error=%q", device.ThingName, err))
			}
		}
	}
	for thingName, managed := range s.deviceSnapshot() {
		found := false
		for _, device := range loaded.Devices {
			if device.ThingName == thingName {
				found = true
				break
			}
		}
		if !found {
			if managed.mqtt != nil {
				managed.mqtt.Disconnect(250)
			}
			s.deviceMu.Lock()
			delete(s.devices, thingName)
			s.deviceMu.Unlock()
			s.clearBoardStateSubscription(thingName)
		}
	}
	inventory := protocol.NewInventory(managerID, loaded.Devices, s.inventorySeq, uint64(time.Now().UnixMilli()))
	s.inventorySeq++
	payload, err := inventory.Marshal()
	if err != nil {
		return err
	}
	s.broker.Publish(protocol.InventoryTopic, payload, true)
	s.logger.Print(ctx, "info", fmt.Sprintf("inventory refreshed rigType=%s devices=%d", loaded.RigType, len(loaded.Devices)))
	return nil
}

func (s *runtimeState) ensureDeviceMQTT(thingName string, managed *managedDevice) error {
	if managed.mqtt != nil {
		return nil
	}
	willPayload, err := sparkplug.BuildDeviceDeathPayload(0, uint64(time.Now().UnixMilli()))
	if err != nil {
		return err
	}
	client, err := mqttx.New(mqttx.Options{
		Config:      s.cfg,
		ClientID:    thingName,
		WillTopic:   sparkplug.BuildDeviceTopic(s.cfg.TownID, "DDEATH", s.cfg.RigID, thingName),
		WillPayload: willPayload,
		OnConnectionLost: func(err error) {
			s.logger.Print(context.Background(), "warning", fmt.Sprintf("device MQTT disconnected thing=%s error=%q", thingName, err))
		},
	})
	if err != nil {
		return err
	}
	if err := client.Connect(); err != nil {
		return err
	}
	managed.mqtt = client
	return nil
}

func (s *runtimeState) handleMQTTMessage(ctx context.Context, message mqttx.Message) {
	if thingName, ok := parseSparkplugDCMDTopic(s.cfg.TownID, s.cfg.RigID, message.Topic); ok {
		s.commandSeq++
		deadline := uint64(time.Now().Add(s.cfg.CommandDeadline).UnixMilli())
		command, err := manager.CommandFromDCMD(thingName, message.Payload, fmt.Sprintf("dcmd-%s-%d", thingName, s.commandSeq), uint64(time.Now().UnixMilli()), &deadline)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("DCMD decode failed topic=%s error=%q", message.Topic, err))
			return
		}
		if command == nil {
			return
		}
		s.infoPrint(ctx, fmt.Sprintf("REDCON command received thing=%s targetRedcon=%d command=%s source=sparkplug-dcmd topic=%s", thingName, command.Target.Redcon, command.CommandID, message.Topic))
		payload, err := command.Marshal()
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("command encode failed thing=%s error=%q", thingName, err))
			return
		}
		topic, err := protocol.BuildCapabilityCommandTopic(thingName)
		if err != nil {
			return
		}
		s.broker.Publish(topic, payload, false)
		return
	}
	if thingName, ok := parseBoardCapabilityStateTopic(message.Topic); ok {
		var state protocol.CapabilityState
		if err := json.Unmarshal(message.Payload, &state); err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("board retained state decode failed thing=%s error=%q", thingName, err))
			return
		}
		if state.ThingName == "" {
			state.ThingName = thingName
		}
		if state.Metrics == nil {
			state.Metrics = map[string]protocol.MetricValue{}
		}
		payload, err := state.Marshal()
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("board retained state encode failed thing=%s error=%q", thingName, err))
			return
		}
		topic, err := protocol.BuildCapabilityStateTopic(state.ThingName, state.AdapterID)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("board retained state topic invalid error=%q", err))
			return
		}
		s.broker.Publish(topic, payload, true)
	}
}

func (s *runtimeState) handleIPCMessage(ctx context.Context, message ipc.Message) {
	if isThingShadowUpdateTopic(message.Topic) {
		if s.nodeMQTT == nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("shadow update dropped before MQTT connection topic=%s", message.Topic))
			return
		}
		if err := s.nodeMQTT.Publish(message.Topic, message.Payload, false); err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("shadow update publish failed topic=%s error=%q", message.Topic, err))
		}
		return
	}
	if thingName, _, ok := protocol.ParseCapabilityStateTopic(message.Topic); ok {
		state, err := protocol.DecodeCapabilityState(message.Payload)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("capability state decode failed topic=%s error=%q", message.Topic, err))
			return
		}
		managed := s.devices[thingName]
		if managed == nil {
			return
		}
		if err := managed.state.ObserveState(state); err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("capability state rejected topic=%s error=%q", message.Topic, err))
		}
		return
	}
	if thingName, _, ok := protocol.ParseCapabilityCommandResultTopic(message.Topic); ok {
		result, err := protocol.DecodeCapabilityCommandResult(message.Payload)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("command result decode failed topic=%s error=%q", message.Topic, err))
			return
		}
		managed := s.devices[thingName]
		if managed == nil || managed.mqtt == nil {
			return
		}
		metrics, err := manager.CommandResultMetrics(result)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("command result metrics failed topic=%s error=%q", message.Topic, err))
			return
		}
		redcon := uint8(4)
		if snapshot := managed.state.Snapshot(uint64(time.Now().UnixMilli())); snapshot.Redcon != nil {
			redcon = *snapshot.Redcon
		}
		seq := managed.nextSeq()
		payload, err := sparkplug.BuildDeviceReportPayload(redcon, seq, uint64(time.Now().UnixMilli()), metrics)
		if err != nil {
			return
		}
		if err := managed.mqtt.Publish(sparkplug.BuildDeviceTopic(s.cfg.TownID, "DDATA", s.cfg.RigID, thingName), payload, false); err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("publish command result DDATA failed thing=%s error=%q", thingName, err))
		}
	}
}

func (s *runtimeState) publishDeviceState(ctx context.Context) {
	for thingName, managed := range s.devices {
		if managed.mqtt == nil {
			if err := s.ensureDeviceMQTT(thingName, managed); err != nil {
				s.logger.Print(ctx, "warning", fmt.Sprintf("device MQTT reconnect failed thing=%s error=%q", thingName, err))
				continue
			}
		}
		publication, err := managed.state.DecidePublication(uint64(time.Now().UnixMilli()))
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("device publication decision failed thing=%s error=%q", thingName, err))
			continue
		}
		switch publication.Kind {
		case manager.PublicationBirth:
			s.publishDeviceReport(ctx, managed, thingName, "DBIRTH", publication.Redcon, publication.Metrics)
		case manager.PublicationData:
			s.publishDeviceReport(ctx, managed, thingName, "DDATA", publication.Redcon, publication.Metrics)
		case manager.PublicationDeath:
			s.publishDeviceDeath(ctx, managed, thingName)
		}
	}
}

func (s *runtimeState) publishDeviceReport(ctx context.Context, managed *managedDevice, thingName, messageType string, redcon uint8, metrics []sparkplug.Metric) {
	seq := managed.nextSeq()
	payload, err := sparkplug.BuildDeviceReportPayload(redcon, seq, uint64(time.Now().UnixMilli()), metrics)
	if err != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("build %s failed thing=%s error=%q", messageType, thingName, err))
		return
	}
	if err := managed.mqtt.Publish(sparkplug.BuildDeviceTopic(s.cfg.TownID, messageType, s.cfg.RigID, thingName), payload, false); err != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("publish %s failed thing=%s error=%q", messageType, thingName, err))
	}
}

func (s *runtimeState) publishDeviceDeath(ctx context.Context, managed *managedDevice, thingName string) {
	seq := managed.nextSeq()
	payload, err := sparkplug.BuildDeviceDeathPayload(seq, uint64(time.Now().UnixMilli()))
	if err != nil {
		if s.logger != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("build DDEATH failed thing=%s error=%q", thingName, err))
		}
		return
	}
	if err := managed.mqtt.Publish(sparkplug.BuildDeviceTopic(s.cfg.TownID, "DDEATH", s.cfg.RigID, thingName), payload, false); err != nil && s.logger != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("publish DDEATH failed thing=%s error=%q", thingName, err))
	}
}

func (s *runtimeState) gracefulShutdown(ctx context.Context) {
	for thingName, managed := range s.devices {
		if managed.mqtt == nil {
			continue
		}
		s.publishDeviceDeath(ctx, managed, thingName)
		managed.mqtt.Disconnect(250)
	}
	if s.nodeMQTT != nil {
		payload, err := sparkplug.BuildNodeDeathPayload(manager.NodeRedconDead, nodeBDSeq, uint64(time.Now().UnixMilli()))
		if err == nil {
			_ = s.nodeMQTT.Publish(sparkplug.BuildNodeTopic(s.cfg.TownID, "NDEATH", s.cfg.RigID), payload, false)
		}
		s.nodeMQTT.Disconnect(250)
	}
	s.logger.Print(ctx, "info", "sparkplug manager stopped")
}

func (s *runtimeState) nextNodeSeq() uint64 {
	seq := s.nodeSeq
	s.nodeSeq = (s.nodeSeq + 1) % 256
	return seq
}

func (s *runtimeState) knownDeviceNames() []string {
	s.deviceMu.RLock()
	defer s.deviceMu.RUnlock()
	names := make([]string, 0, len(s.devices))
	for thingName := range s.devices {
		names = append(names, thingName)
	}
	sort.Strings(names)
	return names
}

func (s *runtimeState) deviceSnapshot() map[string]*managedDevice {
	s.deviceMu.RLock()
	defer s.deviceMu.RUnlock()
	snapshot := make(map[string]*managedDevice, len(s.devices))
	for thingName, managed := range s.devices {
		snapshot[thingName] = managed
	}
	return snapshot
}

func (s *runtimeState) ensureBoardStateSubscription(client nodeMQTTClient, thingName string) error {
	if client == nil || thingName == "" {
		return nil
	}
	s.boardStateMu.Lock()
	if s.boardStateSubscriptions == nil {
		s.boardStateSubscriptions = map[string]struct{}{}
	}
	if _, ok := s.boardStateSubscriptions[thingName]; ok {
		s.boardStateMu.Unlock()
		return nil
	}
	s.boardStateSubscriptions[thingName] = struct{}{}
	s.boardStateMu.Unlock()

	topic := boardRetainedCapabilityStateTopic(thingName)
	if err := client.Subscribe(topic, nil); err != nil {
		s.clearBoardStateSubscription(thingName)
		return fmt.Errorf("subscribe %s: %w", topic, err)
	}
	return nil
}

func (s *runtimeState) resetBoardStateSubscriptions() {
	s.boardStateMu.Lock()
	defer s.boardStateMu.Unlock()
	s.boardStateSubscriptions = map[string]struct{}{}
}

func (s *runtimeState) clearBoardStateSubscription(thingName string) {
	s.boardStateMu.Lock()
	defer s.boardStateMu.Unlock()
	delete(s.boardStateSubscriptions, thingName)
}

func boardRetainedCapabilityStateTopic(thingName string) string {
	return fmt.Sprintf("txings/%s/capability/v2/state", thingName)
}

func (d *managedDevice) nextSeq() uint64 {
	seq := d.seq
	d.seq = (d.seq + 1) % 256
	return seq
}

func (s *runtimeState) infoPrint(ctx context.Context, message string) {
	if s.logger == nil {
		return
	}
	s.logger.Print(ctx, "info", message)
}

func parseSparkplugDCMDTopic(groupID, edgeNodeID, topic string) (string, bool) {
	prefix := fmt.Sprintf("%s/%s/DCMD/%s/", sparkplug.Namespace, groupID, edgeNodeID)
	thingName, ok := strings.CutPrefix(topic, prefix)
	if !ok || thingName == "" || strings.Contains(thingName, "/") {
		return "", false
	}
	return thingName, true
}

func parseBoardCapabilityStateTopic(topic string) (string, bool) {
	const prefix = "txings/"
	const suffix = "/capability/v2/state"
	value, ok := strings.CutPrefix(topic, prefix)
	if !ok {
		return "", false
	}
	thingName, rest, ok := strings.Cut(value, "/")
	if !ok || rest != strings.TrimPrefix(suffix, "/") || thingName == "" {
		return "", false
	}
	return thingName, true
}

func isThingShadowUpdateTopic(topic string) bool {
	if !strings.HasPrefix(topic, "$aws/things/") {
		return false
	}
	parts := strings.Split(topic, "/")
	return len(parts) == 7 &&
		parts[0] == "$aws" &&
		parts[1] == "things" &&
		parts[2] != "" &&
		parts[3] == "shadow" &&
		parts[4] == "name" &&
		parts[5] != "" &&
		parts[6] == "update"
}
