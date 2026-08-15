package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/mparkachov/txing/devices/common/board/daemon/internal/daemon"
)

func main() {
	config, showVersion, err := daemon.ParseMAVLinkServiceConfig(os.Args[1:], daemon.ProcessEnvironment())
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if showVersion {
		fmt.Printf("txing-%s-mavlink %s\n", daemon.DeviceType, daemon.DaemonVersion)
		return
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := daemon.RunMAVLinkService(ctx, config); err != nil && err != context.Canceled {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
