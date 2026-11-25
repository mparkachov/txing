package session

import (
	"errors"
	"time"
)

const (
	StartupLimit       = 90 * time.Second
	FlightLimit        = 12 * time.Minute
	CleanupLimit       = 30 * time.Second
	HealthLimit        = 15 * time.Second
	MediaRecoveryLimit = 30 * time.Second
	SessionLimit       = StartupLimit + FlightLimit + CleanupLimit
)

var (
	ErrBusy      = errors.New("virtual quad already has a session")
	ErrStale     = errors.New("virtual quad command targets a stale generation")
	ErrInvalid   = errors.New("invalid virtual quad session request")
	ErrNotOwner  = errors.New("virtual quad invocation no longer owns the session")
	ErrExpired   = errors.New("virtual quad session deadline reached")
	ErrDuplicate = errors.New("virtual quad command already accepted")
)

// State is stored in the simulation shadow. The version on the shadow, rather
// than a field in this document, is used for conditional writes.
type State struct {
	Phase                 string   `json:"phase"`
	TerminalRevision      uint64   `json:"terminalRevision"`
	SessionID             *string  `json:"sessionId"`
	LastSessionID         *string  `json:"lastSessionId"`
	LastOutcome           *string  `json:"lastOutcome"`
	LastReason            *string  `json:"lastReason"`
	AvailabilityWatermark *int64   `json:"availabilityWatermarkMs"`
	AvailabilityExpires   *int64   `json:"availabilityExpiresAtMs"`
	StartupDeadline       *int64   `json:"startupDeadlineMs"`
	FlightDeadline        *int64   `json:"flightDeadlineMs"`
	ShutdownDeadline      *int64   `json:"shutdownDeadlineMs"`
	Run                   *Run     `json:"run"`
	ProjectionTimestamp   int64    `json:"projectionTimestampMs"`
	Receipt               *Receipt `json:"receipt"`
}

type Receipt struct {
	RequestID string `json:"requestId"`
	Sequence  uint32 `json:"sequence"`
	REDCON    uint8  `json:"redcon"`
	Status    string `json:"status"`
	Reason    string `json:"reason"`
}

type Run struct {
	Owner          string `json:"owner"`
	TownID         string `json:"townId"`
	RigID          string `json:"rigId"`
	StartRequestID string `json:"startRequestId"`
	StartSequence  uint32 `json:"startSequence"`
	StopRequestID  string `json:"stopRequestId"`
	StopSequence   uint32 `json:"stopSequence"`
	HardDeadline   int64  `json:"hardDeadlineMs"`
	Simulation     bool   `json:"simulation"`
	Mavlink        bool   `json:"mavlink"`
	Video          bool   `json:"video"`
	ReadinessLost  *int64 `json:"readinessLostAtMs"`
}

type Health struct {
	Heartbeat  bool
	Navigation bool
	Mavlink    bool
	Video      bool
}

type Availability struct {
	REDCON     uint8
	Simulation bool
	Mavlink    bool
	Video      bool
}

// Availability returns only fresh, session-bound readiness. Terminal states
// are reachable at REDCON 4 and Stop withdraws the active capabilities.
func (s State) Availability(now int64) Availability {
	if s.Run == nil {
		return Availability{REDCON: 4}
	}
	result := Availability{REDCON: 3}
	if s.Phase == "stopping" || s.AvailabilityExpires == nil || now >= *s.AvailabilityExpires {
		return result
	}
	result.Simulation = s.Run.Simulation
	result.Mavlink = s.Run.Mavlink
	result.Video = s.Run.Video
	if result.Mavlink {
		result.REDCON = 2
		if s.Phase == "operational" && result.Video {
			result.REDCON = 1
		}
	}
	return result
}

// Start accepts a command once, before any simulator process is launched.
// Expired invocations may be replaced without waiting for a repair process.
func (s *State) Start(requestID, owner, townID, rigID string, sequence uint32, revision uint64, now, invocationDeadline int64) error {
	if requestID == "" || owner == "" || townID == "" || rigID == "" || now <= 0 || invocationDeadline <= now {
		return ErrInvalid
	}
	if revision != s.TerminalRevision {
		return ErrStale
	}
	if (s.Run != nil && s.Run.StartRequestID == requestID) || (s.LastSessionID != nil && *s.LastSessionID == requestID) {
		return ErrDuplicate
	}
	startupDeadline := now + StartupLimit.Milliseconds()
	shutdownDeadline := min(now+SessionLimit.Milliseconds(), invocationDeadline)
	if shutdownDeadline <= startupDeadline+CleanupLimit.Milliseconds() {
		return ErrInvalid
	}
	if s.Run != nil {
		if now < s.Run.HardDeadline {
			return ErrBusy
		}
		s.finish("failed", "invocation deadline reached", now)
	}
	s.Phase, s.SessionID = "starting", &requestID
	s.StartupDeadline, s.FlightDeadline, s.ShutdownDeadline = &startupDeadline, nil, &shutdownDeadline
	s.AvailabilityWatermark, s.AvailabilityExpires = &now, nil
	s.Run = &Run{Owner: owner, TownID: townID, RigID: rigID, StartRequestID: requestID,
		StartSequence: sequence, HardDeadline: invocationDeadline}
	s.Receipt = &Receipt{RequestID: requestID, Sequence: sequence, REDCON: 1, Status: "accepted"}
	return nil
}

