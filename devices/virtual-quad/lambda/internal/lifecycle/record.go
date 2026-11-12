package lifecycle

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"regexp"
	"time"
)

const (
	StartupTimeout  = 90 * time.Second
	FlightLimit     = 12 * time.Minute
	CleanupTimeout  = 30 * time.Second
	SessionLimit    = StartupTimeout + FlightLimit + CleanupTimeout
	HealthTimeout   = 15 * time.Second
	HealthInterval  = 5 * time.Second
	GrantInterval   = 2 * time.Second
	DispatchTimeout = 5 * time.Second
)

type Phase string

const (
	Stopped     Phase = "stopped"
	Starting    Phase = "starting"
	Operational Phase = "operational"
	Stopping    Phase = "stopping"
	FailedPhase Phase = "failed"
)

type Status string

const (
	Accepted  Status = "accepted"
	Succeeded Status = "succeeded"
	Failed    Status = "failed"
)

type Outcome string

const (
	OutcomeStopped Outcome = "stopped"
	OutcomeExpired Outcome = "expired"
	OutcomeFailed  Outcome = "failed"
)

const (
	ReasonStopped      = "operator stop"
	ReasonRigSleep     = "rig asleep"
	ReasonAssignment   = "rig assignment changed"
	ReasonStartup      = "startup deadline exceeded"
	ReasonHealth       = "worker health expired"
	ReasonDeadline     = "flight deadline reached"
	ReasonUnexpectedVM = "MicroVM terminated unexpectedly"
)

var (
	ErrInvalidRequest = errors.New("invalid virtual quad lifecycle request")
	ErrStaleTarget    = errors.New("virtual quad command targets a stale generation")
	ErrBusy           = errors.New("virtual quad already has a session")
	ErrRigAsleep      = errors.New("virtual quad rig is asleep")
	ErrGrantDenied    = errors.New("virtual quad worker grant denied")
	ErrStaleHealth    = errors.New("virtual quad health report is stale")
	ErrUnconfirmed    = errors.New("virtual quad termination is unconfirmed")
	ErrContention     = errors.New("virtual quad lifecycle update contention")
)

var requestIDPattern = regexp.MustCompile(`(?i)^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$`)

func ValidRequestID(id string) bool { return requestIDPattern.MatchString(id) }

type Assignment struct {
	DeviceID string `json:"deviceId"`
	TownID   string `json:"townId"`
	RigID    string `json:"rigId"`
}

func (a Assignment) valid() bool {
	return a.DeviceID != "" && a.TownID != "" && a.RigID != ""
}

type Receipt struct {
	RequestID string `json:"requestId"`
	Sequence  uint32 `json:"sequence"`
	REDCON    uint8  `json:"redcon"`
	Status    Status `json:"status"`
	Reason    string `json:"reason,omitempty"`
}

type LaunchConfig struct {
	ImageARN         string `json:"imageArn"`
	ImageVersion     string `json:"imageVersion"`
	ExecutionRoleARN string `json:"executionRoleArn"`
	IngressConnector string `json:"ingressConnector"`
	EgressConnector  string `json:"egressConnector"`
	LogGroup         string `json:"logGroup"`
	ControllerURL    string `json:"controllerUrl"`
}

func (c LaunchConfig) valid() bool {
	return c.ImageARN != "" && c.ImageVersion != "" && c.ExecutionRoleARN != "" &&
		c.IngressConnector != "" && c.EgressConnector != "" && c.LogGroup != "" && c.ControllerURL != ""
}

// Launch is written before RunMicrovm. Every retry sends these same inputs.
type Launch struct {
	LaunchConfig
	ClientToken              string `json:"clientToken"`
	MaximumDurationInSeconds int32  `json:"maximumDurationInSeconds"`
	RunHookPayload           string `json:"runHookPayload"`
}

type WorkerPayload struct {
	Assignment
	SessionID          string `json:"sessionId"`
	WorkerToken        string `json:"workerToken"`
	ControllerURL      string `json:"controllerUrl"`
	ShutdownDeadlineMS int64  `json:"shutdownDeadlineMs"`
}

type Worker struct {
	SessionID string `json:"sessionId"`
	VMID      string `json:"microvmId"`
	Token     string `json:"workerToken"`
}

type Health struct {
	Sequence     uint64 `json:"sequence"`
	ObservedAtMS int64  `json:"observedAtMs"`
	Heartbeat    bool   `json:"heartbeat"`
	Navigation   bool   `json:"navigation"`
	Mavlink      bool   `json:"mavlink"`
	Video        bool   `json:"video"`
}

type StopIntent struct {
	Receipt    Receipt `json:"receipt"`
	Reason     string  `json:"reason"`
	DeadlineMS int64   `json:"deadlineMs"`
}

