package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/mparkachov/txing/rig/internal/awsx"
	rigble "github.com/mparkachov/txing/rig/internal/ble"
	"github.com/mparkachov/txing/rig/internal/ipc"
	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
	"github.com/mparkachov/txing/rig/internal/version"
	"tinygo.org/x/bluetooth"
)

type runtimeState struct {
	cfg                   rigconfig.Config
	logger                *awsx.CloudWatchLogger
	ipc                   *ipc.Client
	specs                 map[string]rigble.DeviceSpec
	sessions              map[string]*deviceSession
	addresses             map[string]bluetooth.Address
	cachedAdvertisements  map[string]rigble.Advertisement
	scannerLastPublished  map[string]uint64
	lastStateRead         map[string]time.Time
	activeConnects        map[string]chan struct{}
	connectSlots          chan struct{}
	scanStoppedForConnect bool
	seq                   uint64
	mu                    sync.Mutex
	txingUUID             bluetooth.UUID
	commandUUID           bluetooth.UUID
	stateUUID             bluetooth.UUID
	powerUUID             bluetooth.UUID
	weatherUUID           bluetooth.UUID
	connector             bleConnector
	sampleSink            func(rigble.CapabilitySample, bool, bool)
	commandResultSink     func(protocol.CapabilityCommand, string, *string, *uint8)
}

func main() {
	var configDir string
	var dryRun bool
	var showVersion bool
	var noBLE bool
	flag.StringVar(&configDir, "config-dir", "", "rig daemon config directory")
	flag.BoolVar(&dryRun, "dry-run", false, "validate configuration and exit")
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.BoolVar(&noBLE, "no-ble", false, "disable BLE hardware access and publish offline state")
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
	if noBLE {
		cfg.NoBLE = true
	}
	if dryRun {
		fmt.Printf("txing-ble-connectivity version=%s rig=%s town=%s ipc=%s noBle=%t\n", version.Version, cfg.RigID, cfg.TownID, cfg.IPCSocket, cfg.NoBLE)
		return
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, cfg); err != nil {
		fmt.Fprintf(os.Stderr, "ble connectivity stopped with error: %v\n", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, cfg rigconfig.Config) error {
	awsConfig, err := awsx.LoadConfig(ctx, cfg)
	if err != nil {
		return err
	}
	logger := awsx.NewCloudWatchLogger(cloudwatchlogs.NewFromConfig(awsConfig), cfg.CloudWatchLogGroup, "txing-ble-connectivity", cfg.CloudWatchRetentionDays)
	logger.Ensure(ctx)
	logger.Print(ctx, "info", fmt.Sprintf("version=%s rig=%s noBle=%t", version.Version, cfg.RigID, cfg.NoBLE))

	client, err := ipc.Dial(ctx, cfg.IPCSocket)
	if err != nil {
		return err
	}
	defer client.Close()
	for _, filter := range []string{
		protocol.InventoryTopic,
		protocol.CapabilityCommandTopicPrefix + "/#",
	} {
		if err := client.Subscribe(filter); err != nil {
			return err
		}
	}

	state, err := newRuntimeState(cfg, logger, client)
	if err != nil {
		return err
	}

	if !cfg.NoBLE {
		if err := bluetooth.DefaultAdapter.Enable(); err != nil {
			return err
		}
		go state.scanLoop(ctx)
	}

	messages := make(chan ipc.Message, 256)
	ipcErrors := make(chan error, 1)
	go func() {
		for {
			message, err := client.Receive()
			if err != nil {
				ipcErrors <- err
				return
			}
			messages <- message
		}
	}()

	heartbeat := time.NewTicker(cfg.HeartbeatInterval)
	defer heartbeat.Stop()
	for {
		select {
		case <-ctx.Done():
			logger.Print(context.Background(), "info", "ble connectivity stopped")
			return nil
		case err := <-ipcErrors:
			return fmt.Errorf("IPC receive failed: %w", err)
		case <-heartbeat.C:
			state.publishHeartbeat(ctx, nil)
		case message := <-messages:
			state.handleIPCMessage(ctx, message)
		}
	}
}

func newRuntimeState(cfg rigconfig.Config, logger *awsx.CloudWatchLogger, client *ipc.Client) (*runtimeState, error) {
	parse := func(value string) (bluetooth.UUID, error) {
		return bluetooth.ParseUUID(value)
	}
	txingUUID, err := parse(rigble.TxingBLEServiceUUID)
	if err != nil {
		return nil, err
	}
	commandUUID, err := parse(rigble.TxingBLECommandUUID)
	if err != nil {
		return nil, err
	}
	stateUUID, err := parse(rigble.TxingBLEStateUUID)
	if err != nil {
		return nil, err
	}
	powerUUID, err := parse(rigble.PowerMeasurementUUID)
	if err != nil {
		return nil, err
	}
	weatherUUID, err := parse(rigble.WeatherMeasurementUUID)
	if err != nil {
		return nil, err
	}
	var connectSlots chan struct{}
	if cfg.MaxBLEConnections > 0 {
		connectSlots = make(chan struct{}, cfg.MaxBLEConnections)
	}
	state := &runtimeState{
		cfg:                  cfg,
		logger:               logger,
		ipc:                  client,
		specs:                map[string]rigble.DeviceSpec{},
		sessions:             map[string]*deviceSession{},
		addresses:            map[string]bluetooth.Address{},
		cachedAdvertisements: map[string]rigble.Advertisement{},
		scannerLastPublished: map[string]uint64{},
		lastStateRead:        map[string]time.Time{},
		activeConnects:       map[string]chan struct{}{},
		connectSlots:         connectSlots,
		txingUUID:            txingUUID,
		commandUUID:          commandUUID,
		stateUUID:            stateUUID,
		powerUUID:            powerUUID,
		weatherUUID:          weatherUUID,
	}
	state.connector = state
	return state, nil
}

func (s *runtimeState) handleIPCMessage(ctx context.Context, message ipc.Message) {
	if message.Topic == protocol.InventoryTopic {
		inventory, err := protocol.DecodeInventory(message.Payload)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("inventory decode failed error=%q", err))
			return
		}
		s.reconcileInventory(ctx, inventory)
		return
	}
	if thingName, ok := protocol.ParseCapabilityCommandTopic(message.Topic); ok {
		command, err := protocol.DecodeCapabilityCommand(message.Payload)
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("command decode failed topic=%s error=%q", message.Topic, err))
			return
		}
		if command.ThingName != thingName {
			s.logger.Print(ctx, "warning", fmt.Sprintf("command thing mismatch topic=%s payloadThing=%s", message.Topic, command.ThingName))
			return
		}
		s.dispatchCommand(ctx, command)
	}
}

