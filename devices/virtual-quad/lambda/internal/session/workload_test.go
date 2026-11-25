package session

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestWorkloadHealthRequiresFreshEvidence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "health.json")
	w := Workload{health: path}
	now := time.Unix(1700000000, 0)
	clock := func() time.Time { return now }
	if got := w.readHealth(clock); got != (Health{}) {
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
	if got := w.readHealth(clock); got != (Health{true, true, true, true}) {
		t.Fatalf("fresh health: %+v", got)
	}
	write(now.Add(-3 * time.Second).UnixMilli())
	if got := w.readHealth(clock); got != (Health{}) {
		t.Fatalf("stale health: %+v", got)
	}
	write(now.Add(time.Second).UnixMilli())
	if got := w.readHealth(clock); got != (Health{}) {
		t.Fatalf("future health: %+v", got)
	}
}

func TestWorkloadHealthAcceptsSampleWrittenDuringRead(t *testing.T) {
	path := filepath.Join(t.TempDir(), "health.fifo")
	if err := syscall.Mkfifo(path, 0600); err != nil {
		t.Fatal(err)
	}
	written := make(chan error, 1)
	go func() {
		f, err := os.OpenFile(path, os.O_WRONLY, 0)
		if err != nil {
			written <- err
			return
		}
		time.Sleep(25 * time.Millisecond)
		_, err = fmt.Fprintf(f, `{"observedAtMs":%d,"heartbeat":true,"navigation":true,"mavlink":true,"video":true}`, time.Now().UnixMilli())
		if closeErr := f.Close(); err == nil {
			err = closeErr
		}
		written <- err
	}()
	got := (&Workload{health: path}).Health()
	if err := <-written; err != nil {
		t.Fatal(err)
	}
	if got != (Health{true, true, true, true}) {
		t.Fatalf("fresh sample written during read rejected: %+v", got)
	}
}
