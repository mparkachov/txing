package companion

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
)

func TestIPCFramesAndLimits(t *testing.T) {
	var stream bytes.Buffer
	frames := []Event{{'B', []byte{0xfd, 0, 1, 0, 42, 1, 1, 0x12, 0x34, 0x56, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}}, {'J', []byte(`{"op":"control.status"}`)}}
	for _, frame := range frames {
		if err := writePacket(&stream, frame); err != nil {
			t.Fatal(err)
		}
	}
	for _, want := range frames {
		got, err := readPacket(&stream)
		if err != nil || got.Kind != want.Kind || !bytes.Equal(got.Payload, want.Payload) {
			t.Fatal("IPC altered message boundaries or bytes", err)
		}
	}
	if _, err := readPacket(bytes.NewReader([]byte{'B', 0, 1, 0, 1})); err == nil {
		t.Fatal("oversize packet accepted")
	}
	if err := writePacket(&stream, Event{'B', make([]byte, MaxIPC+1)}); err == nil {
		t.Fatal("oversize send accepted")
	}
	if _, err := readPacket(bytes.NewReader([]byte{'B', 0, 0, 0, 3, 1})); !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Fatal("truncated message accepted", err)
	}
}
func TestTaskCredentialPacket(t *testing.T) {
	c := aws.Credentials{AccessKeyID: "test", SecretAccessKey: "test-secret", SessionToken: "test-token", CanExpire: true, Expires: time.Now().Add(time.Hour)}
	if data, err := credentialPacket(c); err != nil || bytes.Count(data, []byte{0}) != 3 {
		t.Fatal("temporary credential IPC", err)
	}
	for _, mutate := range []func(*aws.Credentials){func(c *aws.Credentials) { c.CanExpire = false }, func(c *aws.Credentials) { c.SessionToken = "" }, func(c *aws.Credentials) { c.Expires = time.Now() }, func(c *aws.Credentials) { c.SecretAccessKey = "invalid\x00secret" }} {
		bad := c
		mutate(&bad)
		if _, err := credentialPacket(bad); err == nil {
			t.Fatal("invalid credentials accepted")
		}
	}
}

// This helper exercises the actual process supervisor and pipes. Actual WebRTC
// behavior is validated separately by the pinned SDK's real peer CTest.
func TestWorkerHelper(t *testing.T) {
	if os.Getenv("TXING_TEST_VIEWER_HELPER") != "1" {
		return
	}
	e, err := readPacket(os.Stdin)
	if err != nil || e.Kind != 'C' {
		os.Exit(2)
	}
	if err = writePacket(os.Stdout, Event{'S', []byte("connected")}); err != nil {
		os.Exit(3)
	}
	for {
		e, err = readPacket(os.Stdin)
		if err != nil {
			os.Exit(0)
		}
		if e.Kind == 'J' || e.Kind == 'B' {
			if writePacket(os.Stdout, e) != nil {
				os.Exit(4)
			}
		} else if e.Kind == 'C' {
			// Return only the synthetic key identifier, never secret/token fields.
			key := strings.SplitN(string(e.Payload), "\x00", 2)[0]
			if writePacket(os.Stdout, Event{'J', []byte("refreshed:" + key)}) != nil {
				os.Exit(5)
			}
		}
	}
}

func TestCredentialRefreshPreservesLiveProcessAcrossTransientFailure(t *testing.T) {
	t.Setenv("TXING_TEST_VIEWER_HELPER", "1")
	bin, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	script := filepath.Join(t.TempDir(), "viewer")
	if err = os.WriteFile(script, []byte("#!/bin/sh\nexec '"+bin+"' -test.run=TestWorkerHelper -- \"$@\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	provider := aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
		call := calls.Add(1)
		if call == 2 {
			return aws.Credentials{}, errors.New("synthetic task-role endpoint outage")
		}
		key := "key-before-rotation"
		if call >= 3 {
			key = "key-after-rotation"
		}
		return aws.Credentials{AccessKeyID: key, SecretAccessKey: "test-secret", SessionToken: "test-token", CanExpire: true, Expires: time.Now().Add(time.Hour)}, nil
	})
	factory := ProcessFactory{Path: script, Thing: testThing, ID: testID, Region: "eu-central-1", CA: "anchor.pem", Credentials: provider, refreshEvery: 5 * time.Millisecond}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	session, err := factory.Start(ctx, "mavlink")
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	select {
	case event := <-session.Events():
		if event.Kind != 'S' || string(event.Payload) != "connected" {
			t.Fatal("worker did not connect before refresh")
		}
	case <-ctx.Done():
		t.Fatal("worker did not start")
	}
	for {
		select {
		case event, open := <-session.Events():
			if !open || event.Kind != 'J' {
				t.Fatal("credential refresh reset the live worker")
			}
			if string(event.Payload) == "refreshed:key-after-rotation" {
				if calls.Load() < 3 {
					t.Fatal("transient failure was not exercised")
				}
				frame := []byte{0xfd, 1, 0, 1}
				if err := session.Send(ctx, 'B', frame); err != nil {
					t.Fatal("rotated worker could not use its existing pipe", err)
				}
				for {
					select {
					case echoed, open := <-session.Events():
						if !open {
							t.Fatal("worker exited after rotation")
						}
						if echoed.Kind == 'B' {
							if !bytes.Equal(echoed.Payload, frame) {
								t.Fatal("rotation changed frame bytes")
							}
							return
						}
					case <-ctx.Done():
						t.Fatal("existing pipe stopped working after rotation")
					}
				}
			}
		case <-ctx.Done():
			t.Fatal("task credentials did not rotate")
		}
	}
}
func TestProcessPipeAndBoundedShutdown(t *testing.T) {
	t.Setenv("TXING_TEST_VIEWER_HELPER", "1")
	bin, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	script := filepath.Join(t.TempDir(), "viewer")
	if err = os.WriteFile(script, []byte("#!/bin/sh\nexec '"+bin+"' -test.run=TestWorkerHelper -- \"$@\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	creds := aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
		return aws.Credentials{AccessKeyID: "test", SecretAccessKey: "test-secret", SessionToken: "test-session", CanExpire: true, Expires: time.Now().Add(time.Hour)}, nil
	})
	factory := ProcessFactory{Path: script, Thing: testThing, ID: testID, Region: "eu-central-1", CA: "anchor.pem", Credentials: creds}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	session, err := factory.Start(ctx, "mavlink")
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	select {
	case e := <-session.Events():
		if e.Kind != 'S' || string(e.Payload) != "connected" {
			t.Fatal("worker did not open")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("worker pipe startup hung")
	}
	payload := []byte{0xfd, 1, 0, 1}
	call, cc := context.WithTimeout(ctx, time.Second)
	defer cc()
	if err = session.Send(call, 'B', payload); err != nil {
		t.Fatal(err)
	}
	select {
	case e := <-session.Events():
		if !bytes.Equal(e.Payload, payload) {
			t.Fatal("process IPC changed bytes")
		}
	case <-time.After(time.Second):
		t.Fatal("worker pipe receive hung")
	}
	before := time.Now()
	if err = session.Close(); err != nil {
		t.Fatal(err)
	}
	if time.Since(before) > time.Second {
		t.Fatal("worker did not exit promptly")
	}
}
