package companion

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
)

const MaxIPC = 64 * 1024

// IPC is type byte + big-endian uint32 size + payload. Credentials use four
// NUL-separated fields and travel only over the anonymous parent/child pipe.
func readPacket(reader io.Reader) (Event, error) {
	var header [5]byte
	if _, err := io.ReadFull(reader, header[:]); err != nil {
		return Event{}, err
	}
	n := binary.BigEndian.Uint32(header[1:])
	if n > MaxIPC {
		return Event{}, errors.New("viewer IPC packet exceeds limit")
	}
	e := Event{Kind: header[0], Payload: make([]byte, n)}
	_, err := io.ReadFull(reader, e.Payload)
	return e, err
}
func writePacket(writer io.Writer, e Event) error {
	if len(e.Payload) > MaxIPC {
		return errors.New("viewer IPC packet exceeds limit")
	}
	var header [5]byte
	header[0] = e.Kind
	binary.BigEndian.PutUint32(header[1:], uint32(len(e.Payload)))
	for _, data := range [][]byte{header[:], e.Payload} {
		for len(data) > 0 {
			n, err := writer.Write(data)
			if err != nil {
				return err
			}
			if n == 0 {
				return io.ErrShortWrite
			}
			data = data[n:]
		}
	}
	return nil
}

type ProcessFactory struct {
	Path, Thing, ID, Region, CA string
	Credentials                 aws.CredentialsProvider
	// Tests can accelerate refresh without changing the production cadence.
	refreshEvery time.Duration
}

func (f *ProcessFactory) Start(ctx context.Context, channel string) (Session, error) {
	if channel != "mavlink" && channel != "video" {
		return nil, errors.New("unknown viewer channel")
	}
	suffix := "-mavlink"
	if channel == "video" {
		suffix = "-board-video"
	}
	childCtx, cancel := context.WithCancel(ctx)
	cmd := exec.CommandContext(childCtx, f.Path, channel, f.Thing+suffix, f.Region, "agent-"+f.ID, f.CA)
	// SDK diagnostics are deliberately suppressed: only sanitized IPC errors are
	// forwarded. Credential-bearing SDK request bodies never enter task logs.
	cmd.Stderr = io.Discard
	in, err := cmd.StdinPipe()
	if err != nil {
		cancel()
		return nil, err
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		_ = in.Close()
		cancel()
		return nil, err
	}
	if err = cmd.Start(); err != nil {
		_ = in.Close()
		cancel()
		return nil, err
	}
	p := &process{cmd: cmd, in: in, out: out, cancel: cancel, events: make(chan Event, 64), writes: make(chan writeRequest, 16), done: make(chan struct{})}
	p.readWG.Add(1)
	go p.read()
	go p.write(childCtx)
	go func() { p.readWG.Wait(); _ = cmd.Wait(); cancel(); _ = in.Close(); close(p.done) }()
	go p.refresh(childCtx, f.Credentials, f.refreshEvery)
	return p, nil
}

type writeRequest struct {
	event Event
	done  chan error
	ctx   context.Context
}
type process struct {
	cmd    *exec.Cmd
	in     io.WriteCloser
	out    io.ReadCloser
	cancel context.CancelFunc
	events chan Event
	writes chan writeRequest
	done   chan struct{}
	once   sync.Once
	readWG sync.WaitGroup
}

func (p *process) Events() <-chan Event { return p.events }
func (p *process) Send(ctx context.Context, kind byte, payload []byte) error {
	if len(payload) > MaxIPC {
		return errors.New("viewer IPC packet exceeds limit")
	}
	// Caller may reuse its frame as soon as Send returns.
	req := writeRequest{Event{kind, append([]byte(nil), payload...)}, make(chan error, 1), ctx}
	select {
	case p.writes <- req:
	case <-ctx.Done():
		return ctx.Err()
	case <-p.done:
		return errors.New("viewer exited")
	}
	select {
	case err := <-req.done:
		return err
	case <-ctx.Done():
		p.cancel()
		return ctx.Err()
	case <-p.done:
		return errors.New("viewer exited")
	}
}
func (p *process) read() {
	defer p.readWG.Done()
	defer close(p.events)
	for {
		e, err := readPacket(p.out)
		if err != nil {
			return
		}
		if e.Kind != 'S' && e.Kind != 'B' && e.Kind != 'J' && e.Kind != 'E' {
			p.cancel()
			return
		}
		select {
		case p.events <- e:
		default:
			p.cancel()
			return
		}
	}
}
func (p *process) write(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case req := <-p.writes:
			err := req.ctx.Err()
			if err == nil {
				err = writePacket(p.in, req.event)
			}
			if req.event.Kind == 'C' {
				clear(req.event.Payload)
			}
			req.done <- err
			if err != nil {
				p.cancel()
				return
			}
		}
	}
}
func credentialPacket(c aws.Credentials) ([]byte, error) {
	if c.AccessKeyID == "" || c.SecretAccessKey == "" || c.SessionToken == "" || !c.CanExpire || !c.Expires.After(time.Now().Add(time.Minute)) {
		return nil, errors.New("fresh temporary task credentials are required")
	}
	for _, field := range []string{c.AccessKeyID, c.SecretAccessKey, c.SessionToken} {
		if strings.ContainsRune(field, 0) {
			return nil, errors.New("invalid task credentials")
		}
	}
	return []byte(strings.Join([]string{c.AccessKeyID, c.SecretAccessKey, c.SessionToken, strconv.FormatInt(c.Expires.Unix(), 10)}, "\x00")), nil
}
func (p *process) refresh(ctx context.Context, provider aws.CredentialsProvider, interval time.Duration) {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	tick := time.NewTicker(interval)
	defer tick.Stop()
	var validUntil time.Time
	for {
		call, cc := context.WithTimeout(ctx, 4*time.Second)
		c, err := provider.Retrieve(call)
		cc()
		if err == nil {
			var payload []byte
			payload, err = credentialPacket(c)
			if err == nil {
				call, cc = context.WithTimeout(ctx, 2*time.Second)
				err = p.Send(call, 'C', payload)
				cc()
				clear(payload)
				if err != nil {
					return
				}
				validUntil = c.Expires
			}
		}
		// A transient credential endpoint failure does not reset a healthy peer.
		if err != nil && !validUntil.After(time.Now().Add(time.Minute)) {
			p.cancel()
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
	}
}
func (p *process) Close() error {
	p.once.Do(func() { p.cancel(); _ = p.in.Close() })
	select {
	case <-p.done:
		return nil
	case <-time.After(5 * time.Second):
		_ = p.cmd.Process.Kill()
		return errors.New("native viewer shutdown timed out")
	}
}
