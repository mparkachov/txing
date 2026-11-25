package session

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"time"
)

// Workload owns a supervisor and the health file for one invocation. The
// supervisor owns SITL and media, including their graceful landing and reaping.
type Workload struct {
	cmd     *exec.Cmd
	done    chan struct{}
	waitErr error
	dir     string
	health  string
}

func StartWorkload(root, device string) (*Workload, error) {
	dir, err := os.MkdirTemp("", "virtual-quad-session-")
	if err != nil {
		return nil, fmt.Errorf("create session workspace: %w", err)
	}
	health := filepath.Join(dir, "health.json")
	cmd := exec.Command(filepath.Join(root, "bin", "virtual-quad-supervisor"), "managed", health)
	cmd.Env = append(os.Environ(),
		"TXING_QUAD_ROOT="+root,
		"LD_LIBRARY_PATH="+filepath.Join(root, "lib"),
		"GST_PLUGIN_SYSTEM_PATH_1_0="+filepath.Join(root, "plugins"),
		"GST_REGISTRY_FORK=no",
		"TXING_KVS_SYSTEM_CA_CERT_PATH="+filepath.Join(root, "certs", "starfield.pem"),
		"QUAD_VIDEO_CHANNEL="+device+"-board-video",
		"QUAD_MAVLINK_CHANNEL="+device+"-mavlink",
	)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Start(); err != nil {
		os.RemoveAll(dir)
		return nil, fmt.Errorf("start virtual quad supervisor: %w", err)
	}
	w := &Workload{cmd: cmd, done: make(chan struct{}), dir: dir, health: health}
	go func() { w.waitErr = cmd.Wait(); close(w.done) }()
	return w, nil
}

func (w *Workload) Done() <-chan struct{} { return w.done }

func (w *Workload) Err() error { <-w.done; return w.waitErr }

// Health rejects missing, malformed, or stale evidence instead of allowing a
// frozen media process to keep advertising flight readiness.
func (w *Workload) Health() Health {
	return w.readHealth(time.Now)
}

func (w *Workload) readHealth(clock func() time.Time) Health {
	f, err := os.Open(w.health)
	if err != nil {
		return Health{}
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, 513))
	// The media process can atomically replace the file during this read.
	// Compare its timestamp with a clock sampled after reading it.
	now := clock()
	var sample struct {
		ObservedAt int64 `json:"observedAtMs"`
		Heartbeat  bool  `json:"heartbeat"`
		Navigation bool  `json:"navigation"`
		Mavlink    bool  `json:"mavlink"`
		Video      bool  `json:"video"`
	}
	if err != nil || len(data) > 512 || json.Unmarshal(data, &sample) != nil ||
		sample.ObservedAt < now.Add(-2500*time.Millisecond).UnixMilli() || sample.ObservedAt > now.UnixMilli() {
		return Health{}
	}
	return Health{sample.Heartbeat, sample.Navigation, sample.Mavlink, sample.Video}
}

// Stop waits for the supervisor's bounded landing and child reaping before
// escalating, so a subsequent warm invocation starts with a clean workspace.
func (w *Workload) Stop() error {
	defer os.RemoveAll(w.dir)
	if err := w.cmd.Process.Signal(syscall.SIGTERM); err != nil && err != os.ErrProcessDone {
		return fmt.Errorf("signal supervisor: %w", err)
	}
	select {
	case <-w.done:
		return w.waitErr
	case <-time.After(25 * time.Second):
		_ = w.cmd.Process.Kill()
		<-w.done
		return fmt.Errorf("supervisor shutdown timed out")
	}
}
