package session

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	"github.com/eclipse/paho.golang/autopaho"
	"github.com/eclipse/paho.golang/paho"
	"github.com/gorilla/websocket"
)

type Notification int

const (
	Subscribed Notification = iota + 1
	Updated
	RigUpdated
	Disconnected
)

// Notifications is scoped to a single invocation. Every subscription,
// including a reconnection, is followed by an authoritative shadow read by
// the caller; MQTT payloads are only wakeups and are never treated as state.
type Notifications struct {
	Events <-chan Notification
	cancel context.CancelFunc
}

func (n Notifications) Close() { n.cancel() }

func Subscribe(ctx context.Context, cfg aws.Config, endpoint, device, rig, owner string) (Notifications, error) {
	if endpoint == "" || strings.ContainsAny(endpoint, "/?#:@") || device == "" || rig == "" || owner == "" {
		return Notifications{}, fmt.Errorf("invalid MQTT endpoint or client identity")
	}
	broker, err := url.Parse("wss://" + endpoint + "/mqtt")
	if err != nil {
		return Notifications{}, err
	}
	ctx, cancel := context.WithCancel(ctx)
	events := make(chan Notification, 32)
	push := func(event Notification) {
		select {
		case events <- event:
		default:
		}
	}
	// Unlike shadow wakeups, connection transitions must not be dropped when
	// the queue is full: the owner must stop renewing readiness on disconnect.
	pushConnection := func(event Notification) {
		select {
		case events <- event:
		case <-ctx.Done():
		}
	}
	topic := "$aws/things/" + device + "/shadow/name/simulation/update/documents"
	rigTopic := "$aws/things/" + rig + "/shadow/name/sparkplug/update/documents"
	options := autopaho.ClientConfig{
		ServerUrls: []*url.URL{broker}, KeepAlive: 30, CleanStartOnInitialConnection: true,
		ConnectTimeout:   8 * time.Second,
		ReconnectBackoff: func(int) time.Duration { return time.Second },
		AttemptConnection: func(ctx context.Context, _ autopaho.ClientConfig, broker *url.URL) (net.Conn, error) {
			signed, err := signedMQTTURL(ctx, cfg, broker.Host, time.Now())
			if err != nil {
				return nil, err
			}
			dialer := *websocket.DefaultDialer
			dialer.Subprotocols = []string{"mqtt"}
			conn, _, err := dialer.DialContext(ctx, signed, nil)
			if err != nil {
				return nil, fmt.Errorf("connect MQTT websocket: %w", err)
			}
			return &mqttSocket{Conn: conn}, nil
		},
		OnConnectionUp: func(cm *autopaho.ConnectionManager, _ *paho.Connack) {
			go func() {
				ack, err := cm.Subscribe(ctx, &paho.Subscribe{Subscriptions: []paho.SubscribeOptions{{Topic: topic, QoS: 1}, {Topic: rigTopic, QoS: 1}}})
				if err != nil || ack == nil || len(ack.Reasons) != 2 || ack.Reasons[0] >= 0x80 || ack.Reasons[1] >= 0x80 {
					pushConnection(Disconnected)
					return
				}
				pushConnection(Subscribed)
			}()
		},
		OnConnectionDown: func() bool { pushConnection(Disconnected); return true },
		ClientConfig: paho.ClientConfig{
			ClientID: "quad-" + owner,
			OnPublishReceived: []func(paho.PublishReceived) (bool, error){func(p paho.PublishReceived) (bool, error) {
				if p.Packet.Topic == rigTopic {
					push(RigUpdated)
				} else {
					push(Updated)
				}
				return true, nil
			}},
		},
	}
	if _, err := autopaho.NewConnection(ctx, options); err != nil {
		cancel()
		return Notifications{}, err
	}
	return Notifications{Events: events, cancel: cancel}, nil
}

func signedMQTTURL(ctx context.Context, cfg aws.Config, endpoint string, now time.Time) (string, error) {
	creds, err := cfg.Credentials.Retrieve(ctx)
	if err != nil {
		return "", fmt.Errorf("retrieve MQTT credentials: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://"+endpoint+"/mqtt?X-Amz-Expires=300", nil)
	if err != nil {
		return "", err
	}
	const emptySHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	// IoT Core requires the STS token to be appended after signing, unlike
	// most AWS services where it participates in the canonical query.
	token := creds.SessionToken
	creds.SessionToken = ""
	signed, _, err := v4.NewSigner().PresignHTTP(ctx, creds, req, emptySHA256, "iotdevicegateway", cfg.Region, now)
	if err != nil {
		return "", fmt.Errorf("sign MQTT websocket: %w", err)
	}
	if token != "" {
		signed += "&X-Amz-Security-Token=" + url.QueryEscape(token)
	}
	return "wss://" + strings.TrimPrefix(signed, "https://"), nil
}

// mqttSocket adapts message-framed websocket reads to the stream interface
// required by Paho. The locks serialize websocket readers and writers.
type mqttSocket struct {
	*websocket.Conn
	reader  io.Reader
	readMu  sync.Mutex
	writeMu sync.Mutex
}

func (c *mqttSocket) Read(p []byte) (int, error) {
	c.readMu.Lock()
	defer c.readMu.Unlock()
	for {
		if c.reader == nil {
			_, r, err := c.NextReader()
			if err != nil {
				return 0, err
			}
			c.reader = r
		}
		n, err := c.reader.Read(p)
		if err == io.EOF {
			c.reader = nil
			if n > 0 {
				return n, nil
			}
			continue
		}
		return n, err
	}
}

func (c *mqttSocket) Write(p []byte) (int, error) {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	if err := c.WriteMessage(websocket.BinaryMessage, p); err != nil {
		return 0, err
	}
	return len(p), nil
}

func (c *mqttSocket) SetDeadline(t time.Time) error {
	if err := c.SetReadDeadline(t); err != nil {
		return err
	}
	return c.SetWriteDeadline(t)
}