type Session struct {
	ID                 string      `json:"id"`
	WorkerToken        string      `json:"workerToken"`
	Assignment         Assignment  `json:"assignment"`
	Phase              Phase       `json:"phase"`
	Start              Receipt     `json:"start"`
	AcceptedAtMS       int64       `json:"acceptedAtMs"`
	StartupDeadlineMS  int64       `json:"startupDeadlineMs"`
	FlightDeadlineMS   int64       `json:"flightDeadlineMs,omitempty"`
	ShutdownDeadlineMS int64       `json:"shutdownDeadlineMs"`
	Launch             *Launch     `json:"launch,omitempty"`
	LaunchAttempts     uint32      `json:"launchAttempts,omitempty"`
	DispatchUntilMS    int64       `json:"dispatchUntilMs,omitempty"`
	VMID               string      `json:"microvmId,omitempty"`
	Claimed            bool        `json:"claimed"`
	Health             Health      `json:"health"`
	ReadinessLostAtMS  int64       `json:"readinessLostAtMs,omitempty"`
	Stop               *StopIntent `json:"stop,omitempty"`
}

type Completion struct {
	SessionID     string     `json:"sessionId"`
	StartRevision uint64     `json:"startRevision"`
	Assignment    Assignment `json:"assignment"`
	Start         Receipt    `json:"start"`
	Stop          Receipt    `json:"stop"`
	Reason        string     `json:"reason"`
	Outcome       Outcome    `json:"outcome"`
}

// Record remains after termination so commands targeting older generations
// cannot reserve a replacement. Version is the storage compare-and-swap key.
type Record struct {
	DeviceID                string      `json:"deviceId"`
	Version                 uint64      `json:"version"`
	TerminalRevision        uint64      `json:"terminalRevision"`
	AvailabilityWatermarkMS int64       `json:"availabilityWatermarkMs"`
	Session                 *Session    `json:"session,omitempty"`
	Last                    *Completion `json:"last,omitempty"`
	Projection              *Projection `json:"projection,omitempty"`
}

type Availability struct {
	REDCON    uint8
	Mavlink   bool
	Video     bool
	ExpiresMS int64
}

func (r Record) Availability(nowMS int64) Availability {
	s := r.Session
	if s == nil {
		return Availability{REDCON: 4}
	}
	result := Availability{REDCON: 3}
	if s.Phase == Stopping || s.deadlineReason(nowMS) != "" || s.Health.Sequence == 0 {
		return result
	}
	result.ExpiresMS = min(s.Health.ObservedAtMS+HealthTimeout.Milliseconds(), s.authorityDeadline())
	if s.ReadinessLostAtMS != 0 {
		result.ExpiresMS = min(result.ExpiresMS, s.ReadinessLostAtMS+HealthTimeout.Milliseconds())
	}
	if nowMS >= result.ExpiresMS {
		return Availability{REDCON: 3}
	}
	result.Mavlink = s.Health.Heartbeat && s.Health.Mavlink
	result.Video = s.Health.Navigation && s.Health.Video
	if result.Mavlink {
		result.REDCON = 2
		if s.Phase == Operational && result.Video {
			result.REDCON = 1
		}
	}
	return result
}

func (s Session) authorityDeadline() int64 {
	if s.Phase == Operational {
		return s.FlightDeadlineMS
	}
	return s.StartupDeadlineMS
}

func (s Session) deadlineReason(nowMS int64) string {
	if s.Phase == Starting && nowMS >= s.StartupDeadlineMS {
		return ReasonStartup
	}
	if s.Phase == Operational {
		if nowMS >= s.FlightDeadlineMS {
			return ReasonDeadline
		}
		if nowMS >= s.Health.ObservedAtMS+HealthTimeout.Milliseconds() {
			return ReasonHealth
		}
		if s.ReadinessLostAtMS != 0 && nowMS >= s.ReadinessLostAtMS+HealthTimeout.Milliseconds() {
			return ReasonHealth
		}
	}
	return ""
}

func (r *Record) markAvailability(nowMS int64) {
	r.AvailabilityWatermarkMS = max(nowMS, r.AvailabilityWatermarkMS+1)
	if r.Projection != nil {
		r.AvailabilityWatermarkMS = max(r.AvailabilityWatermarkMS, r.Projection.TimestampMS+1)
	}
}

func (r *Record) beginStop(receipt Receipt, reason string, nowMS int64) {
	s := r.Session
	s.Phase = Stopping
	s.Stop = &StopIntent{
		Receipt: receipt, Reason: reason,
		DeadlineMS: min(nowMS+CleanupTimeout.Milliseconds(), s.ShutdownDeadlineMS),
	}
	r.markAvailability(nowMS)
}

func (s Session) matchesWorker(worker Worker) bool {
	return worker.SessionID == s.ID && worker.VMID != "" &&
		subtle.ConstantTimeCompare([]byte(s.WorkerToken), []byte(worker.Token)) == 1
}

func (s Session) launchRequest(config LaunchConfig, nowMS int64) (Launch, error) {
	if !config.valid() {
		return Launch{}, ErrInvalidRequest
	}
	payload, err := json.Marshal(WorkerPayload{
		Assignment: s.Assignment, SessionID: s.ID, WorkerToken: s.WorkerToken,
		ControllerURL: config.ControllerURL, ShutdownDeadlineMS: s.ShutdownDeadlineMS,
	})
	if err != nil {
		return Launch{}, err
	}
	return Launch{
		LaunchConfig: config, ClientToken: s.ID, RunHookPayload: string(payload),
		MaximumDurationInSeconds: int32((s.ShutdownDeadlineMS - max(nowMS, s.AcceptedAtMS)) / time.Second.Milliseconds()),
	}, nil
}
