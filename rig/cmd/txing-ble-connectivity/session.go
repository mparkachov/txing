package main

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	rigble "github.com/mparkachov/txing/rig/internal/ble"
	"github.com/mparkachov/txing/rig/internal/protocol"
	"tinygo.org/x/bluetooth"
)

const (
	staleCheckInterval           = 500 * time.Millisecond
	notificationDrainInterval    = 100 * time.Millisecond
	connectedStateRefresh        = 30 * time.Second
	advertisementBroadcastPeriod = 1 * time.Second
	commandConnectRetryDelay     = 1 * time.Second
	commandWriteMaxAttempts      = 2
	commandConfirmMaxAttempts    = 8
	commandConfirmRetryDelay     = 250 * time.Millisecond
	commandStateNotificationHold = 2 * time.Second
	// Mirrors rig/internal/manager.StateTTLMS without coupling the BLE daemon to the Sparkplug manager.
	gattUnavailableRecoveryHold = 150 * time.Second
	visibleDeviceReconnectDelay = 30 * time.Second
)

type connectOutcome uint8

const (
	connectOutcomeConnected connectOutcome = iota
	connectOutcomeDeferredNoCapacity
)

type bleConnector interface {
	ConnectBLE(ctx context.Context, spec rigble.DeviceSpec, advertisement rigble.Advertisement, waitForCapacity bool) (bleConnection, connectOutcome, error)
}

type bleConnection interface {
	Address() string
	Connected() bool
	Disconnect()
	WriteRedcon(uint8) error
	ReadPowerState() (rigble.PowerState, error)
	ReadWeatherState() (rigble.WeatherState, error)
	ReadPowerMeasurement() (rigble.PowerMeasurement, error)
	ReadWeatherMeasurement() (rigble.WeatherMeasurement, error)
	DrainNotifications() []bleNotification
}

type bleNotification struct {
	uuid    bluetooth.UUID
	payload []byte
}

type redconConfirmationMismatchError struct {
	want uint8
	got  *uint8
}

func (e *redconConfirmationMismatchError) Error() string {
	if e.got == nil {
		return fmt.Sprintf("confirmed BLE state has no REDCON, want %d", e.want)
	}
	return fmt.Sprintf("confirmed BLE state REDCON %d, want %d", *e.got, e.want)
}

type timedMeasurement[T any] struct {
	value        T
	observedAtMS uint64
}

type deviceSession struct {
	runtime                *runtimeState
	spec                   rigble.DeviceSpec
	advertisements         chan rigble.Advertisement
	commands               chan protocol.CapabilityCommand
	done                   chan struct{}
	cancel                 context.CancelFunc
	lastAdvertisement      *rigble.Advertisement
	lastRedcon             *uint8
	lastPowerMeasurement   *timedMeasurement[rigble.PowerMeasurement]
	lastWeatherMeasurement *timedMeasurement[rigble.WeatherMeasurement]
	connected              bleConnection
	nextConnectAfter       time.Time
	connectFailures        uint32
	offlinePublished       bool
	guardedRedcon          *uint8
	guardedRedconUntil     time.Time
}

func newDeviceSession(runtime *runtimeState, spec rigble.DeviceSpec) *deviceSession {
	return &deviceSession{
		runtime:        runtime,
		spec:           spec,
		advertisements: make(chan rigble.Advertisement, 256),
		commands:       make(chan protocol.CapabilityCommand, 32),
		done:           make(chan struct{}),
	}
}

func (d *deviceSession) run(parent context.Context) {
	ctx, cancel := context.WithCancel(parent)
	d.cancel = cancel
	defer close(d.done)
	defer d.disconnect()

	if d.runtime.cfg.NoBLE {
		d.publishOffline(ctx)
		for {
			select {
			case <-ctx.Done():
				return
			case command := <-d.commands:
				message := "BLE is disabled for this daemon instance"
				d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
			}
		}
	}

	staleTicker := time.NewTicker(staleCheckInterval)
	defer staleTicker.Stop()
	notificationTicker := time.NewTicker(notificationDrainInterval)
	defer notificationTicker.Stop()
	connectedHeartbeat := time.NewTicker(connectedStateRefresh)
	defer connectedHeartbeat.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case advertisement := <-d.advertisements:
			d.handleAdvertisement(ctx, advertisement)
		case command := <-d.commands:
			d.handleCommand(ctx, command)
		case <-staleTicker.C:
			d.checkStale(ctx)
		case <-notificationTicker.C:
			d.drainNotifications(ctx)
		case <-connectedHeartbeat.C:
			if d.connected != nil && d.connected.Connected() {
				if err := d.refreshConnectedState(ctx, false, false); err != nil {
					d.runtime.infoPrint(ctx, fmt.Sprintf("BLE connected state heartbeat failed thing=%s error=%q", d.spec.ThingName, err))
					d.disconnect()
					d.publishGattUnavailableUnlessRecovering(ctx)
				}
			}
		}
	}
}

func (d *deviceSession) stop() {
	if d.cancel != nil {
		d.cancel()
	}
}

func (d *deviceSession) enqueueAdvertisement(ctx context.Context, advertisement rigble.Advertisement) bool {
	select {
	case d.advertisements <- advertisement:
		return true
	default:
		d.runtime.debugPrint(ctx, fmt.Sprintf("BLE advertisement dropped thing=%s reason=session-queue-full", d.spec.ThingName))
		return false
	}
}

func (d *deviceSession) enqueueCommand(ctx context.Context, command protocol.CapabilityCommand) bool {
	select {
	case d.commands <- command:
		return true
	default:
		d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command dropped thing=%s command=%s reason=session-queue-full", d.spec.ThingName, command.CommandID))
		return false
	}
}

