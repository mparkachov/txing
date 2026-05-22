//go:build linux

package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/godbus/dbus/v5"
	"tinygo.org/x/bluetooth"
)

const (
	bluezDestination       = "org.bluez"
	defaultBluezAdapter    = "/org/bluez/hci0"
	bluezConnectedProperty = "org.bluez.Device1.Connected"
)

func prepareBLEConnection(ctx context.Context, address bluetooth.Address) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	conn, err := dbus.SystemBus()
	if err != nil {
		return fmt.Errorf("bluez system bus: %w", err)
	}
	device := conn.Object(bluezDestination, bluezDevicePath(address))
	if connected, err := bluezDeviceConnected(device); err == nil && connected {
		return nil
	}

	call := device.Go("org.bluez.Device1.Connect", 0, make(chan *dbus.Call, 1))
	connectDone := call.Done
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case done := <-connectDone:
			connectDone = nil
			if done.Err != nil && !bluezConnectErrorCanStillComplete(done.Err) {
				return fmt.Errorf("bluetooth: failed to connect: %w", done.Err)
			}
			if connected, err := bluezDeviceConnected(device); err == nil && connected {
				return nil
			}
		case <-ticker.C:
			if connected, err := bluezDeviceConnected(device); err == nil && connected {
				return nil
			}
		case <-ctx.Done():
			_ = device.Call("org.bluez.Device1.Disconnect", 0).Err
			return fmt.Errorf("bluetooth connect timed out: %w", ctx.Err())
		}
	}
}

func bluezDevicePath(address bluetooth.Address) dbus.ObjectPath {
	return dbus.ObjectPath(defaultBluezAdapter + "/dev_" + strings.ReplaceAll(address.MAC.String(), ":", "_"))
}

func bluezDeviceConnected(device dbus.BusObject) (bool, error) {
	property, err := device.GetProperty(bluezConnectedProperty)
	if err != nil {
		return false, err
	}
	connected, ok := property.Value().(bool)
	if !ok {
		return false, fmt.Errorf("%s was not boolean", bluezConnectedProperty)
	}
	return connected, nil
}

func bluezConnectErrorCanStillComplete(err error) bool {
	lower := strings.ToLower(err.Error())
	return strings.Contains(lower, "inprogress") ||
		strings.Contains(lower, "in progress") ||
		strings.Contains(lower, "already")
}
