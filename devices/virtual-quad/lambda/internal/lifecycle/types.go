package lifecycle

import (
	"errors"
	"regexp"
)

var (
	ErrInvalidRequest = errors.New("invalid virtual quad lifecycle request")
	ErrStaleTarget    = errors.New("virtual quad command targets a stale generation")
	ErrRigAsleep      = errors.New("virtual quad rig is asleep")
)
var requestIDPattern = regexp.MustCompile(`(?i)^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$`)

func ValidRequestID(id string) bool { return requestIDPattern.MatchString(id) }

type Assignment struct{ DeviceID, TownID, RigID string }
type CommandRequest struct {
	ID       string
	Sequence uint32
}
type Status string
type Receipt struct {
	RequestID string
	Sequence  uint32
	REDCON    uint8
	Status    Status
	Reason    string
}
type Projection struct {
	TimestampMS           int64
	SessionID             string
	REDCON                uint8
	Simulation            *bool
	Mavlink, Video, Agent bool
	Receipt               Receipt
}