func (d *deviceSession) handleAdvertisement(ctx context.Context, advertisement rigble.Advertisement) {
	if !d.observeMatchingAdvertisement(ctx, advertisement) {
		return
	}
	if d.connected != nil && d.connected.Connected() {
		d.runtime.debugPrint(ctx, fmt.Sprintf("BLE advertisement ignored because already connected thing=%s", d.spec.ThingName))
		return
	}
	d.publishAdvertisementSample(ctx, advertisement)
	now := time.Now()
	if now.Before(d.nextConnectAfter) {
		d.runtime.debugPrint(ctx, fmt.Sprintf("BLE advertisement ignored during reconnect backoff thing=%s retryAfterMs=%d", d.spec.ThingName, d.nextConnectAfter.UnixMilli()))
		return
	}
	outcome, err := d.connect(ctx, false)
	switch {
	case err == nil && outcome == connectOutcomeConnected:
		d.resetConnectBackoff()
	case err == nil && outcome == connectOutcomeDeferredNoCapacity:
		d.nextConnectAfter = time.Now().Add(maxDuration(d.runtime.cfg.ReconnectDelay, time.Duration(rigble.BLERetryMinDelayMS)*time.Millisecond))
	case err != nil:
		d.publishGattUnavailableUnlessRecovering(ctx)
		retryDelay := d.recordBackgroundConnectFailure(err)
		d.nextConnectAfter = time.Now().Add(retryDelay)
		d.logBackgroundConnectFailure(ctx, err, retryDelay)
	}
}

func (d *deviceSession) observeMatchingAdvertisement(ctx context.Context, advertisement rigble.Advertisement) bool {
	if !advertisement.MatchesThing(d.spec.ThingName) {
		return false
	}
	if !d.advertisementIsFresh(advertisement) {
		d.runtime.debugPrint(ctx, fmt.Sprintf("BLE advertisement ignored because stale thing=%s address=%s seq=%d observedAtMs=%d", d.spec.ThingName, advertisement.Address, advertisement.Seq, advertisement.ObservedAtMS))
		return false
	}
	d.lastAdvertisement = cloneAdvertisement(advertisement)
	d.offlinePublished = false
	d.runtime.debugPrint(ctx, fmt.Sprintf("BLE advertisement matched thing=%s address=%s rssi=%s seq=%d", d.spec.ThingName, advertisement.Address, debugRSSI(advertisement.RSSI), advertisement.Seq))
	return true
}

func (d *deviceSession) publishAdvertisementSample(ctx context.Context, advertisement rigble.Advertisement) {
	d.runtime.publishSample(ctx, rigble.AdvertisementSample(d.spec, advertisement, d.runtime.nextSeq()), true, rigble.AdvertisementPublishesCapabilityState(d.spec))
	d.runtime.debugPrint(ctx, fmt.Sprintf("BLE advertisement published thing=%s address=%s", d.spec.ThingName, advertisement.Address))
}

func (d *deviceSession) logBackgroundConnectFailure(ctx context.Context, err error, retryDelay time.Duration) {
	message := fmt.Sprintf("BLE connect from advertisement failed thing=%s failureCount=%d retryDelayMs=%d retryAfterMs=%d error=%q", d.spec.ThingName, d.connectFailures, retryDelay.Milliseconds(), d.nextConnectAfter.UnixMilli(), err)
	if d.backgroundConnectFailureLogLevel(err) == "debug" {
		d.runtime.debugPrint(ctx, message)
		return
	}
	d.runtime.logger.Print(ctx, "warning", message)
}

func (d *deviceSession) backgroundConnectFailureLogLevel(err error) string {
	if err == nil {
		return "debug"
	}
	message := err.Error()
	if strings.Contains(message, "no BLE advertisement has been observed") ||
		strings.Contains(message, "last BLE advertisement") ||
		d.hasFreshAdvertisement() {
		return "debug"
	}
	return "warning"
}

