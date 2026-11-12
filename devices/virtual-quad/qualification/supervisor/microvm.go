package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
)

const hookPath = "/aws/lambda-microvms/runtime/v1/"
const probeRegion = "eu-central-1"

// Treat the service ID as opaque. AWS examples and live responses use
// different prefixes.
var vmID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,256}$`)

type microVM struct {
	local    bool
	managed  bool
	mu       sync.Mutex
	id, mode string
	stopping bool
	cancel   context.CancelFunc
	done     chan struct{}
	session  *sessionActivation
}

func serveMicroVM(mode string) error {
	vm := &microVM{local: mode == "microvm-local", managed: mode == "microvm-session"}
	server := &http.Server{
		Addr: ":8080", Handler: vm,
		ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 5 * time.Second,
		WriteTimeout: 30 * time.Second, MaxHeaderBytes: 8192,
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		vm.terminate(shutdown)
		_ = server.Close()
	}()
	log.Print("QUAD_HOOK_LISTENER_READY")
	err := server.ListenAndServe()
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func (vm *microVM) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}
	switch r.URL.Path {
	case hookPath + "ready", hookPath + "validate":
		vm.mu.Lock()
		defer vm.mu.Unlock()
		if vm.id != "" || vm.stopping {
			http.Error(w, "snapshot requires an idle workload", http.StatusConflict)
			return
		}
		w.WriteHeader(http.StatusOK)
	case hookPath + "run":
		vm.launch(w, r)
	case hookPath + "terminate":
		// The service's 20-second hook timeout should expire first in the
		// hung-workload test. Keep local callers bounded as well.
		ctx, cancel := context.WithTimeout(r.Context(), 25*time.Second)
		defer cancel()
		if !vm.terminate(ctx) {
			http.Error(w, "workload did not stop", http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusOK)
	default:
		http.NotFound(w, r)
	}
}

func (vm *microVM) launch(w http.ResponseWriter, r *http.Request) {
	var request struct {
		ID      string `json:"microvmId"`
		Payload string `json:"runHookPayload"`
	}
	err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384)).Decode(&request)
	if err != nil || !vmID.MatchString(request.ID) {
		http.Error(w, "invalid MicroVM run payload", http.StatusBadRequest)
		return
	}
	if vm.managed {
		vm.launchSession(w, r, request.ID, request.Payload)
		return
	}
	var payload struct {
		Mode string `json:"mode"`
	}
	if json.Unmarshal([]byte(request.Payload), &payload) != nil ||
		(payload.Mode != "kvs" && payload.Mode != "hang-on-stop") {
		http.Error(w, "invalid MicroVM run payload", http.StatusBadRequest)
		return
	}
	vm.mu.Lock()
	defer vm.mu.Unlock()
	if vm.stopping || (vm.id != "" && (vm.id != request.ID || vm.mode != payload.Mode)) {
		http.Error(w, "MicroVM already assigned or stopping", http.StatusConflict)
		return
	}
	if vm.id == "" {
		ctx, cancel := context.WithCancel(context.Background())
		vm.id, vm.mode, vm.cancel = request.ID, payload.Mode, cancel
		vm.done = make(chan struct{})
		go vm.work(ctx, request.ID, payload.Mode, vm.done)
	}
	w.WriteHeader(http.StatusOK)
}

func (vm *microVM) work(ctx context.Context, id, mode string, done chan struct{}) {
	defer close(done)
	log.Printf("QUAD_MICROVM_RUN id=%s mode=%s", id, mode)
	var mediaEnv, mediaArgs []string
	if vm.local {
		mediaArgs = []string{"--local"}
	} else {
		credentialsCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
		creds, err := microVMCredentials(credentialsCtx, time.Now().Add(runLimit))
		cancel()
		if err != nil {
			if ctx.Err() == nil {
				log.Printf("QUAD_SUPERVISOR_ERROR %v", err)
			}
			return
		}
		mediaEnv = append(mediaCredentials(creds),
			"AWS_REGION="+probeRegion,
			"QUAD_VIDEO_CHANNEL=quad-qualification-176-board-video",
			"QUAD_MAVLINK_CHANNEL=quad-qualification-176-mavlink")
	}
	if err := runWorkload(ctx, mode, mediaEnv, mediaArgs, "", !vm.local, nil); err != nil {
		log.Printf("QUAD_SUPERVISOR_ERROR %v", err)
	}
}

func microVMCredentials(ctx context.Context, deadline time.Time) (aws.Credentials, error) {
	// Resolve the execution role only after restore, through the standard AWS
	// provider chain. The native KVS sender needs credentials valid for one run.
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(probeRegion))
	if err != nil {
		return aws.Credentials{}, errors.New("could not configure the MicroVM credential provider")
	}
	creds, err := cfg.Credentials.Retrieve(ctx)
	if err != nil || !creds.HasKeys() || creds.SessionToken == "" {
		return aws.Credentials{}, errors.New("temporary MicroVM execution-role credentials unavailable")
	}
	if creds.CanExpire && creds.Expires.Before(deadline.Add(time.Minute)) {
		return aws.Credentials{}, errors.New("MicroVM execution-role credentials expire before the run deadline")
	}
	log.Printf("QUAD_ROLE_CREDENTIALS temporary=true expiry_known=%t", creds.CanExpire)
	return creds, nil
}

func mediaCredentials(creds aws.Credentials) []string {
	return []string{"AWS_ACCESS_KEY_ID=" + creds.AccessKeyID, "AWS_SECRET_ACCESS_KEY=" + creds.SecretAccessKey,
		"AWS_SESSION_TOKEN=" + creds.SessionToken}
}

func (vm *microVM) terminate(ctx context.Context) bool {
	vm.mu.Lock()
	if !vm.stopping {
		log.Print("QUAD_MICROVM_TERMINATE")
	}
	vm.stopping = true
	if vm.cancel != nil {
		vm.cancel()
	}
	done := vm.done
	vm.mu.Unlock()
	if done == nil {
		return true
	}
	select {
	case <-done:
		log.Print("QUAD_MICROVM_WORKLOAD_STOPPED")
		return true
	case <-ctx.Done():
		return false
	}
}

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
