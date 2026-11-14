package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/signer/v4"
)

const (
	grantInterval     = 2 * time.Second
	healthInterval    = 5 * time.Second
	healthEvidenceAge = 2500 * time.Millisecond
)

var sessionSegment = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,128}$`)
var workerHostname = regexp.MustCompile(`^[a-z0-9]+\.lambda-url\.` + sessionRegion + `\.on\.aws$`)

type sessionAssignment struct {
	DeviceID           string `json:"deviceId"`
	TownID             string `json:"townId"`
	RigID              string `json:"rigId"`
	SessionID          string `json:"sessionId"`
	Token              string `json:"workerToken"`
	URL                string `json:"controllerUrl"`
	ShutdownDeadlineMS int64  `json:"shutdownDeadlineMs"`
}

func (a sessionAssignment) deadline() time.Time {
	return time.UnixMilli(a.ShutdownDeadlineMS)
}

func (a sessionAssignment) valid(now time.Time) bool {
	for _, segment := range []string{a.DeviceID, a.TownID, a.RigID, a.SessionID, a.Token} {
		if !sessionSegment.MatchString(segment) {
			return false
		}
	}
	endpoint, err := url.Parse(a.URL)
	return err == nil && endpoint.Scheme == "https" && workerHostname.MatchString(endpoint.Host) &&
		endpoint.User == nil && (endpoint.EscapedPath() == "" || endpoint.EscapedPath() == "/") &&
		endpoint.RawQuery == "" && !endpoint.ForceQuery && endpoint.Fragment == "" &&
		strings.HasPrefix(a.DeviceID, "virtual-quad-") &&
		a.deadline().After(now) && !a.deadline().After(now.Add(runLimit+grantInterval))
}

type sessionActivation struct {
	assignment sessionAssignment
	claimed    chan struct{}
	status     int // Published by closing claimed.
}

func (vm *microVM) launchSession(w http.ResponseWriter, r *http.Request, id, payload string) {
	var assignment sessionAssignment
	if json.Unmarshal([]byte(payload), &assignment) != nil || !assignment.valid(time.Now()) {
		http.Error(w, "invalid session assignment", http.StatusBadRequest)
		return
	}
	vm.mu.Lock()
	if vm.stopping || (vm.session != nil && (vm.id != id || vm.session.assignment != assignment)) {
		vm.mu.Unlock()
		http.Error(w, "MicroVM already assigned or stopping", http.StatusConflict)
		return
	}
	if vm.session == nil {
		ctx, cancel := context.WithDeadline(context.Background(), assignment.deadline())
		vm.id, vm.cancel, vm.done = id, cancel, make(chan struct{})
		vm.session = &sessionActivation{assignment: assignment, claimed: make(chan struct{})}
		go vm.session.work(ctx, cancel, id, vm.done)
	}
	activation, done := vm.session, vm.done
	vm.mu.Unlock()

	select {
	case <-activation.claimed:
		status := activation.status
		if status == http.StatusOK {
			select {
			case <-done:
				status = http.StatusConflict
			default:
			}
		}
		w.WriteHeader(status)
	case <-r.Context().Done():
	}
}

type sessionWorker struct {
	SessionID string `json:"sessionId"`
	VMID      string `json:"microvmId"`
	Token     string `json:"workerToken"`
}

type sessionHealth struct {
	Sequence     uint64 `json:"sequence"`
	ObservedAtMS int64  `json:"observedAtMs"`
	Heartbeat    bool   `json:"heartbeat"`
	Navigation   bool   `json:"navigation"`
	Mavlink      bool   `json:"mavlink"`
	Video        bool   `json:"video"`
}

type sessionClient struct {
	assignment sessionAssignment
	worker     sessionWorker
	creds      aws.Credentials
	http       *http.Client
	signer     *v4.Signer
}

func newSessionClient(assignment sessionAssignment, id string, creds aws.Credentials) sessionClient {
	return sessionClient{
		assignment: assignment, creds: creds, signer: v4.NewSigner(),
		worker: sessionWorker{SessionID: assignment.SessionID, VMID: id, Token: assignment.Token},
		http: &http.Client{
			Transport: &http.Transport{ForceAttemptHTTP2: true},
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

func (c sessionClient) request(ctx context.Context, action string, health *sessionHealth) (int, error) {
	timeout := 4 * time.Second
	if action == "grant" {
		timeout = grantInterval
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	body, err := json.Marshal(struct {
		Action   string         `json:"action"`
		DeviceID string         `json:"deviceId"`
		Worker   sessionWorker  `json:"worker"`
		Health   *sessionHealth `json:"health,omitempty"`
	}{action, c.assignment.DeviceID, c.worker, health})
	if err != nil {
		return 0, errors.New("encode session controller request")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.assignment.URL, bytes.NewReader(body))
	if err != nil {
		return 0, errors.New("construct session controller request")
	}
	req.Header.Set("Content-Type", "application/json")
	digest := sha256.Sum256(body)
	payloadHash := hex.EncodeToString(digest[:])
	req.Header.Set("X-Amz-Content-Sha256", payloadHash)
	if err := c.signer.SignHTTP(ctx, c.creds, req, payloadHash, "lambda", sessionRegion, time.Now()); err != nil {
		return 0, errors.New("sign session controller request")
	}
	res, err := c.http.Do(req)
	if err != nil {
		return 0, errors.New("session controller request failed")
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return res.StatusCode, nil
	}
	var result struct {
		Granted            bool  `json:"granted"`
		ShutdownDeadlineMS int64 `json:"shutdownDeadlineMs"`
	}
	data, err := io.ReadAll(io.LimitReader(res.Body, 4097))
	if err != nil || len(data) > 4096 || json.Unmarshal(data, &result) != nil ||
		!result.Granted || result.ShutdownDeadlineMS != c.assignment.ShutdownDeadlineMS {
		return 0, errors.New("invalid session controller grant")
	}
	return http.StatusOK, nil
}

func (c sessionClient) claim(ctx context.Context) int {
	for attempt := 0; attempt < 3 && ctx.Err() == nil; attempt++ {
		status, err := c.request(ctx, "claim", nil)
		if err == nil && status == http.StatusOK {
			return status
		}
		if err == nil && status >= 400 && status < 500 && status != http.StatusTooManyRequests {
			log.Printf("QUAD_SESSION_CLAIM_DENIED status=%d", status)
			return http.StatusForbidden
		}
	}
	log.Print("QUAD_SESSION_CLAIM_UNAVAILABLE")
	return http.StatusServiceUnavailable
}

func (a *sessionActivation) work(ctx context.Context, cancel context.CancelFunc, id string, done chan struct{}) {
	defer close(done)
	defer cancel()
	credentialsCtx, stopCredentials := context.WithTimeout(ctx, 10*time.Second)
	creds, err := microVMCredentials(credentialsCtx, a.assignment.deadline())
	stopCredentials()
	if err != nil {
		log.Printf("QUAD_SESSION_CREDENTIALS_ERROR %v", err)
		a.status = http.StatusServiceUnavailable
		close(a.claimed)
		return
	}
	client := newSessionClient(a.assignment, id, creds)
	defer client.http.CloseIdleConnections()
	a.status = client.claim(ctx)
	close(a.claimed)
	if a.status != http.StatusOK || ctx.Err() != nil {
		return
	}
	log.Printf("QUAD_SESSION_CLAIMED id=%s session=%s", id, a.assignment.SessionID)
	mediaEnv := append(mediaCredentials(creds),
		"AWS_REGION="+sessionRegion,
		"QUAD_VIDEO_CHANNEL="+a.assignment.DeviceID+"-board-video",
		"QUAD_MAVLINK_CHANNEL="+a.assignment.DeviceID+"-mavlink")
	if err := runWorkload(ctx, mediaEnv, nil, func(ctx context.Context, path string) {
		client.monitor(ctx, cancel, path)
	}); err != nil {
		log.Printf("QUAD_SESSION_WORKLOAD_ERROR %v", err)
	}
}

func (c sessionClient) monitor(ctx context.Context, revoke context.CancelFunc, path string) {
	healthDone := make(chan struct{})
	go func() {
		defer close(healthDone)
		c.reportHealth(ctx, revoke, path)
	}()
	ticker := time.NewTicker(grantInterval)
	defer ticker.Stop()
	defer func() { <-healthDone }()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			status, err := c.request(ctx, "grant", nil)
			if ctx.Err() != nil {
				return
			}
			if err != nil || status != http.StatusOK {
				log.Printf("QUAD_SESSION_GRANT_LOST status=%d error=%v", status, err)
				revoke()
				return
			}
		}
	}
}

func (c sessionClient) reportHealth(ctx context.Context, revoke context.CancelFunc, path string) {
	ticker := time.NewTicker(healthInterval)
	defer ticker.Stop()
	for sequence := uint64(1); ctx.Err() == nil; sequence++ {
		sample := readSessionHealth(path, time.Now(), sequence)
		status, err := c.request(ctx, "health", &sample)
		if status == http.StatusForbidden {
			log.Print("QUAD_SESSION_HEALTH_DENIED")
			revoke()
			return
		}
		if ctx.Err() != nil {
			return
		}
		if err != nil || status != http.StatusOK {
			log.Printf("QUAD_SESSION_HEALTH_UNCONFIRMED status=%d error=%v", status, err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func readSessionHealth(path string, now time.Time, sequence uint64) sessionHealth {
	fallback := sessionHealth{Sequence: sequence, ObservedAtMS: now.UnixMilli()}
	file, err := os.Open(path)
	if err != nil {
		return fallback
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, 513))
	var sample sessionHealth
	if err != nil || len(data) > 512 || json.Unmarshal(data, &sample) != nil ||
		sample.ObservedAtMS < now.Add(-healthEvidenceAge).UnixMilli() || sample.ObservedAtMS > now.UnixMilli() {
		return fallback
	}
	sample.Sequence = sequence
	return sample
}
