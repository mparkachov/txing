// Video runtime state copied from
// devices/unit/daemon/internal/daemon/runtime.go. In the mac daemon the
// video capability stays not-ready until a KVS worker reports READY over
// the BoardVideoBridge (worker supervision arrives with the video task).
package action

import "strings"

const defaultBoardVideoWorkerErrorDetail = "board video worker reported an error"

type VideoRuntimeState struct {
	Available       bool
	Ready           bool
	Status          string
	ViewerConnected bool
	LastError       *string
	UpdatedAtMS     uint64
}

func VideoRuntimeStarting(observedAtMS uint64) VideoRuntimeState {
	return VideoRuntimeState{Available: true, Ready: false, Status: VideoStatusStarting, UpdatedAtMS: observedAtMS}
}

func VideoRuntimeUnavailable(observedAtMS uint64) VideoRuntimeState {
	return VideoRuntimeState{Available: false, Ready: false, Status: VideoStatusUnavailable, UpdatedAtMS: observedAtMS}
}

type VideoWorkerEventKind string

const (
	VideoWorkerStarting             VideoWorkerEventKind = "starting"
	VideoWorkerReady                VideoWorkerEventKind = "ready"
	VideoWorkerViewerConnected      VideoWorkerEventKind = "viewer-connected"
	VideoWorkerMCPDataChannelOpen   VideoWorkerEventKind = "mcp-open"
	VideoWorkerMCPDataChannelClosed VideoWorkerEventKind = "mcp-closed"
	VideoWorkerMCPDataChannelError  VideoWorkerEventKind = "mcp-error"
	VideoWorkerError                VideoWorkerEventKind = "error"
)

type VideoWorkerEvent struct {
	Kind          VideoWorkerEventKind
	WorkerVersion string
	Connected     bool
	SessionID     string
	Reason        string
	Detail        string
}

func (s *VideoRuntimeState) ApplyEvent(event VideoWorkerEvent, observedAtMS uint64) {
	switch event.Kind {
	case VideoWorkerStarting:
		*s = VideoRuntimeStarting(observedAtMS)
	case VideoWorkerReady:
		s.Available = true
		s.Ready = true
		s.Status = VideoStatusReady
		s.LastError = nil
		s.UpdatedAtMS = observedAtMS
	case VideoWorkerViewerConnected:
		s.ViewerConnected = event.Connected
		s.UpdatedAtMS = observedAtMS
	case VideoWorkerError:
		detail := event.Detail
		if strings.TrimSpace(detail) == "" {
			detail = defaultBoardVideoWorkerErrorDetail
		}
		s.Available = true
		s.Ready = false
		s.Status = VideoStatusError
		s.LastError = &detail
		s.UpdatedAtMS = observedAtMS
	default:
		s.UpdatedAtMS = observedAtMS
	}
}