func (s *runtimeState) reconcileInventory(ctx context.Context, inventory protocol.Inventory) {
	next := map[string]rigble.DeviceSpec{}
	for _, device := range inventory.Devices {
		spec := rigble.DeviceSpecFromInventory(device)
		if spec != nil {
			next[spec.ThingName] = *spec
		}
	}
	deliveries := s.updateInventorySessions(ctx, next)
	s.logger.Print(ctx, "info", fmt.Sprintf("BLE inventory reconciled devices=%d", len(next)))
	for _, delivery := range deliveries {
		delivery.session.enqueueAdvertisement(ctx, delivery.advertisement)
	}
}

type sessionAdvertisementDelivery struct {
	session       *deviceSession
	advertisement rigble.Advertisement
}

func (s *runtimeState) updateInventorySessions(ctx context.Context, next map[string]rigble.DeviceSpec) []sessionAdvertisementDelivery {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.sessions == nil {
		s.sessions = map[string]*deviceSession{}
	}
	for thingName, session := range s.sessions {
		nextSpec, ok := next[thingName]
		if !ok || nextSpec.Kind != session.spec.Kind {
			session.stop()
			delete(s.sessions, thingName)
		}
	}
	deliveries := make([]sessionAdvertisementDelivery, 0, len(next))
	for thingName, spec := range next {
		session, ok := s.sessions[thingName]
		if !ok {
			session = newDeviceSession(s, spec)
			s.sessions[thingName] = session
			go session.run(ctx)
		}
		if advertisement, ok := s.cachedAdvertisements[thingName]; ok {
			deliveries = append(deliveries, sessionAdvertisementDelivery{session: session, advertisement: advertisement})
		}
	}
	s.specs = next
	return deliveries
}

