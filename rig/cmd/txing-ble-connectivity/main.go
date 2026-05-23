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
	addresses             map[string]bluetooth.Address
	lastConnect           map[string]time.Time
	lastStateRead         map[string]time.Time
	connectionHolds       map[string]uint64
	nextConnectionHold    uint64
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
}

type connectionReleasePolicy uint8

const (
	disconnectImmediately connectionReleasePolicy = iota
	holdCommandConnectionBriefly

	commandConnectionHoldDuration = 15 * time.Second
)

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
	return &runtimeState{
		cfg:             cfg,
		logger:          logger,
		ipc:             client,
		specs:           map[string]rigble.DeviceSpec{},
		addresses:       map[string]bluetooth.Address{},
		lastConnect:     map[string]time.Time{},
		lastStateRead:   map[string]time.Time{},
		connectionHolds: map[string]uint64{},
		activeConnects:  map[string]chan struct{}{},
		connectSlots:    connectSlots,
		txingUUID:       txingUUID,
		commandUUID:     commandUUID,
		stateUUID:       stateUUID,
		powerUUID:       powerUUID,
		weatherUUID:     weatherUUID,
	}, nil
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
		go s.handleCommand(ctx, command)
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
	refreshCandidates := s.updateInventorySpecs(next)
	s.logger.Print(ctx, "info", fmt.Sprintf("BLE inventory reconciled devices=%d", len(next)))
	if s.cfg.NoBLE {
		for _, spec := range next {
			s.publishSample(ctx, rigble.OfflineSample(spec, s.nextSeq(), uint64(time.Now().UnixMilli())), false, true)
		}
		return
	}
	for _, spec := range refreshCandidates {
		if s.shouldBackgroundConnect(spec.ThingName) {
			s.debugPrint(ctx, fmt.Sprintf("BLE background connect scheduled thing=%s reason=cached-address", spec.ThingName))
			go s.connectAndPublishBackground(ctx, spec)
		}
	}
}

func (s *runtimeState) updateInventorySpecs(next map[string]rigble.DeviceSpec) []rigble.DeviceSpec {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.specs = next
	refreshCandidates := make([]rigble.DeviceSpec, 0, len(next))
	for thingName, spec := range next {
		if _, ok := s.addresses[thingName]; ok {
			refreshCandidates = append(refreshCandidates, spec)
		}
	}
	return refreshCandidates
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
		s.recordAdvertisementAddress(name, result.Address)
		s.mu.Lock()
		spec, ok := s.specs[name]
		s.mu.Unlock()
		if !ok {
			s.debugPrint(context.Background(), fmt.Sprintf("BLE scan ignored name=%q address=%s reason=unmanaged-target cachedAddress=true", name, result.Address.String()))
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
		includeCapabilityState := s.shouldPublishAdvertisementCapabilityState(spec, now)
		s.publishSample(
			context.Background(),
			rigble.AdvertisementSample(spec, advertisement, s.nextSeq()),
			true,
			includeCapabilityState,
		)
		if !includeCapabilityState {
			s.debugPrint(context.Background(), fmt.Sprintf("BLE advertisement capability state suppressed thing=%s reason=recent-state-read", spec.ThingName))
		}
		s.debugPrint(context.Background(), fmt.Sprintf("BLE advertisement published thing=%s address=%s rssi=%d", spec.ThingName, result.Address.String(), rssi))
		if s.shouldBackgroundConnect(name) {
			s.debugPrint(context.Background(), fmt.Sprintf("BLE background connect scheduled thing=%s address=%s", spec.ThingName, result.Address.String()))
			go s.connectAndPublishBackground(ctx, spec)
		}
	})
	if err != nil && ctx.Err() == nil {
		return err
	}
	return nil
}

func (s *runtimeState) recordAdvertisementAddress(thingName string, address bluetooth.Address) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.addresses == nil {
		s.addresses = map[string]bluetooth.Address{}
	}
	s.addresses[thingName] = address
}

