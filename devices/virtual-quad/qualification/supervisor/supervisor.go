package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

const (
	runLimit = 840 * time.Second
	grace    = 10 * time.Second
)

var metadataClient = &http.Client{
	Timeout:   4 * time.Second,
	Transport: &http.Transport{}, // Link-local only; do not use proxy environment variables.
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

func readMetadata(path string, result any) error {
	req, err := http.NewRequest(http.MethodGet, "http://169.254.170.2"+path, nil)
	if err != nil {
		return errors.New("invalid ECS metadata path")
	}
	res, err := metadataClient.Do(req)
	if err != nil {
		return errors.New("ECS metadata request failed")
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("ECS metadata returned HTTP %d", res.StatusCode)
	}
	if err := json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(result); err != nil {
		return errors.New("invalid ECS metadata response")
	}
	return nil
}

func credentialsEnv() ([]string, error) {
	path := os.Getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
	if !strings.HasPrefix(path, "/v2/credentials/") {
		return nil, errors.New("ECS task role credentials URI is required")
	}
	var credentials struct {
		AccessKeyID     string
		SecretAccessKey string
		Token           string
		Expiration      time.Time
	}
	if err := readMetadata(path, &credentials); err != nil {
		return nil, err
	}
	if credentials.AccessKeyID == "" || credentials.SecretAccessKey == "" || credentials.Token == "" ||
		time.Until(credentials.Expiration) < runLimit+time.Minute {
		return nil, errors.New("ECS task credentials must be valid for the entire qualification run")
	}
	return []string{
		"AWS_ACCESS_KEY_ID=" + credentials.AccessKeyID,
		"AWS_SECRET_ACCESS_KEY=" + credentials.SecretAccessKey,
		"AWS_SESSION_TOKEN=" + credentials.Token,
	}, nil
}

type resourceSample struct {
	CPU struct {
		Usage struct {
			Total uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
	} `json:"cpu_stats"`
	Memory struct {
		Usage uint64 `json:"usage"`
	} `json:"memory_stats"`
}

func recordResources(scratch, metadataPath string, vm bool, done <-chan struct{}) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	var previousCPU uint64
	var previousAt time.Time
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
			if vm {
				previousVM = recordVMResources(previousVM)
			}
			if metadataPath == "" {
				continue
			}
			var sample resourceSample
			if err := readMetadata(metadataPath+"/stats", &sample); err != nil {
				log.Printf("QUAD_ECS_SAMPLE_UNAVAILABLE %v", err)
				continue
			}
			now := time.Now()
			total := sample.CPU.Usage.Total
			if total == 0 || sample.Memory.Usage == 0 {
				log.Print("QUAD_ECS_SAMPLE_UNAVAILABLE missing CPU or memory counters")
				continue
			}
			if previousCPU != 0 && total >= previousCPU {
				cores := float64(total-previousCPU) / float64(now.Sub(previousAt).Nanoseconds())
				log.Printf("QUAD_ECS_SAMPLE cpu_cores=%.3f memory_bytes=%d", cores, sample.Memory.Usage)
			}
			previousCPU, previousAt = total, now
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
	for _, cmd := range children {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGTERM)
	}
	timer := time.NewTimer(grace)
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

func run(mode string) error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	local, hang := mode == "local" || mode == "local-camera", mode == "hang-on-stop"
	if !local && !hang && mode != "kvs" {
		return errors.New("usage: virtual-quad-qualification [kvs|local|local-camera|hang-on-stop]")
	}
	log.Printf("QUAD_SUPERVISOR_START mode=%s", mode)

	var mediaEnv, mediaArgs []string
	var metadataPath string
	if local {
		mediaArgs = []string{"--local"}
	} else {
		if os.Getenv("AWS_REGION") == "" || os.Getenv("QUAD_VIDEO_CHANNEL") == "" ||
			os.Getenv("QUAD_MAVLINK_CHANNEL") == "" || os.Getenv("QUAD_VIDEO_CHANNEL") == os.Getenv("QUAD_MAVLINK_CHANNEL") {
			return errors.New("AWS_REGION and two distinct qualification channels are required")
		}
		var err error
		mediaEnv, err = credentialsEnv()
		if err != nil {
			return err
		}
		metadata, err := url.Parse(os.Getenv("ECS_CONTAINER_METADATA_URI_V4"))
		if err != nil || metadata.Scheme != "http" || metadata.Host != "169.254.170.2" ||
			!strings.HasPrefix(metadata.Path, "/v4/") {
			return errors.New("ECS v4 container metadata URI is required")
		}
		metadataPath = metadata.EscapedPath()
	}

	return runWorkload(ctx, mode, mediaEnv, mediaArgs, metadataPath, false, nil)
}

func runWorkload(ctx context.Context, mode string, mediaEnv, mediaArgs []string, metadataPath string, vm bool, monitor func(context.Context, string)) error {
	if ctx.Err() != nil {
		return nil
	}
	start := time.Now()
	scratch, err := os.MkdirTemp("/tmp", "quad-qualification-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(scratch)
	done := make(chan struct{})
	go recordResources(scratch, metadataPath, vm, done)
	defer close(done)

	healthPath := filepath.Join(scratch, "health.json")
	if monitor != nil {
		mediaEnv = append(mediaEnv, "QUAD_HEALTH_FILE="+healthPath)
	}
	if mode == "microvm-session" || mode == "local-camera" {
		mediaArgs = append(mediaArgs, "--camera")
		// The pinned build reads message IDs and intervals in milliseconds.
		// SIM_STATE feeds the camera at 30 Hz and EKF_STATUS_REPORT gates navigation at 2 Hz.
		intervals := filepath.Join(scratch, "message-intervals-chan0.txt")
		if err := os.WriteFile(intervals, []byte("108 33\n193 500\n"), 0600); err != nil {
			return fmt.Errorf("configure SITL health telemetry: %w", err)
		}
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
		"--defaults=/opt/quad/qualification.parm",
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
	for {
		select {
		case <-ctx.Done():
			hang := mode == "hang-on-stop"
			log.Printf("QUAD_SUPERVISOR_SIGNAL elapsed_ms=%d ignore=%t", time.Since(start).Milliseconds(), hang)
			if !hang {
				return nil
			}
			// Leave the children running for the platform termination test.
			<-timer.C
			return errors.New("unresponsive supervisor reached its local deadline")
		case <-timer.C:
			log.Print("QUAD_RUN_DEADLINE")
			return nil
		case child := <-exit:
			pending--
			return fmt.Errorf("%s exited before shutdown: %v", child.name, child.err)
		}
	}
}

func main() {
	log.SetFlags(log.Ldate | log.Ltime | log.Lmicroseconds | log.LUTC)
	mode := "kvs"
	if len(os.Args) > 1 {
		mode = os.Args[1]
	}
	if len(os.Args) > 2 {
		log.Fatal("expected at most one run mode")
	}
	var err error
	if mode == "microvm" || mode == "microvm-local" || mode == "microvm-session" {
		err = serveMicroVM(mode)
	} else {
		err = run(mode)
	}
	if err != nil {
		log.Fatalf("QUAD_SUPERVISOR_ERROR %v", err)
	}
}