func (s *runtimeState) scanLoop(ctx context.Context) {
	var failures uint32
	for ctx.Err() == nil {
		err := s.scan(ctx)
		if ctx.Err() != nil {
			return
		}
		if s.consumeScanStoppedForConnect() {
			failures = 0
			s.waitForActiveConnects(ctx)
			continue
		}
		decision := scanRetryDecision(err, failures)
		failures = decision.nextFailures
		if decision.resetDiscovery {
			_ = bluetooth.DefaultAdapter.StopScan()
		}
		if err != nil {
			s.logger.Print(context.Background(), "warning", fmt.Sprintf("BLE scan stopped error=%q retryMs=%d", err, decision.delayMS))
		} else {
			s.logger.Print(context.Background(), "warning", fmt.Sprintf("BLE scan stopped unexpectedly retryMs=%d", decision.delayMS))
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Duration(decision.delayMS) * time.Millisecond):
		}
	}
}

type scanRetry struct {
	delayMS        uint64
	nextFailures   uint32
	resetDiscovery bool
}

func scanRetryDecision(err error, failures uint32) scanRetry {
	if err != nil && rigble.BLEErrorIndicatesInProgress(err.Error()) {
		return scanRetry{
			delayMS:        rigble.BluezInProgressScanRetryDelayMS,
			nextFailures:   0,
			resetDiscovery: true,
		}
	}
	return scanRetry{
		delayMS:      rigble.BoundedRetryDelayMS(rigble.BLERetryMinDelayMS, failures, rigble.BLERetryMaxDelayMS),
		nextFailures: failures + 1,
	}
}

func (s *runtimeState) scan(ctx context.Context) error {
	s.debugPrint(ctx, "BLE scan starting")
	err := bluetooth.DefaultAdapter.Scan(func(adapter *bluetooth.Adapter, result bluetooth.ScanResult) {
		select {
		case <-ctx.Done():
			_ = adapter.StopScan()
			return
		default:
		}
		name := result.LocalName()
		hasTxingService := result.HasServiceUUID(s.txingUUID)
		knownTarget := s.hasSpec(name)
		if s.shouldDebugScanCandidate(name, hasTxingService, knownTarget) {
			s.debugPrint(
				context.Background(),
				fmt.Sprintf(
					"BLE scan candidate name=%q address=%s rssi=%d txingService=%t knownTarget=%t serviceUUIDs=%v",
					name,
					result.Address.String(),
					result.RSSI,
					hasTxingService,
					knownTarget,
					scanServiceUUIDs(result),
				),
			)
		}
		if !hasTxingService {
			if s.shouldDebugScanCandidate(name, hasTxingService, knownTarget) {
				s.debugPrint(context.Background(), fmt.Sprintf("BLE scan ignored name=%q address=%s reason=no-txing-service", name, result.Address.String()))
			}
			return
		}
		if name == "" {
			s.debugPrint(context.Background(), fmt.Sprintf("BLE scan ignored address=%s reason=missing-local-name serviceUUIDs=%v", result.Address.String(), scanServiceUUIDs(result)))
			return
		}
		rssi := result.RSSI
		identity := name
		now := time.Now()
		advertisement := rigble.Advertisement{
			Address:      result.Address.String(),
			IdentityName: &identity,
			Services:     []string{rigble.TxingBLEServiceUUID},
			RSSI:         &rssi,
			ObservedAtMS: uint64(now.UnixMilli()),
			Seq:          s.nextSeq(),
		}
		s.recordAdvertisement(name, result.Address, advertisement)
		s.mu.Lock()
		_, ok := s.specs[name]
		s.mu.Unlock()
		if !ok {
			s.debugPrint(context.Background(), fmt.Sprintf("BLE scan ignored name=%q address=%s reason=unmanaged-target cachedAddress=true", name, result.Address.String()))
			return
		}
		s.dispatchAdvertisement(context.Background(), name, result.Address, advertisement)
	})
	if err != nil && ctx.Err() == nil {
		return err
	}
	return nil
}

func (s *runtimeState) dispatchAdvertisement(ctx context.Context, thingName string, address bluetooth.Address, advertisement rigble.Advertisement) {
	s.recordAdvertisement(thingName, address, advertisement)
	s.mu.Lock()
	if s.scannerLastPublished == nil {
		s.scannerLastPublished = map[string]uint64{}
	}
	session := s.sessions[thingName]
	if session == nil {
		s.mu.Unlock()
		return
	}
	targets := map[string]struct{}{thingName: {}}
	shouldPublish := rigble.ShouldPublishScannerAdvertisement(targets, advertisement, uint64(time.Now().UnixMilli()), s.scannerLastPublished, uint64(advertisementBroadcastPeriod/time.Millisecond))
	s.mu.Unlock()
	if !shouldPublish {
		return
	}
	session.enqueueAdvertisement(ctx, advertisement)
}

