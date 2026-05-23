package main

import (
	"fmt"
	"os"

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
	if _, err := daemon.RuntimeConfigFromCLI(cli); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "txing-unit-daemon Go runtime is not implemented in this milestone")
	os.Exit(1)
}