func (d *deviceSession) handleCommand(ctx context.Context, command protocol.CapabilityCommand) {
	d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command received thing=%s targetRedcon=%d command=%s", command.ThingName, command.Target.Redcon, command.CommandID))
	d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command received thing=%s targetRedcon=%d command=%s", command.ThingName, command.Target.Redcon, command.CommandID))
	if protocol.CommandDeadlineExpired(command, uint64(time.Now().UnixMilli())) {
		message := "command deadline expired"
		d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command failed thing=%s targetRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, command.CommandID, message))
		d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
		return
	}
	if reason := rigble.WeatherCommandRejectReason(command, d.spec); reason != nil {
		d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command rejected thing=%s targetRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, command.CommandID, *reason))
		d.runtime.publishCommandResult(ctx, command, protocol.CommandRejected, reason, &command.Target.Redcon)
		return
	}
	normalized, err := protocol.NormalizeBleTargetRedcon(command.Target.Redcon)
	if err != nil {
		message := err.Error()
		d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command rejected thing=%s targetRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, command.CommandID, message))
		d.runtime.publishCommandResult(ctx, command, protocol.CommandRejected, &message, &command.Target.Redcon)
		return
	}
	d.runtime.publishCommandResult(ctx, command, protocol.CommandAccepted, nil, &command.Target.Redcon)

	commandCtx, cancel := d.runtime.commandContext(ctx, command)
	defer cancel()
	for attempt := 1; attempt <= commandWriteMaxAttempts; attempt++ {
		if err := d.connectForCommand(commandCtx, command); err != nil {
			retryDelay := d.recordConnectFailure(err)
			d.nextConnectAfter = time.Now().Add(retryDelay)
			message := fmt.Sprintf("BLE connection failed before command write: %v", err)
			d.publishGattUnavailable(ctx)
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s error=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, err))
			d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, message))
			d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
			return
		}
		if protocol.CommandDeadlineExpired(command, uint64(time.Now().UnixMilli())) {
			message := "command deadline expired"
			d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, message))
			d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
			return
		}
		if d.connected == nil {
			message := "BLE connection is unavailable"
			d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, message))
			d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
			return
		}
		if err := d.connected.WriteRedcon(normalized); err != nil {
			d.disconnect()
			if attempt < commandWriteMaxAttempts && d.commandCanRetry(commandCtx) {
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command write retry thing=%s targetRedcon=%d normalizedRedcon=%d command=%s attempt=%d error=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, attempt, err))
				d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command write retry thing=%s targetRedcon=%d normalizedRedcon=%d command=%s attempt=%d error=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, attempt, err))
				continue
			}
			retryDelay := d.recordConnectFailure(err)
			d.nextConnectAfter = time.Now().Add(retryDelay)
			message := fmt.Sprintf("BLE command write failed: %v", err)
			d.publishGattUnavailable(ctx)
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command write failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s attempt=%d error=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, attempt, err))
			d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command write failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s attempt=%d error=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, attempt, err))
			d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
			return
		}
		d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command written thing=%s targetRedcon=%d normalizedRedcon=%d command=%s attempt=%d", command.ThingName, command.Target.Redcon, normalized, command.CommandID, attempt))
		break
	}
	if err := d.confirmCommandState(commandCtx, normalized); err != nil {
		message := fmt.Sprintf("BLE state confirmation failed after command write: %v", err)
		var mismatch *redconConfirmationMismatchError
		if !errors.As(err, &mismatch) {
			d.disconnect()
			d.publishGattUnavailable(ctx)
		}
		d.runtime.infoPrint(ctx, fmt.Sprintf("BLE REDCON command confirmation failed thing=%s targetRedcon=%d normalizedRedcon=%d command=%s reason=%q", command.ThingName, command.Target.Redcon, normalized, command.CommandID, message))
		d.runtime.publishCommandResult(ctx, command, protocol.CommandFailed, &message, &command.Target.Redcon)
		return
	}
	d.resetConnectBackoff()
	d.guardConfirmedRedcon(normalized)
	d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command succeeded thing=%s targetRedcon=%d normalizedRedcon=%d command=%s", command.ThingName, command.Target.Redcon, normalized, command.CommandID))
	d.runtime.publishCommandResult(ctx, command, protocol.CommandSucceeded, nil, &command.Target.Redcon)
}

func (d *deviceSession) confirmCommandState(ctx context.Context, targetRedcon uint8) error {
	var lastRedcon *uint8
	var lastErr error
	for attempt := 1; attempt <= commandConfirmMaxAttempts; attempt++ {
		if err := d.refreshConnectedState(ctx, true, true); err != nil {
			lastErr = err
			if !d.commandConfirmationReadCanRetry(ctx, attempt, err) {
				return err
			}
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command state confirmation retry thing=%s targetRedcon=%d attempt=%d retryDelayMs=%d error=%q", d.spec.ThingName, targetRedcon, attempt, commandConfirmRetryDelay.Milliseconds(), err))
			if err := d.waitForCommandRetryDelay(ctx, commandConfirmRetryDelay); err != nil {
				return err
			}
			continue
		}
		lastErr = nil
		if d.lastRedcon != nil {
			value := *d.lastRedcon
			lastRedcon = &value
			if value == targetRedcon {
				return nil
			}
		} else {
			lastRedcon = nil
		}
		if attempt == commandConfirmMaxAttempts {
			break
		}
		if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) <= commandConfirmRetryDelay {
			break
		}
		if err := d.waitForCommandRetryDelay(ctx, commandConfirmRetryDelay); err != nil {
			return err
		}
	}
	if lastErr != nil {
		return lastErr
	}
	return &redconConfirmationMismatchError{want: targetRedcon, got: lastRedcon}
}

func (d *deviceSession) commandConfirmationReadCanRetry(ctx context.Context, attempt int, err error) bool {
	if err == nil || attempt >= commandConfirmMaxAttempts || ctx.Err() != nil {
		return false
	}
	if !rigble.BLECommandConnectErrorIsRetryable(err.Error()) {
		return false
	}
	if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) <= commandConfirmRetryDelay {
		return false
	}
	return true
}

func (d *deviceSession) connectForCommand(ctx context.Context, command protocol.CapabilityCommand) error {
	attempt := uint32(0)
	for {
		attempt++
		outcome, err := d.connect(ctx, true)
		if err == nil && outcome == connectOutcomeConnected {
			return nil
		}
		if err == nil && outcome == connectOutcomeDeferredNoCapacity {
			return fmt.Errorf("BLE connection capacity is unavailable before command write")
		}
		if ctx.Err() != nil {
			return fmt.Errorf("bluetooth command stopped after error: %w", err)
		}
		if !rigble.BLECommandConnectErrorIsRetryable(err.Error()) || !d.commandCanRetry(ctx) {
			return err
		}
		d.runtime.debugPrint(ctx, fmt.Sprintf("BLE command connect retry thing=%s command=%s attempt=%d retryDelayMs=%d error=%q", d.spec.ThingName, command.CommandID, attempt, commandConnectRetryDelay.Milliseconds(), err))
		if d.hasFreshAdvertisement() {
			if err := d.waitForCommandRetryDelay(ctx, commandConnectRetryDelay); err != nil {
				return err
			}
		} else if err := d.waitForFreshCommandAdvertisement(ctx, command, commandConnectRetryDelay); err != nil {
			return err
		}
	}
}