func (s *runtimeState) connectAndPublishBackground(ctx context.Context, spec rigble.DeviceSpec) {
	if s.connectionHoldActive(spec.ThingName) {
		s.debugPrint(context.Background(), fmt.Sprintf("BLE background connect skipped thing=%s reason=command-connection-held", spec.ThingName))
		return
	}
	connectCtx, cancel := s.backgroundConnectContext(ctx)
	defer cancel()
	if err := s.connectAndPublish(connectCtx, spec, nil, disconnectImmediately); err != nil {
		s.debugPrint(context.Background(), fmt.Sprintf("BLE background connect failed thing=%s error=%q", spec.ThingName, err))
		return
	}
	s.debugPrint(context.Background(), fmt.Sprintf("BLE background connect succeeded thing=%s", spec.ThingName))
}

func (s *runtimeState) backgroundConnectContext(ctx context.Context) (context.Context, context.CancelFunc) {
	timeoutMS := rigble.ConnectSessionTimeoutMS(uint64(s.cfg.ConnectTimeout / time.Millisecond))
	return context.WithTimeout(ctx, time.Duration(timeoutMS)*time.Millisecond)
}

func (s *runtimeState) shouldBackgroundConnect(thingName string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	last := s.lastConnect[thingName]
	if time.Since(last) < s.cfg.ReconnectDelay {
		return false
	}
	s.lastConnect[thingName] = time.Now()
	return true
}

func (s *runtimeState) handleCommand(ctx context.Context, command protocol.CapabilityCommand) {
	s.mu.Lock()
	spec, ok := s.specs[command.ThingName]
	s.mu.Unlock()
	if !ok {
		message := "device is not managed by BLE connectivity"
		s.publishCommandResult(ctx, command, protocol.CommandRejected, &message, &command.Target.Redcon)
		return
	}
	if protocol.CommandDeadlineExpired(command, uint64(time.Now().UnixMilli())) {
		message := "command deadline expired"
		s.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
		return
	}
	if reason := rigble.WeatherCommandRejectReason(command, spec); reason != nil {
		s.publishCommandResult(ctx, command, protocol.CommandRejected, reason, &command.Target.Redcon)
		return
	}
	if s.cfg.NoBLE {
		message := "BLE is disabled for this daemon instance"
		s.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
		return
	}
	s.publishCommandResult(ctx, command, protocol.CommandAccepted, nil, &command.Target.Redcon)
	normalized, err := protocol.NormalizeBleTargetRedcon(command.Target.Redcon)
	if err != nil {
		message := err.Error()
		s.publishCommandResult(ctx, command, protocol.CommandRejected, &message, &command.Target.Redcon)
		return
	}
	commandCtx, cancel := s.commandContext(ctx, command)
	defer cancel()
	if err := s.connectAndPublishCommand(commandCtx, command, spec, normalized); err != nil {
		message := err.Error()
		s.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
		return
	}
	s.publishCommandResult(ctx, command, protocol.CommandSucceeded, nil, &command.Target.Redcon)
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

func (s *runtimeState) connectAndPublishCommand(ctx context.Context, command protocol.CapabilityCommand, spec rigble.DeviceSpec, normalizedRedcon uint8) error {
	var failures uint32
	for {
		err := s.connectAndPublish(ctx, spec, &normalizedRedcon, commandConnectionReleasePolicy(normalizedRedcon))
		if err == nil {
			return nil
		}
		if ctx.Err() != nil {
			return fmt.Errorf("bluetooth command stopped after error: %w", err)
		}
		if protocol.CommandDeadlineExpired(command, uint64(time.Now().UnixMilli())) {
			return fmt.Errorf("bluetooth command deadline expired after error: %w", err)
		}
		message := err.Error()
		if !rigble.BLECommandConnectErrorIsRetryable(message) {
			return err
		}
		delayMS := bleCommandRetryDelayMS(spec.ThingName, message, failures)
		delay := time.Duration(delayMS) * time.Millisecond
		if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) <= delay {
			return fmt.Errorf("bluetooth command deadline expired before retry after error: %w", err)
		}
		s.logger.Print(ctx, "warning", fmt.Sprintf("BLE command connect retry thing=%s targetRedcon=%d normalizedRedcon=%d attempt=%d error=%q retryMs=%d", spec.ThingName, command.Target.Redcon, normalizedRedcon, failures+1, err, delayMS))
		select {
		case <-ctx.Done():
			return fmt.Errorf("bluetooth command stopped after error: %w", err)
		case <-time.After(delay):
		}
		failures++
	}
}

