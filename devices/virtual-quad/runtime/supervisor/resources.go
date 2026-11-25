package main

import (
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
)

type cpuSample struct{ total, busy uint64 }

func recordVMResources(previous cpuSample) cpuSample {
	stat, err := os.ReadFile("/proc/stat")
	if err != nil {
		return previous
	}
	line, _, _ := strings.Cut(string(stat), "\n")
	fields := strings.Fields(line)
	if len(fields) < 9 || fields[0] != "cpu" {
		return previous
	}
	var current cpuSample
	for i, field := range fields[1:9] {
		v, err := strconv.ParseUint(field, 10, 64)
		if err != nil {
			return previous
		}
		current.total += v
		if i != 3 && i != 4 {
			current.busy += v
		}
	}
	meminfo, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return current
	}
	var total, available uint64
	for _, line := range strings.Split(string(meminfo), "\n") {
		switch {
		case strings.HasPrefix(line, "MemTotal:"):
			fmt.Sscanf(line, "MemTotal: %d kB", &total)
		case strings.HasPrefix(line, "MemAvailable:"):
			fmt.Sscanf(line, "MemAvailable: %d kB", &available)
		}
	}
	if previous.total != 0 && current.total > previous.total && current.busy >= previous.busy && total > available && available != 0 {
		log.Printf("QUAD_VM_SAMPLE cpu_percent=%.2f memory_used_bytes=%d",
			100*float64(current.busy-previous.busy)/float64(current.total-previous.total), (total-available)*1024)
	}
	return current
}
