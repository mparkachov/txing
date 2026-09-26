package agentstatus

import (
	"context"
	"errors"
	"fmt"
	"net"
)

const UDPPort = 14550

var (
	ErrStaleTask       = errors.New("agent shadow task identity changed")
	ErrVersionConflict = errors.New("agent shadow version conflict")
)

type Task struct {
	Status string  `json:"status"`
	ID     *string `json:"id"`
}

type Endpoint struct {
	IPv4    *string `json:"ipv4"`
	IPv6    *string `json:"ipv6"`
	UDPPort *int    `json:"udpPort"`
}

type Reported struct {
	Task      Task     `json:"task"`
	Endpoint  Endpoint `json:"endpoint"`
	MAVLink   string   `json:"mavlink"`
	Video     string   `json:"video"`
	LastError *string  `json:"lastError"`
}

func Stopped() Reported {
	return Reported{Task: Task{Status: "stopped"}, MAVLink: "disconnected", Video: "disconnected"}
}

// Begin is a controller transition. Its new identity fences all reports from older tasks.
func Begin(current Reported, taskID string) (Reported, error) {
	if taskID == "" {
		return Reported{}, errors.New("task identity is required")
	}
	if current.Task.ID != nil && *current.Task.ID == taskID && current.Task.Status != "stopped" {
		return current, nil
	}
	return Reported{Task: Task{Status: "starting", ID: &taskID}, MAVLink: "disconnected", Video: "disconnected"}, nil
}

func checkTask(current Reported, taskID string) error {
	if taskID == "" || current.Task.ID == nil || *current.Task.ID != taskID || current.Task.Status == "stopped" {
		return ErrStaleTask
	}
	return nil
}

// Stop and Fail clear the endpoint. A late transition from a superseded task is rejected.
func Stop(current Reported, taskID string) (Reported, error) {
	if err := checkTask(current, taskID); err != nil {
		return Reported{}, err
	}
	return Stopped(), nil
}

func Fail(current Reported, taskID, message string) (Reported, error) {
	if err := checkTask(current, taskID); err != nil {
		return Reported{}, err
	}
	if message == "" {
		return Reported{}, errors.New("failure message is required")
	}
	current.Task.Status = "error"
	current.Endpoint = Endpoint{}
	current.MAVLink = "disconnected"
	current.Video = "disconnected"
	current.LastError = &message
	return current, nil
}

func validConnection(state string) bool {
	switch state {
	case "disconnected", "connecting", "connected", "error":
		return true
	default:
		return false
	}
}

// Connection is an agent transition. Video changes never disturb a ready MAVLink endpoint.
func Connection(current Reported, taskID, channel, state string) (Reported, error) {
	if err := checkTask(current, taskID); err != nil {
		return Reported{}, err
	}
	if current.Task.Status == "error" || !validConnection(state) {
		return Reported{}, errors.New("invalid connection transition")
	}
	switch channel {
	case "mavlink":
		current.MAVLink = state
		if state != "connected" {
			current.Task.Status = "starting"
			current.Endpoint = Endpoint{}
		}
	case "video":
		current.Video = state
	default:
		return Reported{}, fmt.Errorf("unknown connection channel %q", channel)
	}
	return current, nil
}

// Ready may publish addresses only after the UDP socket and MAVLink channel work.
func Ready(current Reported, taskID, ipv4, ipv6 string, udpListening bool) (Reported, error) {
	if err := checkTask(current, taskID); err != nil {
		return Reported{}, err
	}
	if !udpListening || current.MAVLink != "connected" || current.Task.Status == "error" {
		return Reported{}, errors.New("UDP and MAVLink must be ready before publishing an endpoint")
	}
	if parsed := net.ParseIP(ipv4); parsed == nil || parsed.To4() == nil || !parsed.IsGlobalUnicast() || parsed.IsPrivate() {
		return Reported{}, errors.New("valid public IPv4 address is required")
	}
	if parsed := net.ParseIP(ipv6); parsed == nil || parsed.To4() != nil || !parsed.IsGlobalUnicast() || parsed.IsPrivate() {
		return Reported{}, errors.New("valid public IPv6 address is required")
	}
	port := UDPPort
	current.Task.Status = "ready"
	current.Endpoint = Endpoint{IPv4: &ipv4, IPv6: &ipv6, UDPPort: &port}
	current.LastError = nil
	return current, nil
}

// Store must implement version-conditional writes to the IoT named shadow.
// An unconditional write would allow a superseded task to restore its endpoint.
type Store interface {
	Read(context.Context) (Reported, int64, error)
	Write(context.Context, Reported, int64) error
}

// Update rechecks task identity after each version conflict before committing.
func Update(ctx context.Context, store Store, transition func(Reported) (Reported, error)) error {
	for attempt := 0; attempt < 3; attempt++ {
		current, version, err := store.Read(ctx)
		if err != nil {
			return err
		}
		next, err := transition(current)
		if err != nil {
			return err
		}
		err = store.Write(ctx, next, version)
		if !errors.Is(err, ErrVersionConflict) {
			return err
		}
	}
	return ErrVersionConflict
}
