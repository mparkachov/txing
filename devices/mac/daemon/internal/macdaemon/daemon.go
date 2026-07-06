package macdaemon

import (
	"context"
	"fmt"
	"time"

	"github.com/mparkachov/txing/devices/mac/daemon/internal/macconfig"
	"github.com/mparkachov/txing/devices/mac/daemon/internal/rigadapter"
)

type Logf func(level string, message string)

// Run keeps the watch layer connected to the rig IPC socket for the
// daemon lifetime. The REDCON machine survives IPC reconnects so a rig
// restart does not reset the device posture. The action controller is
// driven by applied REDCON targets and stopped (with cloud offline
// publications) on daemon shutdown.
func Run(ctx context.Context, cfg macconfig.Config, action ActionController, logf Logf) error {
	machine, err := NewMachine(cfg.InitialRedcon)
	if err != nil {
		return err
	}
	if action != nil {
		action.SetTarget(machine.Redcon())
	}
	for {
		logf("info", fmt.Sprintf("dialing rig IPC socket=%s", cfg.IPCSocket))
		client, err := rigadapter.Dial(ctx, cfg.IPCSocket)
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		logf("info", fmt.Sprintf("rig IPC connected socket=%s", cfg.IPCSocket))
		err = runSession(ctx, cfg, machine, action, client, logf)
		_ = client.Close()
		if ctx.Err() != nil {
			return nil
		}
		logf("warning", fmt.Sprintf("rig IPC session ended, reconnecting error=%q", err))
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(time.Second):
		}
	}
}

func runSession(ctx context.Context, cfg macconfig.Config, machine *Machine, action ActionController, client *rigadapter.Client, logf Logf) error {
	commandTopic, err := rigadapter.BuildCapabilityCommandTopic(cfg.ThingID)
	if err != nil {
		return err
	}
	for _, filter := range []string{rigadapter.InventoryTopic, commandTopic} {
		if err := client.Subscribe(filter); err != nil {
			return err
		}
	}
	adapter := NewAdapter(cfg.ThingID, machine, client)
	adapter.Action = action

	messages := make(chan rigadapter.Message, 64)
	receiveErrors := make(chan error, 1)
	go func() {
		for {
			message, err := client.Receive()
			if err != nil {
				receiveErrors <- err
				return
			}
			messages <- message
		}
	}()

	stateTicker := time.NewTicker(cfg.StateInterval)
	defer stateTicker.Stop()
	heartbeatTicker := time.NewTicker(cfg.HeartbeatInterval)
	defer heartbeatTicker.Stop()

	if err := adapter.PublishHeartbeat(); err != nil {
		return err
	}
	for {
		select {
		case <-ctx.Done():
			if err := adapter.PublishOfflineState(); err != nil {
				logf("warning", fmt.Sprintf("offline state publish failed error=%q", err))
			}
			logf("info", "mac watch layer stopped")
			return nil
		case err := <-receiveErrors:
			return fmt.Errorf("IPC receive failed: %w", err)
		case <-stateTicker.C:
			if err := adapter.PublishState(); err != nil {
				return err
			}
		case <-heartbeatTicker.C:
			if err := adapter.PublishHeartbeat(); err != nil {
				return err
			}
		case message := <-messages:
			if err := handleMessage(adapter, cfg.ThingID, message, logf); err != nil {
				return err
			}
		}
	}
}

func handleMessage(adapter *Adapter, thingName string, message rigadapter.Message, logf Logf) error {
	if message.Topic == rigadapter.InventoryTopic {
		inventory, err := rigadapter.DecodeInventory(message.Payload)
		if err != nil {
			logf("warning", fmt.Sprintf("inventory decode failed error=%q", err))
			return nil
		}
		present, changed, err := adapter.ReconcileInventory(inventory)
		if changed {
			if present {
				logf("info", fmt.Sprintf("thing %s present in rig inventory redcon=%d", thingName, adapter.Machine.Redcon()))
			} else {
				logf("warning", fmt.Sprintf("thing %s missing from rig inventory; check registration and rigId assignment", thingName))
			}
		}
		return err
	}
	if commandThing, ok := rigadapter.ParseCapabilityCommandTopic(message.Topic); ok {
		command, err := rigadapter.DecodeCapabilityCommand(message.Payload)
		if err != nil {
			logf("warning", fmt.Sprintf("command decode failed topic=%s error=%q", message.Topic, err))
			return nil
		}
		if command.ThingName != commandThing {
			logf("warning", fmt.Sprintf("command thing mismatch topic=%s payloadThing=%s", message.Topic, command.ThingName))
			return nil
		}
		logf("info", fmt.Sprintf("redcon command received command=%s target=%d", command.CommandID, command.Target.Redcon))
		return adapter.HandleCommand(command)
	}
	return nil
}
