package session

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWorkloadHealthRequiresFreshEvidence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "health.json")
	w := Workload{health: path}
	now := time.Unix(1700000000, 0)
	if got := w.Health(now); got != (Health{}) {
		t.Fatalf("missing health: %+v", got)
	}
	write := func(at int64) {
		t.Helper()
		data := fmt.Sprintf(`{"observedAtMs":%d,"heartbeat":true,"navigation":true,"mavlink":true,"video":true}`, at)
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	write(now.UnixMilli())
	if got := w.Health(now); got != (Health{true, true, true, true}) {
		t.Fatalf("fresh health: %+v", got)
	}
	write(now.Add(-3 * time.Second).UnixMilli())
	if got := w.Health(now); got != (Health{}) {
		t.Fatalf("stale health: %+v", got)
	}
	write(now.Add(time.Second).UnixMilli())
	if got := w.Health(now); got != (Health{}) {
		t.Fatalf("future health: %+v", got)
	}
}
