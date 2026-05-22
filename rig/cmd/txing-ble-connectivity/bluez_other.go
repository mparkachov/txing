//go:build !linux

package main

import (
	"context"

	"tinygo.org/x/bluetooth"
)

func prepareBLEConnection(_ context.Context, _ bluetooth.Address) error {
	return nil
}