func bleCommandRetryDelayMS(thingName string, message string, failures uint32) uint64 {
	baseDelayMS := rigble.BLERetryMinDelayMS
	if rigble.BLEErrorIndicatesInProgress(message) {
		baseDelayMS = rigble.BluezInProgressReconnectDelayMS
	} else if rigble.BLEErrorIndicatesHostResourceExhaustion(message) {
		baseDelayMS = rigble.BLUEResourceExhaustedReconnectDelayMS
	}
	return rigble.BoundedRetryDelayMS(baseDelayMS, failures, rigble.BLERetryMaxDelayMS) +
		rigble.StableJitterMS(thingName, 250)
}

func commandConnectionReleasePolicy(normalizedRedcon uint8) connectionReleasePolicy {
	if normalizedRedcon == rigble.RedconIdle {
		return disconnectImmediately
	}
	return holdCommandConnectionBriefly
}

func (s *runtimeState) connectAndPublish(ctx context.Context, spec rigble.DeviceSpec, targetRedcon *uint8, successPolicy connectionReleasePolicy) error {
	releaseDevice, err := s.acquireDeviceConnect(ctx, spec.ThingName)
	if err != nil {
		return err
	}
	defer releaseDevice()
	releaseSlot, err := s.acquireConnectSlot(ctx)
	if err != nil {
		return err
	}
	defer releaseSlot()
	s.mu.Lock()
	address, ok := s.addresses[spec.ThingName]
	s.mu.Unlock()
	if !ok {
		return fmt.Errorf("no BLE advertisement address recorded for %s", spec.ThingName)
	}
	s.pauseScanForConnect()
	if err := prepareBLEConnection(ctx, address); err != nil {
		return err
	}
	device, err := bluetooth.DefaultAdapter.Connect(address, bluetooth.ConnectionParams{
		ConnectionTimeout: bluetooth.NewDuration(s.cfg.ConnectTimeout),
	})
	if err != nil {
		return err
	}
	releasePolicy := disconnectImmediately
	defer func() { s.releaseBLEDevice(spec.ThingName, device, releasePolicy) }()
	services, err := device.DiscoverServices([]bluetooth.UUID{s.txingUUID})
	if err != nil {
		return err
	}
	if len(services) == 0 {
		return fmt.Errorf("txing BLE service not found")
	}
	characteristics, err := services[0].DiscoverCharacteristics(s.discoveryUUIDs(spec))
	if err != nil {
		return err
	}
	chars := map[string]bluetooth.DeviceCharacteristic{}
	for _, characteristic := range characteristics {
		chars[characteristic.UUID().String()] = characteristic
	}
	if targetRedcon != nil {
		payload, err := rigble.EncodeRedconCommand(*targetRedcon)
		if err != nil {
			return err
		}
		commandChar, ok := chars[s.commandUUID.String()]
		if !ok {
			return fmt.Errorf("command characteristic not found")
		}
		if _, err := commandChar.Write(payload); err != nil {
			return err
		}
	}
	stateChar, ok := chars[s.stateUUID.String()]
	if !ok {
		return fmt.Errorf("state characteristic not found")
	}
	stateBytes, err := readCharacteristic(stateChar, 16)
	if err != nil {
		return err
	}
	powerChar, hasPowerChar := chars[s.powerUUID.String()]
	var powerMeasurement *rigble.PowerMeasurement
	if hasPowerChar {
		if data, err := readCharacteristic(powerChar, 16); err == nil {
			measurement, err := rigble.ParsePowerMeasurement(data)
			if err == nil {
				powerMeasurement = &measurement
			}
		}
	}
	addressText := address.String()
	observedAt := time.Now()
	now := uint64(observedAt.UnixMilli())
	if spec.Kind == rigble.DeviceKindWeather {
		state, err := rigble.ParseWeatherState(stateBytes)
		if err != nil {
			return err
		}
		var weatherMeasurement *rigble.WeatherMeasurement
		if weatherChar, ok := chars[s.weatherUUID.String()]; ok {
			if data, err := readCharacteristic(weatherChar, 32); err == nil {
				measurement, err := rigble.ParseWeatherMeasurement(data)
				if err == nil {
					weatherMeasurement = &measurement
				}
			}
		}
		s.recordStateRead(spec.ThingName, observedAt)
		s.publishSample(ctx, rigble.WeatherStateSample(spec, state.Redcon, powerMeasurement, weatherMeasurement, &addressText, s.nextSeq(), now), true, true)
		releasePolicy = successPolicy
		return nil
	}
	state, err := rigble.ParsePowerState(stateBytes)
	if err != nil {
		return err
	}
	s.recordStateRead(spec.ThingName, observedAt)
	s.publishSample(ctx, rigble.PowerStateSample(spec, state.Redcon, powerMeasurement, &addressText, s.nextSeq(), now), true, true)
	releasePolicy = successPolicy
	return nil
}

