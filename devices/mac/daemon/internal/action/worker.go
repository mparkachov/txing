// KVS video worker supervision. The mac device has no systemd (the unit
// runs the worker as a separate service), so the daemon spawns the
// worker itself while the device holds REDCON 1 and terminates it when
// leaving, keeping the camera active only at REDCON 1. Worker readiness
// still flows exclusively over the BoardVideoBridge: supervision only
// contributes process lifecycle, restart backoff, and the unexpected-exit
// error event that degrades reported REDCON until the restart recovers.
package action

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"syscall"
	"time"
)

const (
	workerStopGracePeriod  = 5 * time.Second
	workerRestartBaseDelay = time.Second
	workerRestartMaxDelay  = 30 * time.Second
	workerHealthyRunReset  = time.Minute
)

type WorkerSupervisor struct {
	command    string
	socketPath string
	logPath    string
	events     chan<- VideoWorkerEvent
	logf       Logf

	// restartBaseDelay is a test seam; production uses workerRestartBaseDelay.
	restartBaseDelay time.Duration

	mu     sync.Mutex
	cancel context.CancelFunc
	done   chan struct{}
}

func NewWorkerSupervisor(config Config, events chan<- VideoWorkerEvent, logf Logf) *WorkerSupervisor {
	return &WorkerSupervisor{
		command:          config.KVSMasterCommand,
		socketPath:       config.BridgeSocketPath,
		logPath:          filepath.Join(filepath.Dir(config.BridgeSocketPath), "txing-board-kvs-master.log"),
		events:           events,
		logf:             logf,
		restartBaseDelay: workerRestartBaseDelay,
	}
}

func (s *WorkerSupervisor) Start() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cancel != nil {
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	s.cancel = cancel
	s.done = done
	go func() {
		defer close(done)
		s.run(ctx)
	}()
	s.logf("info", fmt.Sprintf("video worker supervision started command=%s", s.command))
}

// Stop terminates the worker with SIGTERM (SIGKILL after a grace
// period) and returns only once the process has exited, so the camera
// is off before the caller reports a lower REDCON.
func (s *WorkerSupervisor) Stop() {
	s.mu.Lock()
	cancel := s.cancel
	done := s.done
	s.cancel = nil
	s.done = nil
	s.mu.Unlock()
	if cancel == nil {
		return
	}
	cancel()
	<-done
	s.logf("info", "video worker supervision stopped")
}

func (s *WorkerSupervisor) run(ctx context.Context) {
	// The worker's own STOPPED bridge report only goes out when its
	// shutdown finishes inside the SIGTERM grace period; a SIGKILL (or a
	// crash during restart backoff) would otherwise leave video ready
	// forever. Supervision owns the worker lifecycle, so it always drops
	// video readiness once the supervised worker is confirmed gone.
	defer s.sendEvent(VideoWorkerEvent{Kind: VideoWorkerStopped})
	delay := s.restartBaseDelay
	for {
		started := time.Now()
		err := s.runWorkerOnce(ctx)
		if ctx.Err() != nil {
			return
		}
		detail := "video worker exited unexpectedly"
		if err != nil {
			detail = fmt.Sprintf("video worker exited unexpectedly: %v", err)
		}
		s.logf("warning", detail)
		s.sendEvent(VideoWorkerEvent{Kind: VideoWorkerError, Detail: detail})
		if time.Since(started) >= workerHealthyRunReset {
			delay = s.restartBaseDelay
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(delay):
		}
		delay *= 2
		if delay > workerRestartMaxDelay {
			delay = workerRestartMaxDelay
		}
	}
}

func (s *WorkerSupervisor) runWorkerOnce(ctx context.Context) error {
	cmd := exec.Command(s.command, "--board-video-bridge-socket-path", s.socketPath)
	logFile, err := os.OpenFile(s.logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		s.logf("warning", fmt.Sprintf("video worker log file unavailable path=%s error=%q", s.logPath, err))
	} else {
		cmd.Stdout = logFile
		cmd.Stderr = logFile
		defer logFile.Close()
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	s.logf("info", fmt.Sprintf("video worker started pid=%d log=%s", cmd.Process.Pid, s.logPath))

	waitDone := make(chan error, 1)
	go func() { waitDone <- cmd.Wait() }()
	select {
	case <-ctx.Done():
		_ = cmd.Process.Signal(syscall.SIGTERM)
		select {
		case <-waitDone:
		case <-time.After(workerStopGracePeriod):
			_ = cmd.Process.Kill()
			<-waitDone
		}
		return nil
	case err := <-waitDone:
		return err
	}
}

// sendEvent never blocks: the session loop may be between MQTT
// reconnects, and supervision must not deadlock on a full channel.
func (s *WorkerSupervisor) sendEvent(event VideoWorkerEvent) {
	select {
	case s.events <- event:
	default:
	}
}