func (d *deviceSession) commandCanRetry(ctx context.Context) bool {
	deadline, ok := ctx.Deadline()
	if !ok {
		return true
	}
	return time.Now().Add(commandConnectRetryDelay).Before(deadline)
}

func (d *deviceSession) waitForCommandRetryDelay(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
			return nil
		case advertisement := <-d.advertisements:
			if d.observeMatchingAdvertisement(ctx, advertisement) {
				d.publishAdvertisementSample(ctx, advertisement)
				return nil
			}
		}
	}
}

func (d *deviceSession) waitForFreshCommandAdvertisement(ctx context.Context, command protocol.CapabilityCommand, step time.Duration) error {
	for !d.hasFreshAdvertisement() {
		wait := step
		if deadline, ok := ctx.Deadline(); ok {
			remaining := time.Until(deadline)
			if remaining <= 0 {
				return fmt.Errorf("no fresh BLE advertisement for %s before command deadline commandId=%s", d.spec.ThingName, command.CommandID)
			}
			if remaining < wait {
				wait = remaining
			}
		}
		if err := d.waitForCommandAdvertisement(ctx, wait); err != nil {
			return err
		}
	}
	return nil
}

func (d *deviceSession) waitForCommandAdvertisement(ctx context.Context, wait time.Duration) error {
	timer := time.NewTimer(wait)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	case advertisement := <-d.advertisements:
		if d.observeMatchingAdvertisement(ctx, advertisement) {
			d.publishAdvertisementSample(ctx, advertisement)
		}
		return nil
	}
}

func (d *deviceSession) connect(ctx context.Context, waitForCapacity bool) (connectOutcome, error) {
	if d.connected != nil && d.connected.Connected() {
		if waitForCapacity {
			if err := d.refreshConnectedState(ctx, false, false); err != nil {
				d.disconnect()
				return connectOutcomeConnected, err
			}
		}
		return connectOutcomeConnected, nil
	}
	d.disconnect()
	if d.lastAdvertisement == nil {
		return connectOutcomeConnected, fmt.Errorf("no BLE advertisement has been observed for %s", d.spec.ThingName)
	}
	if !d.advertisementIsFresh(*d.lastAdvertisement) {
		return connectOutcomeConnected, fmt.Errorf("last BLE advertisement for %s is stale", d.spec.ThingName)
	}
	connectCtx := ctx
	cancel := func() {}
	if !waitForCapacity {
		connectCtx, cancel = d.runtime.backgroundConnectContext(ctx)
	}
	defer cancel()
	connection, outcome, err := d.runtime.connector.ConnectBLE(connectCtx, d.spec, *d.lastAdvertisement, waitForCapacity)
	if err != nil || outcome != connectOutcomeConnected {
		return outcome, err
	}
	d.connected = connection
	if err := d.seedConnectedState(ctx); err != nil {
		d.disconnect()
		return connectOutcomeConnected, err
	}
	return connectOutcomeConnected, nil
}

func (d *deviceSession) seedConnectedState(ctx context.Context) error {
	return d.refreshConnectedState(ctx, true, true)
}

func (d *deviceSession) refreshConnectedState(ctx context.Context, includeMeasurements bool, includeShadow bool) error {
	if d.connected == nil {
		return nil
	}
	if !d.connected.Connected() {
		d.disconnect()
		d.checkStale(ctx)
		return fmt.Errorf("BLE device disconnected before state read")
	}
	now := uint64(time.Now().UnixMilli())
	switch d.spec.Kind {
	case rigble.DeviceKindWeather:
		state, err := d.connected.ReadWeatherState()
		if err != nil {
			return fmt.Errorf("read weather state: %w", err)
		}
		d.setLastRedcon(state.Redcon)
		if includeMeasurements {
			if measurement, err := d.connected.ReadPowerMeasurement(); err == nil {
				d.lastPowerMeasurement = &timedMeasurement[rigble.PowerMeasurement]{value: measurement, observedAtMS: now}
			} else {
				d.lastPowerMeasurement = nil
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE weather power measurement read failed thing=%s error=%q", d.spec.ThingName, err))
			}
			if measurement, err := d.connected.ReadWeatherMeasurement(); err == nil {
				d.lastWeatherMeasurement = &timedMeasurement[rigble.WeatherMeasurement]{value: measurement, observedAtMS: now}
			} else {
				d.lastWeatherMeasurement = nil
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE weather measurement read failed thing=%s error=%q", d.spec.ThingName, err))
			}
		}
	default:
		state, err := d.connected.ReadPowerState()
		if err != nil {
			return fmt.Errorf("read power state: %w", err)
		}
		d.setLastRedcon(state.Redcon)
		if includeMeasurements {
			if measurement, err := d.connected.ReadPowerMeasurement(); err == nil {
				d.lastPowerMeasurement = &timedMeasurement[rigble.PowerMeasurement]{value: measurement, observedAtMS: now}
			} else {
				d.lastPowerMeasurement = nil
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE power measurement read failed thing=%s error=%q", d.spec.ThingName, err))
			}
		}
	}
	d.runtime.recordStateRead(d.spec.ThingName, time.UnixMilli(int64(now)))
	if includeShadow {
		d.publishAggregateSample(ctx, now)
	} else {
		d.publishAggregateStateHeartbeat(ctx, now)
	}
	return nil
}

