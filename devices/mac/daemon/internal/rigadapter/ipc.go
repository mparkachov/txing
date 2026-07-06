// Copied client subset of rig/internal/ipc/ipc.go. The rig
// txing-sparkplug-manager owns the broker side of this contract:
// newline-delimited JSON frames over a Unix domain socket with
// MQTT-style topic filters and retained messages.
package rigadapter

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"sync"
	"time"
)

type Message struct {
	Topic   string
	Payload []byte
}

type Frame struct {
	Type    string `json:"type"`
	Topic   string `json:"topic,omitempty"`
	Payload []byte `json:"payload,omitempty"`
}

type Client struct {
	conn    net.Conn
	encoder *json.Encoder
	scanner *bufio.Scanner
	mu      sync.Mutex
}

func Dial(ctx context.Context, socketPath string) (*Client, error) {
	var lastErr error
	deadline, hasDeadline := ctx.Deadline()
	for {
		dialer := net.Dialer{}
		conn, err := dialer.DialContext(ctx, "unix", socketPath)
		if err == nil {
			scanner := bufio.NewScanner(conn)
			scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
			return &Client{conn: conn, encoder: json.NewEncoder(conn), scanner: scanner}, nil
		}
		lastErr = err
		if hasDeadline && time.Until(deadline) <= 0 {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(500 * time.Millisecond):
		}
	}
	return nil, lastErr
}

func (c *Client) Close() error {
	return c.conn.Close()
}

func (c *Client) Subscribe(filter string) error {
	return c.send(Frame{Type: "subscribe", Topic: filter})
}

func (c *Client) Publish(topic string, payload []byte) error {
	return c.send(Frame{Type: "publish", Topic: topic, Payload: payload})
}

func (c *Client) PublishRetained(topic string, payload []byte) error {
	return c.send(Frame{Type: "publish-retained", Topic: topic, Payload: payload})
}

func (c *Client) Receive() (Message, error) {
	if !c.scanner.Scan() {
		if err := c.scanner.Err(); err != nil {
			return Message{}, err
		}
		return Message{}, errors.New("IPC connection closed")
	}
	var frame Frame
	if err := json.Unmarshal(c.scanner.Bytes(), &frame); err != nil {
		return Message{}, err
	}
	if frame.Type != "publish" {
		return Message{}, fmt.Errorf("unexpected IPC frame type %q", frame.Type)
	}
	return Message{Topic: frame.Topic, Payload: frame.Payload}, nil
}

func (c *Client) send(frame Frame) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.encoder.Encode(frame)
}