func (s *State) Stop(sessionID, requestID string, sequence uint32, now int64) error {
	if requestID == "" || sessionID == "" || now <= 0 {
		return ErrInvalid
	}
	if s.Run == nil || s.SessionID == nil || *s.SessionID != sessionID {
		return ErrStale
	}
	if s.ShutdownDeadline == nil {
		return ErrInvalid
	}
	if s.Phase == "stopping" {
		if s.Run.StopRequestID == requestID {
			return ErrDuplicate
		}
		return ErrBusy
	}
	s.Phase = "stopping"
	s.Run.StopRequestID, s.Run.StopSequence = requestID, sequence
	s.Receipt = &Receipt{RequestID: requestID, Sequence: sequence, REDCON: 4, Status: "accepted"}
	s.Run.Simulation, s.Run.Mavlink, s.Run.Video = false, false, false
	s.AvailabilityWatermark, s.AvailabilityExpires = &now, nil
	deadline := min(now+CleanupLimit.Milliseconds(), *s.ShutdownDeadline)
	s.ShutdownDeadline = &deadline
	return nil
}

// UpdateHealth preserves the readiness deadlines consumed by Office and the
// agent. A session never extends its flight budget after becoming ready.
func (s *State) UpdateHealth(owner string, health Health, now int64) error {
	if s.Run == nil || s.Run.Owner != owner || s.Phase == "stopping" {
		return ErrNotOwner
	}
	if now <= 0 || s.ShutdownDeadline == nil || s.StartupDeadline == nil {
		return ErrInvalid
	}
	if now >= *s.ShutdownDeadline || (s.Phase == "starting" && now >= *s.StartupDeadline) ||
		(s.Phase == "operational" && s.FlightDeadline != nil && now >= *s.FlightDeadline) {
		return ErrExpired
	}
	if s.Phase == "operational" && s.AvailabilityExpires != nil && now >= *s.AvailabilityExpires {
		return ErrExpired
	}
	if s.Run.ReadinessLost != nil {
		limit := HealthLimit
		if health.Heartbeat && health.Navigation {
			limit = MediaRecoveryLimit
		}
		if now >= *s.Run.ReadinessLost+limit.Milliseconds() {
			return ErrExpired
		}
	}
	ready := health.Heartbeat && health.Navigation && health.Mavlink && health.Video
	if s.Phase == "starting" && ready {
		deadline := min(now+FlightLimit.Milliseconds(), *s.ShutdownDeadline-CleanupLimit.Milliseconds())
		s.FlightDeadline = &deadline
		s.Phase = "operational"
		s.Receipt = &Receipt{RequestID: s.Run.StartRequestID, Sequence: s.Run.StartSequence, REDCON: 1, Status: "succeeded"}
	}
	previousSimulation, previousMavlink, previousVideo := s.Run.Simulation, s.Run.Mavlink, s.Run.Video
	s.Run.Simulation = health.Heartbeat
	s.Run.Mavlink = health.Heartbeat && health.Mavlink
	s.Run.Video = health.Navigation && health.Video
	if s.Phase == "operational" && !ready && s.Run.ReadinessLost == nil {
		s.Run.ReadinessLost = &now
	} else if ready {
		s.Run.ReadinessLost = nil
	}
	if s.AvailabilityWatermark == nil || previousSimulation != s.Run.Simulation ||
		previousMavlink != s.Run.Mavlink || previousVideo != s.Run.Video {
		s.AvailabilityWatermark = &now
	}
	expires := min(now+HealthLimit.Milliseconds(), *s.StartupDeadline)
	if s.Phase == "operational" && s.FlightDeadline != nil {
		expires = min(now+HealthLimit.Milliseconds(), *s.FlightDeadline)
	}
	if s.Run.ReadinessLost != nil {
		limit := HealthLimit
		if health.Heartbeat && health.Navigation {
			limit = MediaRecoveryLimit
		}
		expires = min(expires, *s.Run.ReadinessLost+limit.Milliseconds())
	}
	s.AvailabilityExpires = &expires
	return nil
}

func (s *State) Finish(owner, outcome, reason string, now int64) error {
	if s.Run == nil || s.Run.Owner != owner {
		return ErrNotOwner
	}
	if outcome == "" || reason == "" || now <= 0 {
		return ErrInvalid
	}
	s.finish(outcome, reason, now)
	return nil
}

func (s *State) finish(outcome, reason string, now int64) {
	if s.Run != nil && s.Run.StopRequestID != "" {
		status := "succeeded"
		if outcome == "failed" {
			status = "failed"
		}
		s.Receipt = &Receipt{RequestID: s.Run.StopRequestID, Sequence: s.Run.StopSequence,
			REDCON: 4, Status: status, Reason: reason}
	} else if s.Run != nil && s.Phase == "starting" {
		s.Receipt = &Receipt{RequestID: s.Run.StartRequestID, Sequence: s.Run.StartSequence,
			REDCON: 1, Status: "failed", Reason: reason}
	}
	s.LastSessionID, s.LastOutcome, s.LastReason = s.SessionID, &outcome, &reason
	s.SessionID, s.Run = nil, nil
	s.StartupDeadline, s.FlightDeadline, s.ShutdownDeadline = nil, nil, nil
	s.AvailabilityWatermark, s.AvailabilityExpires = &now, nil
	s.TerminalRevision++
	s.Phase = "stopped"
	if outcome == "failed" {
		s.Phase = "failed"
	}
}