func (s *runtimeState) dispatchCommand(ctx context.Context, command protocol.CapabilityCommand) {
	s.mu.Lock()
	session := s.sessions[command.ThingName]
	s.mu.Unlock()
	if session == nil {
		message := "device is not managed by BLE connectivity"
		s.publishCommandResult(ctx, command, protocol.CommandRejected, &message, &command.Target.Redcon)
		return
	}
	if !session.enqueueCommand(ctx, command) {
		message := "BLE device session command queue is full"
		s.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
	}
}

func (s *runtimeState) recordAdvertisement(thingName string, address bluetooth.Address, advertisement rigble.Advertisement) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.addresses == nil {
		s.addresses = map[string]bluetooth.Address{}
	}
	if s.cachedAdvertisements == nil {
		s.cachedAdvertisements = map[string]rigble.Advertisement{}
	}
	s.addresses[thingName] = address
	s.cachedAdvertisements[thingName] = advertisement
}

func (s *runtimeState) backgroundConnectContext(ctx context.Context) (context.Context, context.CancelFunc) {
	timeoutMS := rigble.ConnectSessionTimeoutMS(uint64(s.cfg.ConnectTimeout / time.Millisecond))
	return context.WithTimeout(ctx, time.Duration(timeoutMS)*time.Millisecond)
}

func (s *runtimeState) commandContext(ctx context.Context, command protocol.CapabilityCommand) (context.Context, context.CancelFunc) {
	deadline := time.Now().Add(s.cfg.CommandDeadline)
	if command.DeadlineMS != nil {
		commandDeadline := time.UnixMilli(int64(*command.DeadlineMS))
		if commandDeadline.Before(deadline) {
			deadline = commandDeadline
		}
	}
	return context.WithDeadline(ctx, deadline)
}

func (s *runtimeState) recordStateRead(thingName string, observedAt time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.lastStateRead == nil {
		s.lastStateRead = map[string]time.Time{}
	}
	s.lastStateRead[thingName] = observedAt
}

func (s *runtimeState) pauseScanForConnect() {
	if err := bluetooth.DefaultAdapter.StopScan(); err != nil {
		return
	}
	s.mu.Lock()
	s.scanStoppedForConnect = true
	s.mu.Unlock()
}

func (s *runtimeState) consumeScanStoppedForConnect() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	stopped := s.scanStoppedForConnect
	s.scanStoppedForConnect = false
	return stopped
}