func (d *deviceSession) drainNotifications(ctx context.Context) {
	if d.connected == nil {
		return
	}
	if !d.connected.Connected() {
		d.disconnect()
		d.publishGattUnavailableUnlessRecovering(ctx)
		return
	}
	for _, notification := range d.connected.DrainNotifications() {
		d.handleNotification(ctx, notification)
	}
}

func (d *deviceSession) handleNotification(ctx context.Context, notification bleNotification) {
	nowTime := time.Now()
	now := uint64(nowTime.UnixMilli())
	switch notification.uuid.String() {
	case d.runtime.stateUUID.String():
		if d.spec.Kind == rigble.DeviceKindWeather {
			state, err := rigble.ParseWeatherState(notification.payload)
			if err != nil {
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE weather state notification ignored thing=%s error=%q", d.spec.ThingName, err))
				return
			}
			if d.guardsAgainstStateNotification(state.Redcon, nowTime) {
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE weather state notification ignored during command guard thing=%s notificationRedcon=%d guardedRedcon=%d", d.spec.ThingName, state.Redcon, *d.guardedRedcon))
				return
			}
			d.setLastRedcon(state.Redcon)
		} else {
			state, err := rigble.ParsePowerState(notification.payload)
			if err != nil {
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE power state notification ignored thing=%s error=%q", d.spec.ThingName, err))
				return
			}
			if d.guardsAgainstStateNotification(state.Redcon, nowTime) {
				d.runtime.debugPrint(ctx, fmt.Sprintf("BLE power state notification ignored during command guard thing=%s notificationRedcon=%d guardedRedcon=%d", d.spec.ThingName, state.Redcon, *d.guardedRedcon))
				return
			}
			d.setLastRedcon(state.Redcon)
		}
		d.runtime.recordStateRead(d.spec.ThingName, time.UnixMilli(int64(now)))
		d.publishAggregateSample(ctx, now)
	case d.runtime.powerUUID.String():
		measurement, err := rigble.ParsePowerMeasurement(notification.payload)
		if err != nil {
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE power measurement notification ignored thing=%s error=%q", d.spec.ThingName, err))
			return
		}
		d.lastPowerMeasurement = &timedMeasurement[rigble.PowerMeasurement]{value: measurement, observedAtMS: now}
		d.publishAggregateSample(ctx, now)
	case d.runtime.weatherUUID.String():
		if !d.spec.Kind.SupportsWeather() {
			return
		}
		measurement, err := rigble.ParseWeatherMeasurement(notification.payload)
		if err != nil {
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE weather measurement notification ignored thing=%s error=%q", d.spec.ThingName, err))
			return
		}
		d.lastWeatherMeasurement = &timedMeasurement[rigble.WeatherMeasurement]{value: measurement, observedAtMS: now}
		d.publishAggregateSample(ctx, now)
	}
}

func (d *deviceSession) checkStale(ctx context.Context) {
	nowTime := time.Now()
	now := uint64(nowTime.UnixMilli())
	if d.connected != nil {
		if !d.connected.Connected() {
			d.disconnect()
			d.publishGattUnavailableUnlessRecovering(ctx)
		} else if d.clearStaleMeasurements(now) {
			d.publishAggregateSample(ctx, now)
		}
		return
	}
	if d.lastAdvertisement != nil && d.advertisementIsFresh(*d.lastAdvertisement) {
		return
	}
	if d.refreshFromFreshCachedAdvertisement(ctx, nowTime) {
		return
	}
	if d.lastAdvertisement != nil && d.runtime.scanFreshnessHeldFor(d.spec.ThingName, *d.lastAdvertisement, nowTime) {
		return
	}
	if !d.offlinePublished {
		d.publishOffline(ctx)
	}
}

func (d *deviceSession) publishOffline(ctx context.Context) {
	d.lastRedcon = nil
	d.lastPowerMeasurement = nil
	d.lastWeatherMeasurement = nil
	d.runtime.publishSample(ctx, rigble.OfflineSample(d.spec, d.runtime.nextSeq(), uint64(time.Now().UnixMilli())), false, true)
	d.resetConnectBackoff()
	d.offlinePublished = true
}

func (d *deviceSession) publishGattUnavailable(ctx context.Context) {
	d.lastRedcon = nil
	d.lastPowerMeasurement = nil
	d.lastWeatherMeasurement = nil
	d.runtime.publishSample(ctx, rigble.OfflineSample(d.spec, d.runtime.nextSeq(), uint64(time.Now().UnixMilli())), false, true)
	d.offlinePublished = true
}

func (d *deviceSession) publishGattUnavailableUnlessRecovering(ctx context.Context) {
	now := time.Now()
	if d.gattUnavailableCanDefer(now) {
		if d.hasFreshAdvertisementAt(now) {
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE GATT unavailable publication deferred by fresh advertisement thing=%s", d.spec.ThingName))
			return
		}
		if d.refreshFromFreshCachedAdvertisement(ctx, now) {
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE GATT unavailable publication deferred by cached advertisement thing=%s", d.spec.ThingName))
			return
		}
		if d.lastAdvertisement != nil && d.runtime.scanFreshnessHeldFor(d.spec.ThingName, *d.lastAdvertisement, now) {
			d.runtime.debugPrint(ctx, fmt.Sprintf("BLE GATT unavailable publication deferred by scan freshness hold thing=%s", d.spec.ThingName))
			return
		}
	}
	d.publishGattUnavailable(ctx)
}