func (s *runtimeState) releaseBLEDevice(thingName string, device bluetooth.Device, policy connectionReleasePolicy) {
	if policy != holdCommandConnectionBriefly {
		s.clearConnectionHold(thingName)
		_ = device.Disconnect()
		return
	}
	token := s.recordConnectionHold(thingName)
	hold := commandConnectionHoldDuration
	s.debugPrint(context.Background(), fmt.Sprintf("BLE command connection held thing=%s holdMs=%d", thingName, hold.Milliseconds()))
	go func() {
		timer := time.NewTimer(hold)
		defer timer.Stop()
		<-timer.C
		if s.consumeConnectionHold(thingName, token) {
			_ = device.Disconnect()
			s.debugPrint(context.Background(), fmt.Sprintf("BLE command connection released thing=%s reason=hold-expired", thingName))
		}
	}()
}

func (s *runtimeState) recordStateRead(thingName string, observedAt time.Time) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.lastStateRead == nil {
		s.lastStateRead = map[string]time.Time{}
	}
	s.lastStateRead[thingName] = observedAt
}

func (s *runtimeState) shouldPublishAdvertisementCapabilityState(spec rigble.DeviceSpec, now time.Time) bool {
	if !rigble.AdvertisementPublishesCapabilityState(spec) {
		return false
	}
	if spec.Kind.SupportsWeather() {
		return true
	}
	s.mu.Lock()
	last := s.lastStateRead[spec.ThingName]
	s.mu.Unlock()
	if last.IsZero() {
		return true
	}
	staleAfter := time.Duration(rigble.BLEActiveMeasurementStaleMS) * time.Millisecond
	return now.Sub(last) >= staleAfter
}

func (s *runtimeState) recordConnectionHold(thingName string) uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.connectionHolds == nil {
		s.connectionHolds = map[string]uint64{}
	}
	s.nextConnectionHold++
	token := s.nextConnectionHold
	s.connectionHolds[thingName] = token
	return token
}

func (s *runtimeState) connectionHoldActive(thingName string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.connectionHolds[thingName]
	return ok
}

func (s *runtimeState) consumeConnectionHold(thingName string, token uint64) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.connectionHolds[thingName] != token {
		return false
	}
	delete(s.connectionHolds, thingName)
	return true
}

func (s *runtimeState) clearConnectionHold(thingName string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.connectionHolds, thingName)
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
