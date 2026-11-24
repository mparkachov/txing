package qualification

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

// Handle runs the production supervisor. Setting both channel names enables
// the KVS masters and the MAVLink bridge during qualification.
func Handle(ctx context.Context, request struct {
	DurationSeconds int `json:"durationSeconds"`
}) (map[string]any, error) {
	root := filepath.Join(os.Getenv("LAMBDA_TASK_ROOT"), "quad")
	if os.Getenv("LAMBDA_TASK_ROOT") == "" {
		return nil, fmt.Errorf("LAMBDA_TASK_ROOT is required")
	}
	duration := request.DurationSeconds
	if duration == 0 {
		duration = 165
	}
	if duration < 120 || duration > 720 {
		return nil, fmt.Errorf("durationSeconds must be between 120 and 720")
	}
	runCtx, cancel := context.WithTimeout(ctx, time.Duration(duration)*time.Second)
	defer cancel()
	mode := "smoke"
	video, mavlink := os.Getenv("QUAD_VIDEO_CHANNEL"), os.Getenv("QUAD_MAVLINK_CHANNEL")
	if (video == "") != (mavlink == "") {
		return nil, fmt.Errorf("both qualification channel names are required")
	}
	if video != "" {
		mode = "qualify"
	}
	cmd := exec.Command(filepath.Join(root, "bin", "virtual-quad-supervisor"), mode)
	cmd.Env = append(os.Environ(),
		"TXING_QUAD_ROOT="+root,
		"LD_LIBRARY_PATH="+filepath.Join(root, "lib"),
		"GST_PLUGIN_SYSTEM_PATH_1_0="+filepath.Join(root, "plugins"),
		"GST_REGISTRY_FORK=no",
		"TXING_KVS_SYSTEM_CA_CERT_PATH="+filepath.Join(root, "certs", "starfield.pem"),
	)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	started := time.Now()
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start supervisor: %w", err)
	}
	wait := make(chan error, 1)
	go func() { wait <- cmd.Wait() }()
	select {
	case err := <-wait:
		return nil, fmt.Errorf("supervisor exited during qualification: %v", err)
	case <-runCtx.Done():
	}
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		return nil, fmt.Errorf("stop supervisor: %w", err)
	}
	select {
	case err := <-wait:
		if err != nil {
			return nil, fmt.Errorf("supervisor shutdown: %w", err)
		}
	case <-time.After(25 * time.Second):
		_ = cmd.Process.Kill()
		<-wait
		return nil, fmt.Errorf("supervisor shutdown timed out")
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	elapsed := time.Since(started)
	log.Printf("QUAD_QUALIFICATION_COMPLETE elapsed_ms=%d", elapsed.Milliseconds())
	return map[string]any{"elapsedMs": elapsed.Milliseconds()}, nil
}
