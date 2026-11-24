package qualification

import (
	"context"
	"strings"
	"testing"
)

func TestRejectsInvalidDurationBeforeStartingSupervisor(t *testing.T) {
	t.Setenv("LAMBDA_TASK_ROOT", t.TempDir())
	for _, duration := range []int{-1, 119, 721} {
		_, err := Handle(context.Background(), struct {
			DurationSeconds int `json:"durationSeconds"`
		}{DurationSeconds: duration})
		if err == nil || !strings.Contains(err.Error(), "durationSeconds") {
			t.Fatalf("duration %d: got %v", duration, err)
		}
	}
}

func TestRejectsIncompleteChannelAssignment(t *testing.T) {
	t.Setenv("LAMBDA_TASK_ROOT", t.TempDir())
	t.Setenv("QUAD_VIDEO_CHANNEL", "qualification-video")
	t.Setenv("QUAD_MAVLINK_CHANNEL", "")
	_, err := Handle(context.Background(), struct {
		DurationSeconds int `json:"durationSeconds"`
	}{})
	if err == nil || !strings.Contains(err.Error(), "both qualification channel names") {
		t.Fatalf("got %v", err)
	}
}
