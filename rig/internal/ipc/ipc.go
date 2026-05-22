package ipc

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
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

type Broker struct {
	socketPath string
	listener   net.Listener
	mu         sync.Mutex
	clients    map[*brokerClient]struct{}
	retained   map[string][]byte
}

type brokerClient struct {
	conn          net.Conn
	encoder       *json.Encoder
	subscriptions []string
	mu            sync.Mutex
}

func NewBroker(socketPath string) *Broker {
	return &Broker{
		socketPath: socketPath,
		clients:    map[*brokerClient]struct{}{},
		retained:   map[string][]byte{},
	}
}

func (b *Broker) Serve(ctx context.Context) error {
	if err := os.MkdirAll(filepath.Dir(b.socketPath), 0o755); err != nil {
		return err
	}
	if err := os.RemoveAll(b.socketPath); err != nil {
		return err
	}
	listener, err := net.Listen("unix", b.socketPath)
	if err != nil {
		return err
	}
	b.listener = listener
	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		client := &brokerClient{conn: conn, encoder: json.NewEncoder(conn)}
		b.mu.Lock()
		b.clients[client] = struct{}{}
		b.mu.Unlock()
		go b.handleClient(client)
	}
}

func (b *Broker) Publish(topic string, payload []byte, retain bool) {
	b.mu.Lock()
	if retain {
		b.retained[topic] = append([]byte(nil), payload...)
	}
	clients := make([]*brokerClient, 0, len(b.clients))
	for client := range b.clients {
		if client.matches(topic) {
			clients = append(clients, client)
		}
	}
	b.mu.Unlock()
	for _, client := range clients {
		if err := client.send(Frame{Type: "publish", Topic: topic, Payload: payload}); err != nil {
			b.removeClient(client)
		}
	}
}

func (b *Broker) handleClient(client *brokerClient) {
	defer b.removeClient(client)
	scanner := bufio.NewScanner(client.conn)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var frame Frame
		if err := json.Unmarshal(scanner.Bytes(), &frame); err != nil {
			return
		}
		switch frame.Type {
		case "subscribe":
			if frame.Topic == "" {
				return
			}
			b.subscribe(client, frame.Topic)
		case "publish":
			if frame.Topic == "" {
				return
			}
			b.Publish(frame.Topic, frame.Payload, false)
		case "publish-retained":
			if frame.Topic == "" {
				return
			}
			b.Publish(frame.Topic, frame.Payload, true)
		default:
			return
		}
	}
}

func (b *Broker) subscribe(client *brokerClient, filter string) {
	var retained []Frame
	b.mu.Lock()
	client.subscriptions = append(client.subscriptions, filter)
	for topic, payload := range b.retained {
		if topicMatches(filter, topic) {
			retained = append(retained, Frame{Type: "publish", Topic: topic, Payload: payload})
		}
	}
	b.mu.Unlock()
	for _, frame := range retained {
		if err := client.send(frame); err != nil {
			b.removeClient(client)
			return
		}
	}
}

func (b *Broker) removeClient(client *brokerClient) {
	_ = client.conn.Close()
	b.mu.Lock()
	delete(b.clients, client)
	b.mu.Unlock()
}

func (c *brokerClient) matches(topic string) bool {
	for _, filter := range c.subscriptions {
		if topicMatches(filter, topic) {
			return true
		}
	}
	return false
}

func (c *brokerClient) send(frame Frame) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.encoder.Encode(frame)
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

func topicMatches(filter string, topic string) bool {
	if filter == topic {
		return true
	}
	filterParts := strings.Split(filter, "/")
	topicParts := strings.Split(topic, "/")
	for index, filterPart := range filterParts {
		if filterPart == "#" {
			return index == len(filterParts)-1
		}
		if index >= len(topicParts) {
			return false
		}
		if filterPart != "+" && filterPart != topicParts[index] {
			return false
		}
	}
	return len(filterParts) == len(topicParts)
}
