package main

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"
)

const (
	runLimit = 840 * time.Second
	grace    = 10 * time.Second
)

func recordResources(scratch string, done <-chan struct{}) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	var previousVM cpuSample
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			var scratchBytes int64
			err := filepath.WalkDir(scratch, func(_ string, entry fs.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if entry.Type().IsRegular() {
					info, err := entry.Info()
					if err != nil {
						return err
					}
					scratchBytes += info.Size()
				}
				return nil
			})
			if err != nil {
				log.Print("QUAD_SCRATCH_SAMPLE_UNAVAILABLE")
			} else {
				log.Printf("QUAD_SCRATCH_SAMPLE bytes=%d", scratchBytes)
			}
			previousVM = recordVMResources(previousVM)
		}
	}
}

type childResult struct {
	name string
	err  error
}

func startChild(exit chan<- childResult, dir string, env []string, name string, args ...string) (*exec.Cmd, error) {
	cmd := exec.Command("/opt/quad/bin/"+name, args...)
	cmd.Dir, cmd.Stdout, cmd.Stderr = dir, os.Stdout, os.Stderr
	cmd.Env = append(os.Environ(), "HOME="+dir, "XDG_CACHE_HOME="+dir)
	cmd.Env = append(cmd.Env, env...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start %s: %w", name, err)
	}
	go func() { exit <- childResult{name, cmd.Wait()} }()
	return cmd, nil
}

func shutdown(children []*exec.Cmd, pending int, exit <-chan childResult) {
	wait := grace
	if pending == 2 {
		// Keep the loopback autopilot alive while the media process closes the
		// write gate and attempts landing. Reserve time to reap both processes.
		_ = syscall.Kill(-children[0].Process.Pid, syscall.SIGTERM)
		timer := time.NewTimer(15 * time.Second)
		select {
		case <-exit:
			pending--
		case <-timer.C:
		}
		timer.Stop()
		wait = 3 * time.Second
	}
	for _, cmd := range children {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
	}
	timer := time.NewTimer(wait)
	defer timer.Stop()
	for pending > 0 {
		select {
		case <-exit:
			pending--
		case <-timer.C:
			for _, cmd := range children {
				_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
			}
			for ; pending > 0; pending-- {
				<-exit
			}
		}
	}
	log.Print("QUAD_CHILDREN_REAPED")
}

func runWorkload(ctx context.Context, mediaEnv, mediaArgs []string, monitor func(context.Context, string)) error {
	if ctx.Err() != nil {
		return nil
	}
	start := time.Now()
	scratch, err := os.MkdirTemp("/tmp", "virtual-quad-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(scratch)
	done := make(chan struct{})
	go recordResources(scratch, done)
	defer close(done)

	healthPath := filepath.Join(scratch, "health.json")
	if monitor != nil {
		mediaEnv = append(mediaEnv, "QUAD_HEALTH_FILE="+healthPath)
	}
	// The pinned SITL build reads message IDs and intervals in milliseconds.
	// SIM_STATE drives the camera. EKF_STATUS_REPORT and EXTENDED_SYS_STATE gate flight.
	intervals := filepath.Join(scratch, "message-intervals-chan0.txt")
	if err := os.WriteFile(intervals, []byte("108 33\n193 500\n245 200\n"), 0600); err != nil {
		return fmt.Errorf("configure SITL telemetry: %w", err)
	}
	exit := make(chan childResult, 2)
	children := make([]*exec.Cmd, 0, 2)
	pending := 0
	defer func() { shutdown(children, pending, exit) }()
	media, err := startChild(exit, scratch, mediaEnv, "virtual-quad-media", mediaArgs...)
	if err != nil {
		return err
	}
	children = append(children, media)
	pending++
	sitl, err := startChild(exit, scratch, nil, "arducopter",
		"--model=quad", "--speedup=1", "--home=-35.363261,149.165230,584,0", "--wipe",
		"--defaults=/opt/quad/arducopter.parm",
		"--serial0=udpclient:127.0.0.1:14550", "--serial1=none", "--serial2=none")
	if err != nil {
		return err
	}
	children = append(children, sitl)
	pending++

	if monitor != nil {
		monitorCtx, cancel := context.WithCancel(ctx)
		monitored := make(chan struct{})
		go func() {
			defer close(monitored)
			monitor(monitorCtx, healthPath)
		}()
		defer func() {
			cancel()
			<-monitored
		}()
	}

	timer := time.NewTimer(time.Until(start.Add(runLimit)))
	defer timer.Stop()
	select {
	case <-ctx.Done():
		log.Printf("QUAD_SUPERVISOR_STOP elapsed_ms=%d", time.Since(start).Milliseconds())
		return nil
	case <-timer.C:
		log.Print("QUAD_RUN_DEADLINE")
		return nil
	case child := <-exit:
		pending--
		return fmt.Errorf("%s exited before shutdown: %v", child.name, child.err)
	}
}

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.Lmicroseconds | log.LUTC)
	var err error
	switch {
	case len(os.Args) == 1:
		err = serveMicroVM()
	case len(os.Args) == 2 && os.Args[1] == "smoke":
		ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
		defer stop()
		err = runWorkload(ctx, nil, []string{"--local"}, nil)
	default:
		err = errors.New("usage: virtual-quad-supervisor [smoke]")
	}
	if err != nil {
		log.Fatalf("QUAD_SUPERVISOR_ERROR %v", err)
	}
}