func (d *deviceSession) refreshFromFreshCachedAdvertisement(ctx context.Context, now time.Time) bool {
	observedAfterMS := uint64(0)
	if d.lastAdvertisement != nil {
		observedAfterMS = d.lastAdvertisement.ObservedAtMS
	}
	advertisement, ok := d.runtime.cachedAdvertisementAfter(d.spec.ThingName, observedAfterMS, now)
	if !ok {
		return false
	}
	d.lastAdvertisement = advertisement
	d.offlinePublished = false
	d.runtime.debugPrint(ctx, fmt.Sprintf("BLE stale check held by fresh cached advertisement thing=%s address=%s seq=%d", d.spec.ThingName, advertisement.Address, advertisement.Seq))
	return true
}

func (d *deviceSession) publishAggregateSample(ctx context.Context, now uint64) {
	d.runtime.publishSample(ctx, d.aggregateSample(now), true, true)
}

func (d *deviceSession) publishAggregateStateHeartbeat(ctx context.Context, now uint64) {
	d.runtime.publishSample(ctx, d.aggregateSample(now), false, true)
}

func (d *deviceSession) aggregateSample(now uint64) rigble.CapabilitySample {
	address := d.connectedAddress()
	redcon := rigble.RedconIdle
	if d.lastRedcon != nil {
		redcon = *d.lastRedcon
	}
	var powerMeasurement *rigble.PowerMeasurement
	if d.lastPowerMeasurement != nil && now-d.lastPowerMeasurement.observedAtMS <= d.measurementStaleMS() {
		value := d.lastPowerMeasurement.value
		powerMeasurement = &value
	}
	var weatherMeasurement *rigble.WeatherMeasurement
	if d.lastWeatherMeasurement != nil && now-d.lastWeatherMeasurement.observedAtMS <= d.measurementStaleMS() {
		value := d.lastWeatherMeasurement.value
		weatherMeasurement = &value
	}
	if d.spec.Kind == rigble.DeviceKindWeather {
		return rigble.WeatherStateSample(d.spec, redcon, powerMeasurement, weatherMeasurement, address, d.runtime.nextSeq(), now)
	}
	return rigble.PowerStateSample(d.spec, redcon, powerMeasurement, address, d.runtime.nextSeq(), now)
}

func (d *deviceSession) connectedAddress() *string {
	if d.connected != nil {
		address := d.connected.Address()
		return &address
	}
	if d.lastAdvertisement != nil {
		address := d.lastAdvertisement.Address
		return &address
	}
	return nil
}

func (d *deviceSession) clearStaleMeasurements(now uint64) bool {
	changed := false
	if d.lastPowerMeasurement != nil && now-d.lastPowerMeasurement.observedAtMS > d.measurementStaleMS() {
		d.lastPowerMeasurement = nil
		changed = true
	}
	if d.lastWeatherMeasurement != nil && now-d.lastWeatherMeasurement.observedAtMS > d.measurementStaleMS() {
		d.lastWeatherMeasurement = nil
		changed = true
	}
	return changed
}

func (d *deviceSession) measurementStaleMS() uint64 {
	if d.lastRedcon != nil && *d.lastRedcon < rigble.RedconIdle {
		return rigble.BLEActiveMeasurementStaleMS
	}
	return rigble.BLEIdleMeasurementStaleMS
}

func (d *deviceSession) advertisementIsFresh(advertisement rigble.Advertisement) bool {
	return d.runtime.advertisementIsFreshAt(advertisement, time.Now())
}

func (d *deviceSession) hasFreshAdvertisement() bool {
	return d.hasFreshAdvertisementAt(time.Now())
}

func (d *deviceSession) hasFreshAdvertisementAt(now time.Time) bool {
	return d.lastAdvertisement != nil && d.runtime.advertisementIsFreshAt(*d.lastAdvertisement, now)
}

func (d *deviceSession) setLastRedcon(redcon uint8) {
	value := redcon
	d.lastRedcon = &value
}

func (d *deviceSession) guardConfirmedRedcon(redcon uint8) {
	value := redcon
	d.guardedRedcon = &value
	d.guardedRedconUntil = time.Now().Add(commandStateNotificationHold)
}

func (d *deviceSession) guardsAgainstStateNotification(redcon uint8, now time.Time) bool {
	if d.guardedRedcon == nil {
		return false
	}
	if !now.Before(d.guardedRedconUntil) {
		d.guardedRedcon = nil
		d.guardedRedconUntil = time.Time{}
		return false
	}
	return redcon != *d.guardedRedcon
}

func (d *deviceSession) gattUnavailableCanDefer(now time.Time) bool {
	if d.lastRedcon == nil {
		return false
	}
	d.runtime.mu.Lock()
	observedAt, ok := d.runtime.lastStateRead[d.spec.ThingName]
	d.runtime.mu.Unlock()
	return ok && observedAt.Add(gattUnavailableRecoveryHold).After(now)
}

func (d *deviceSession) recordConnectFailure(err error) time.Duration {
	return d.recordConnectFailureBounded(err, time.Duration(rigble.BLERetryMaxDelayMS)*time.Millisecond)
}

func (d *deviceSession) recordBackgroundConnectFailure(err error) time.Duration {
	maxDelay := time.Duration(rigble.BLERetryMaxDelayMS) * time.Millisecond
	if d.hasFreshAdvertisement() && backgroundTimeoutCanUseVisibleRetry(err) {
		if visibleDeviceReconnectDelay < maxDelay {
			maxDelay = visibleDeviceReconnectDelay
		}
	}
	return d.recordConnectFailureBounded(err, maxDelay)
}