func (s *runtimeState) waitForActiveConnects(ctx context.Context) {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		s.mu.Lock()
		active := len(s.activeConnects)
		s.mu.Unlock()
		if active == 0 {
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (s *runtimeState) discoveryUUIDs(spec rigble.DeviceSpec) []bluetooth.UUID {
	uuids := []bluetooth.UUID{s.commandUUID, s.stateUUID, s.powerUUID}
	if spec.Kind.SupportsWeather() {
		uuids = append(uuids, s.weatherUUID)
	}
	return uuids
}

func (s *runtimeState) acquireDeviceConnect(ctx context.Context, thingName string) (func(), error) {
	for {
		s.mu.Lock()
		if s.activeConnects == nil {
			s.activeConnects = map[string]chan struct{}{}
		}
		done, active := s.activeConnects[thingName]
		if !active {
			done = make(chan struct{})
			s.activeConnects[thingName] = done
			s.mu.Unlock()
			return func() {
				s.mu.Lock()
				if s.activeConnects[thingName] == done {
					delete(s.activeConnects, thingName)
					close(done)
				}
				s.mu.Unlock()
			}, nil
		}
		s.mu.Unlock()
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-done:
		}
	}
}

func (s *runtimeState) acquireConnectSlot(ctx context.Context) (func(), error) {
	if s.connectSlots == nil {
		return func() {}, nil
	}
	select {
	case s.connectSlots <- struct{}{}:
		return func() { <-s.connectSlots }, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func readCharacteristic(characteristic bluetooth.DeviceCharacteristic, size int) ([]byte, error) {
	buffer := make([]byte, size)
	n, err := characteristic.Read(buffer)
	if err != nil {
		return nil, err
	}
	return append([]byte(nil), buffer[:n]...), nil
}

func (s *runtimeState) publishSample(ctx context.Context, sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
	if s.sampleSink != nil {
		s.sampleSink(sample, includeShadow, includeCapabilityState)
		return
	}
	if includeCapabilityState {
		state := rigble.CapabilityStateFromSample(rigble.AdapterID, sample)
		payload, err := state.Marshal()
		if err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("capability state encode failed thing=%s error=%q", sample.ThingName, err))
			return
		}
		topic, err := protocol.BuildCapabilityStateTopic(sample.ThingName, rigble.AdapterID)
		if err == nil {
			if err := s.ipc.PublishRetained(topic, payload); err != nil {
				s.logger.Print(ctx, "warning", fmt.Sprintf("capability state publish failed thing=%s error=%q", sample.ThingName, err))
			} else {
				s.debugPrint(ctx, fmt.Sprintf("BLE capability state published thing=%s topic=%s capabilities=%s metrics=%s", sample.ThingName, topic, _jsonDebug(state.Capabilities), _jsonDebug(state.Metrics)))
			}
		}
	}
	if !includeShadow {
		return
	}
	updates, err := rigble.ShadowUpdatesFromSample(sample)
	if err != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("shadow update build failed thing=%s error=%q", sample.ThingName, err))
		return
	}
	for _, update := range updates {
		if err := s.ipc.Publish(update.Topic, update.Payload); err != nil {
			s.logger.Print(ctx, "warning", fmt.Sprintf("shadow update publish failed topic=%s error=%q", update.Topic, err))
		}
	}
}

func (s *runtimeState) publishHeartbeat(ctx context.Context, activeThingName *string) {
	heartbeat := protocol.NewCapabilityHeartbeat(rigble.AdapterID, protocol.HeartbeatRunning, activeThingName, uint64(time.Now().UnixMilli()), s.nextSeq())
	payload, err := heartbeat.Marshal()
	if err != nil {
		return
	}
	topic, err := protocol.BuildCapabilityHeartbeatTopic(rigble.AdapterID)
	if err != nil {
		return
	}
	if err := s.ipc.PublishRetained(topic, payload); err != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("heartbeat publish failed error=%q", err))
	}
}

func (s *runtimeState) publishCommandResult(ctx context.Context, command protocol.CapabilityCommand, status string, message *string, redcon *uint8) {
	if s.commandResultSink != nil {
		s.commandResultSink(command, status, message, redcon)
		return
	}
	topic, payload, err := rigble.PublishCommandResult(rigble.AdapterID, command, status, message, redcon, uint64(time.Now().UnixMilli()), s.nextSeq())
	if err != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("command result build failed thing=%s error=%q", command.ThingName, err))
		return
	}
	if err := s.ipc.Publish(topic, payload); err != nil {
		s.logger.Print(ctx, "warning", fmt.Sprintf("command result publish failed thing=%s error=%q", command.ThingName, err))
	}
}

func (s *runtimeState) nextSeq() uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	seq := s.seq
	s.seq++
	return seq
}

func (s *runtimeState) hasSpec(thingName string) bool {
	if thingName == "" {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.specs[thingName]
	return ok
}

func (s *runtimeState) shouldDebugScanCandidate(name string, hasTxingService bool, knownTarget bool) bool {
	return s.cfg.Debug && (hasTxingService || knownTarget || looksLikeTxingThingName(name))
}

func (s *runtimeState) debugPrint(ctx context.Context, message string) {
	if !s.cfg.Debug {
		return
	}
	s.logger.Print(ctx, "debug", message)
}

func looksLikeTxingThingName(name string) bool {
	return strings.HasPrefix(name, "unit-") ||
		strings.HasPrefix(name, "power-") ||
		strings.HasPrefix(name, "weather-")
}

func scanServiceUUIDs(result bluetooth.ScanResult) []string {
	uuids := result.ServiceUUIDs()
	values := make([]string, 0, len(uuids))
	for _, uuid := range uuids {
		values = append(values, uuid.String())
	}
	return values
}

func _jsonDebug(value any) string {
	payload, _ := json.Marshal(value)
	return string(payload)
}
