package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/mparkachov/txing/devices/mac/daemon/internal/action"
	"github.com/mparkachov/txing/devices/mac/daemon/internal/macconfig"
	"github.com/mparkachov/txing/devices/mac/daemon/internal/macdaemon"
	"github.com/mparkachov/txing/devices/mac/daemon/internal/version"
)

func main() {
	var configDir string
	var dryRun bool
	var showVersion bool
	flag.StringVar(&configDir, "config-dir", "", "mac daemon config directory")
	flag.BoolVar(&dryRun, "dry-run", false, "validate configuration and exit")
	flag.BoolVar(&showVersion, "version", false, "print version and exit")
	flag.Parse()

	if showVersion {
		fmt.Println(version.Version)
		return
	}
	cfg, err := macconfig.Load(configDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "configuration error: %v\n", err)
		os.Exit(2)
	}
	actionConfig := action.Config{
		ThingID:               cfg.ThingID,
		ClientID:              cfg.ClientID,
		AWSRegion:             cfg.AWSRegion,
		IoTEndpoint:           cfg.IoTEndpoint,
		IoTCredentialEndpoint: cfg.IoTCredentialEndpoint,
		IoTRoleAlias:          cfg.IoTRoleAlias,
		IoTCertFile:           cfg.IoTCertFile,
		IoTPrivateKeyFile:     cfg.IoTPrivateKeyFile,
		IoTRootCAFile:         cfg.IoTRootCAFile,
		Capabilities:          cfg.Capabilities,
		CapabilityTTL:         cfg.CapabilityTTL,
		Heartbeat:             cfg.ActionHeartbeat,
		VideoChannelName:      cfg.VideoChannelName,
		BridgeSocketPath:      cfg.BridgeSocketPath,
		KVSPreferIPv6:         cfg.KVSPreferIPv6,
		KVSDisableIPv4TURN:    cfg.KVSDisableIPv4TURN,
	}
	actionEnabled := actionConfig.Enabled()
	if actionEnabled {
		if err := actionConfig.Validate(); err != nil {
			fmt.Fprintf(os.Stderr, "action layer configuration error: %v\n", err)
			os.Exit(2)
		}
	}
	if dryRun {
		fmt.Printf("txing-mac-daemon version=%s thing=%s ipc=%s initialRedcon=%d actionLayer=%t\n", version.Version, cfg.ThingID, cfg.IPCSocket, cfg.InitialRedcon, actionEnabled)
		return
	}

	logf := func(level string, message string) {
		fmt.Printf("%s level=%s %s\n", time.Now().UTC().Format(time.RFC3339Nano), level, message)
	}
	logf("info", fmt.Sprintf("version=%s thing=%s initialRedcon=%d actionLayer=%t", version.Version, cfg.ThingID, cfg.InitialRedcon, actionEnabled))

	controller := action.NewController(actionConfig, actionEnabled, version.Version, action.Logf(logf))
	defer controller.Shutdown()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := macdaemon.Run(ctx, cfg, controller, logf); err != nil {
		fmt.Fprintf(os.Stderr, "mac daemon stopped with error: %v\n", err)
		os.Exit(1)
	}
}