func (d *deviceSession) recordConnectFailureBounded(err error, maxDelay time.Duration) time.Duration {
	base := d.runtime.cfg.ReconnectDelay
	message := err.Error()
	if rigble.BLEErrorIndicatesHostResourceExhaustion(message) {
		base = maxDuration(base, time.Duration(rigble.BLUEResourceExhaustedReconnectDelayMS)*time.Millisecond)
	} else if rigble.BLEErrorIndicatesInProgress(message) {
		base = maxDuration(base, time.Duration(rigble.BluezInProgressReconnectDelayMS)*time.Millisecond)
	} else {
		base = maxDuration(base, time.Duration(rigble.BLERetryMinDelayMS)*time.Millisecond)
	}
	delayMS := rigble.BoundedRetryDelayMS(uint64(base/time.Millisecond), d.connectFailures+1, rigble.BLERetryMaxDelayMS) +
		rigble.StableJitterMS(d.spec.ThingName, 1000)
	maxDelayMS := uint64(maxDelay / time.Millisecond)
	if delayMS > maxDelayMS {
		delayMS = maxDelayMS
	}
	d.connectFailures++
	return time.Duration(delayMS) * time.Millisecond
}

func backgroundTimeoutCanUseVisibleRetry(err error) bool {
	if err == nil {
		return false
	}
	message := err.Error()
	if rigble.BLEErrorIndicatesHostResourceExhaustion(message) || rigble.BLEErrorIndicatesInProgress(message) {
		return false
	}
	return strings.Contains(strings.ToLower(message), "timeout")
}

func (d *deviceSession) resetConnectBackoff() {
	d.connectFailures = 0
	d.nextConnectAfter = time.Time{}
}

func (d *deviceSession) disconnect() {
	if d.connected != nil {
		d.connected.Disconnect()
		d.connected = nil
	}
}

func (s *runtimeState) ConnectBLE(ctx context.Context, spec rigble.DeviceSpec, advertisement rigble.Advertisement, waitForCapacity bool) (bleConnection, connectOutcome, error) {
	releaseDevice, err := s.acquireDeviceConnect(ctx, spec.ThingName)
	if err != nil {
		return nil, connectOutcomeConnected, err
	}
	defer releaseDevice()

	releaseSlot, outcome, err := s.acquireConnectSlotForSession(ctx, waitForCapacity)
	if err != nil || outcome != connectOutcomeConnected {
		return nil, outcome, err
	}

	address, err := s.addressForAdvertisement(spec, advertisement)
	if err != nil {
		releaseSlot()
		return nil, connectOutcomeConnected, err
	}
	s.pauseScanForConnect()
	if err := prepareBLEConnection(ctx, address); err != nil {
		releaseSlot()
		return nil, connectOutcomeConnected, err
	}
	device, err := bluetooth.DefaultAdapter.Connect(address, bluetooth.ConnectionParams{
		ConnectionTimeout: bluetooth.NewDuration(s.cfg.ConnectTimeout),
	})
	if err != nil {
		releaseSlot()
		return nil, connectOutcomeConnected, err
	}
	connection, err := s.setupConnectedDevice(spec, device, address.String(), releaseSlot)
	if err != nil {
		_ = device.Disconnect()
		releaseSlot()
		return nil, connectOutcomeConnected, err
	}
	return connection, connectOutcomeConnected, nil
}

func (s *runtimeState) acquireConnectSlotForSession(ctx context.Context, waitForCapacity bool) (func(), connectOutcome, error) {
	if s.connectSlots == nil {
		return func() {}, connectOutcomeConnected, nil
	}
	if waitForCapacity {
		release, err := s.acquireConnectSlot(ctx)
		return release, connectOutcomeConnected, err
	}
	select {
	case s.connectSlots <- struct{}{}:
		return func() { <-s.connectSlots }, connectOutcomeConnected, nil
	default:
		return nil, connectOutcomeDeferredNoCapacity, nil
	}
}

func (s *runtimeState) addressForAdvertisement(spec rigble.DeviceSpec, advertisement rigble.Advertisement) (bluetooth.Address, error) {
	s.mu.Lock()
	address, ok := s.addresses[spec.ThingName]
	s.mu.Unlock()
	if ok {
		return address, nil
	}
	var fallback bluetooth.Address
	fallback.Set(advertisement.Address)
	if fallback.String() == "" {
		return bluetooth.Address{}, fmt.Errorf("parse BLE advertisement address %s", advertisement.Address)
	}
	return fallback, nil
}

func (s *runtimeState) setupConnectedDevice(spec rigble.DeviceSpec, device bluetooth.Device, address string, releaseSlot func()) (*realBLEConnection, error) {
	services, err := device.DiscoverServices([]bluetooth.UUID{s.txingUUID})
	if err != nil {
		return nil, err
	}
	if len(services) == 0 {
		return nil, fmt.Errorf("txing BLE service not found")
	}
	characteristics, err := services[0].DiscoverCharacteristics(s.discoveryUUIDs(spec))
	if err != nil {
		return nil, err
	}
	chars := map[string]bluetooth.DeviceCharacteristic{}
	for _, characteristic := range characteristics {
		chars[characteristic.UUID().String()] = characteristic
	}
	commandChar, ok := chars[s.commandUUID.String()]
	if !ok {
		return nil, fmt.Errorf("command characteristic not found")
	}
	stateChar, ok := chars[s.stateUUID.String()]
	if !ok {
		return nil, fmt.Errorf("state characteristic not found")
	}
	powerChar, ok := chars[s.powerUUID.String()]
	if !ok {
		return nil, fmt.Errorf("power measurement characteristic not found")
	}
	var weatherChar *bluetooth.DeviceCharacteristic
	if spec.Kind.SupportsWeather() {
		characteristic, ok := chars[s.weatherUUID.String()]
		if !ok {
			return nil, fmt.Errorf("weather measurement characteristic not found")
		}
		weatherChar = &characteristic
	}
	connection := &realBLEConnection{
		device:        device,
		commandChar:   commandChar,
		stateChar:     &stateChar,
		powerChar:     &powerChar,
		weatherChar:   weatherChar,
		address:       address,
		notifications: make(chan bleNotification, 32),
		releaseSlot:   releaseSlot,
	}
	if err := connection.enableNotifications(); err != nil {
		connection.disableNotifications()
		return nil, err
	}
	return connection, nil
}

