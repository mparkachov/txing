package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/mparkachov/txing/rig/internal/awsx"
	"github.com/mparkachov/txing/rig/internal/ipc"
	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
	rigthread "github.com/mparkachov/txing/rig/internal/thread"
	"github.com/mparkachov/txing/rig/internal/version"
)

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
		fmt.Printf("txing-thread-connectivity version=%s rig=%s town=%s ipc=%s domain=%s\n", version.Version, cfg.RigID, cfg.TownID, cfg.IPCSocket, cfg.ThreadServiceDomain)
		return
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, cfg); err != nil {
		fmt.Fprintf(os.Stderr, "thread connectivity stopped with error: %v\n", err)
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
		"txing-thread-connectivity",
		cfg.CloudWatchRetentionDays,
	)
	logger.Ensure(ctx)
	logger.Print(ctx, "info", fmt.Sprintf("version=%s rig=%s domain=%s", version.Version, cfg.RigID, cfg.ThreadServiceDomain))

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

	runtime := rigthread.NewRuntime(
		rigthread.Discoverer{
			Resolver: rigthread.NewSystemDNSResolver(cfg.ThreadCoAPTimeout),
			Domain:   cfg.ThreadServiceDomain,
		},
		rigthread.CoAPClient{Timeout: cfg.ThreadCoAPTimeout, Attempts: 2},
		client,
	)

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

	discoveryTicker := time.NewTicker(cfg.ThreadDiscoveryInterval)
	defer discoveryTicker.Stop()
	pollTicker := time.NewTicker(cfg.ThreadPollInterval)
	defer pollTicker.Stop()
	heartbeatTicker := time.NewTicker(cfg.ThreadHeartbeatInterval)
	defer heartbeatTicker.Stop()
	var heartbeatSeq uint64

	publishHeartbeat(ctx, client, nil, heartbeatSeq)
	heartbeatSeq++
	for {
		select {
		case <-ctx.Done():
			logger.Print(context.Background(), "info", "thread connectivity stopped")
			return nil
		case err := <-ipcErrors:
			return fmt.Errorf("IPC receive failed: %w", err)
		case <-discoveryTicker.C:
			if err := runtime.DiscoverAndPoll(ctx); err != nil {
				logger.Print(ctx, "warning", fmt.Sprintf("Thread discovery failed error=%q", err))
			}
		case <-pollTicker.C:
			if err := runtime.DiscoverAndPoll(ctx); err != nil {
				logger.Print(ctx, "warning", fmt.Sprintf("Thread poll failed error=%q", err))
			}
		case <-heartbeatTicker.C:
			publishHeartbeat(ctx, client, nil, heartbeatSeq)
			heartbeatSeq++
		case message := <-messages:
			handleIPCMessage(ctx, logger, runtime, message)
		}
	}
}

func handleIPCMessage(ctx context.Context, logger *awsx.CloudWatchLogger, runtime *rigthread.Runtime, message ipc.Message) {
	if message.Topic == protocol.InventoryTopic {
		inventory, err := protocol.DecodeInventory(message.Payload)
		if err != nil {
			logger.Print(ctx, "warning", fmt.Sprintf("inventory decode failed error=%q", err))
			return
		}
		count := runtime.ReconcileInventory(inventory)
		logger.Print(ctx, "info", fmt.Sprintf("Thread inventory reconciled devices=%d", count))
		return
	}
	if thingName, ok := protocol.ParseCapabilityCommandTopic(message.Topic); ok {
		command, err := protocol.DecodeCapabilityCommand(message.Payload)
		if err != nil {
			logger.Print(ctx, "warning", fmt.Sprintf("command decode failed topic=%s error=%q", message.Topic, err))
			return
		}
		if command.ThingName != thingName {
			logger.Print(ctx, "warning", fmt.Sprintf("command thing mismatch topic=%s payloadThing=%s", message.Topic, command.ThingName))
			return
		}
		if err := runtime.HandleCommand(ctx, command); err != nil {
			logger.Print(ctx, "warning", fmt.Sprintf("Thread command handling failed thing=%s command=%s error=%q", command.ThingName, command.CommandID, err))
		}
	}
}

func publishHeartbeat(ctx context.Context, client *ipc.Client, activeThingName *string, seq uint64) {
	heartbeat := protocol.NewCapabilityHeartbeat(rigthread.AdapterID, protocol.HeartbeatRunning, activeThingName, rigthread.NowMS(), seq)
	payload, err := heartbeat.Marshal()
	if err != nil {
		return
	}
	topic, err := protocol.BuildCapabilityHeartbeatTopic(rigthread.AdapterID)
	if err != nil {
		return
	}
	_ = client.PublishRetained(topic, payload)
}
