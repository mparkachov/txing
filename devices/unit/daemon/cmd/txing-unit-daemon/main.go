package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/mparkachov/txing/devices/unit/daemon/internal/daemon"
)

func main() {
	cli, err := daemon.ParseCLI(os.Args[1:])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if cli.ShowVersion {
		fmt.Printf("txing-unit-daemon %s\n", daemon.DaemonVersion)
		return
	}
	config, err := daemon.RuntimeConfigFromCLI(cli)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := daemon.RunRuntime(ctx, config); err != nil && err != context.Canceled {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