type realBLEConnection struct {
	device        bluetooth.Device
	commandChar   bluetooth.DeviceCharacteristic
	stateChar     *bluetooth.DeviceCharacteristic
	powerChar     *bluetooth.DeviceCharacteristic
	weatherChar   *bluetooth.DeviceCharacteristic
	address       string
	notifications chan bleNotification
	releaseSlot   func()
	closeOnce     sync.Once
}

func (c *realBLEConnection) Address() string {
	return c.address
}

func (c *realBLEConnection) Connected() bool {
	connected, err := c.device.Connected()
	return err == nil && connected
}

func (c *realBLEConnection) Disconnect() {
	c.closeOnce.Do(func() {
		c.disableNotifications()
		_ = c.device.Disconnect()
		if c.releaseSlot != nil {
			c.releaseSlot()
		}
	})
}

func (c *realBLEConnection) disableNotifications() {
	if c.stateChar != nil {
		_ = c.stateChar.EnableNotifications(nil)
	}
	if c.powerChar != nil {
		_ = c.powerChar.EnableNotifications(nil)
	}
	if c.weatherChar != nil {
		_ = c.weatherChar.EnableNotifications(nil)
	}
}

func (c *realBLEConnection) WriteRedcon(redcon uint8) error {
	payload, err := rigble.EncodeRedconCommand(redcon)
	if err != nil {
		return err
	}
	_, err = c.commandChar.WriteWithoutResponse(payload)
	return err
}

func (c *realBLEConnection) ReadPowerState() (rigble.PowerState, error) {
	payload, err := readCharacteristic(*c.stateChar, 16)
	if err != nil {
		return rigble.PowerState{}, err
	}
	return rigble.ParsePowerState(payload)
}

func (c *realBLEConnection) ReadWeatherState() (rigble.WeatherState, error) {
	payload, err := readCharacteristic(*c.stateChar, 16)
	if err != nil {
		return rigble.WeatherState{}, err
	}
	return rigble.ParseWeatherState(payload)
}

func (c *realBLEConnection) ReadPowerMeasurement() (rigble.PowerMeasurement, error) {
	payload, err := readCharacteristic(*c.powerChar, 16)
	if err != nil {
		return rigble.PowerMeasurement{}, err
	}
	return rigble.ParsePowerMeasurement(payload)
}

func (c *realBLEConnection) ReadWeatherMeasurement() (rigble.WeatherMeasurement, error) {
	if c.weatherChar == nil {
		return rigble.WeatherMeasurement{}, fmt.Errorf("weather measurement characteristic not found")
	}
	payload, err := readCharacteristic(*c.weatherChar, 32)
	if err != nil {
		return rigble.WeatherMeasurement{}, err
	}
	return rigble.ParseWeatherMeasurement(payload)
}

func (c *realBLEConnection) DrainNotifications() []bleNotification {
	notifications := []bleNotification{}
	for {
		select {
		case notification := <-c.notifications:
			notifications = append(notifications, notification)
		default:
			return notifications
		}
	}
}

func (c *realBLEConnection) enableNotifications() error {
	if err := c.enableCharacteristicNotifications(c.stateChar); err != nil {
		return fmt.Errorf("subscribe BLE state notifications: %w", err)
	}
	if err := c.enableCharacteristicNotifications(c.powerChar); err != nil {
		return fmt.Errorf("subscribe BLE power measurement notifications: %w", err)
	}
	if c.weatherChar != nil {
		if err := c.enableCharacteristicNotifications(c.weatherChar); err != nil {
			return fmt.Errorf("subscribe BLE weather measurement notifications: %w", err)
		}
	}
	return nil
}

func (c *realBLEConnection) enableCharacteristicNotifications(characteristic *bluetooth.DeviceCharacteristic) error {
	uuid := characteristic.UUID()
	return characteristic.EnableNotifications(func(payload []byte) {
		copied := append([]byte(nil), payload...)
		select {
		case c.notifications <- bleNotification{uuid: uuid, payload: copied}:
		default:
		}
	})
}

func cloneAdvertisement(advertisement rigble.Advertisement) *rigble.Advertisement {
	clone := advertisement
	if advertisement.IdentityName != nil {
		name := *advertisement.IdentityName
		clone.IdentityName = &name
	}
	if advertisement.RSSI != nil {
		rssi := *advertisement.RSSI
		clone.RSSI = &rssi
	}
	clone.Services = append([]string(nil), advertisement.Services...)
	return &clone
}

func debugRSSI(rssi *int16) string {
	if rssi == nil {
		return "nil"
	}
	return fmt.Sprintf("%d", *rssi)
}

func maxDuration(a time.Duration, b time.Duration) time.Duration {
	if a > b {
		return a
	}
	return b
}
