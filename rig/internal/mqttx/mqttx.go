package mqttx

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net/url"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/eclipse/paho.golang/autopaho"
	"github.com/eclipse/paho.golang/paho"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
)

type Message struct {
	Topic   string
	Payload []byte
}

type Client struct {
	config        autopaho.ClientConfig
	manager       *autopaho.ConnectionManager
	cancel        context.CancelFunc
	mu            sync.RWMutex
	onMessage     func(Message)
	subscriptions map[string]func(Message)
}

type Options struct {
	Config           rigconfig.Config
	ClientID         string
	WillTopic        string
	WillPayload      []byte
	OnMessage        func(Message)
	OnConnection     func()
	OnConnectionLost func(error)
}

func New(options Options) (*Client, error) {
	tlsConfig, err := TLSConfig(options.Config)
	if err != nil {
		return nil, err
	}
	brokerURL, err := BrokerURL(options.Config.IoTEndpoint)
	if err != nil {
		return nil, err
	}

	client := &Client{
		onMessage:     options.OnMessage,
		subscriptions: map[string]func(Message){},
	}
	client.config = newClientConfig(options, brokerURL, tlsConfig, client)
	return client, nil
}

func newClientConfig(options Options, brokerURL *url.URL, tlsConfig *tls.Config, client *Client) autopaho.ClientConfig {
	config := autopaho.ClientConfig{
		ServerUrls:                    []*url.URL{brokerURL},
		TlsCfg:                        tlsConfig,
		KeepAlive:                     60,
		CleanStartOnInitialConnection: true,
		SessionExpiryInterval:         0,
		ReconnectBackoff:              autopaho.NewConstantBackoff(2 * time.Second),
		ConnectTimeout:                30 * time.Second,
		OnConnectionUp: func(_ *autopaho.ConnectionManager, _ *paho.Connack) {
			if options.OnConnection != nil {
				go options.OnConnection()
			}
		},
		OnConnectionDown: func() bool {
			if options.OnConnectionLost != nil {
				go options.OnConnectionLost(errors.New("MQTT connection down"))
			}
			return true
		},
		ClientConfig: paho.ClientConfig{
			ClientID: options.ClientID,
			OnPublishReceived: []func(paho.PublishReceived) (bool, error){
				client.handlePublish,
			},
		},
	}
	if options.WillTopic != "" {
		config.WillMessage = &paho.WillMessage{
			Topic:   options.WillTopic,
			Payload: append([]byte(nil), options.WillPayload...),
			QoS:     1,
			Retain:  false,
		}
	}
	return config
}

func (c *Client) Connect() error {
	c.mu.Lock()
	manager := c.manager
	if manager == nil {
		ctx, cancel := context.WithCancel(context.Background())
		var err error
		manager, err = autopaho.NewConnection(ctx, c.config)
		if err != nil {
			cancel()
			c.mu.Unlock()
			return err
		}
		c.manager = manager
		c.cancel = cancel
	}
	c.mu.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := manager.AwaitConnection(ctx); err != nil {
		c.Disconnect(0)
		return fmt.Errorf("MQTT connect timed out: %w", err)
	}
	return nil
}

func (c *Client) Disconnect(quiesce uint) {
	c.mu.Lock()
	manager := c.manager
	cancel := c.cancel
	c.manager = nil
	c.cancel = nil
	c.mu.Unlock()

	if manager != nil {
		timeout := time.Duration(quiesce) * time.Millisecond
		if timeout <= 0 {
			timeout = 5 * time.Second
		}
		ctx, stop := context.WithTimeout(context.Background(), timeout)
		_ = manager.Disconnect(ctx)
		stop()
	}
	if cancel != nil {
		cancel()
	}
}

func (c *Client) Subscribe(filter string, handler func(Message)) error {
	if handler != nil {
		c.mu.Lock()
		c.subscriptions[filter] = handler
		c.mu.Unlock()
	}

	manager, err := c.connection()
	if err != nil {
		if handler != nil {
			c.mu.Lock()
			delete(c.subscriptions, filter)
			c.mu.Unlock()
		}
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_, err = manager.Subscribe(ctx, &paho.Subscribe{
		Subscriptions: []paho.SubscribeOptions{
			{Topic: filter, QoS: 1},
		},
	})
	if err != nil && handler != nil {
		c.mu.Lock()
		delete(c.subscriptions, filter)
		c.mu.Unlock()
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return fmt.Errorf("MQTT subscribe %s timed out: %w", filter, err)
	}
	return err
}

func (c *Client) Unsubscribe(filter string) error {
	c.mu.Lock()
	delete(c.subscriptions, filter)
	c.mu.Unlock()

	manager, err := c.connection()
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_, err = manager.Unsubscribe(ctx, &paho.Unsubscribe{
		Topics: []string{filter},
	})
	if errors.Is(err, context.DeadlineExceeded) {
		return fmt.Errorf("MQTT unsubscribe %s timed out: %w", filter, err)
	}
	return err
}

func (c *Client) Publish(topic string, payload []byte, retained bool) error {
	manager, err := c.connection()
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_, err = manager.Publish(ctx, &paho.Publish{
		Topic:   topic,
		Payload: append([]byte(nil), payload...),
		QoS:     1,
		Retain:  retained,
	})
	if errors.Is(err, context.DeadlineExceeded) {
		return fmt.Errorf("MQTT publish %s timed out: %w", topic, err)
	}
	return err
}

func (c *Client) connection() (*autopaho.ConnectionManager, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.manager == nil {
		return nil, errors.New("MQTT client is not connected")
	}
	return c.manager, nil
}

func (c *Client) handlePublish(received paho.PublishReceived) (bool, error) {
	if received.Packet == nil {
		return false, nil
	}
	message := Message{
		Topic:   received.Packet.Topic,
		Payload: append([]byte(nil), received.Packet.Payload...),
	}
	if handler := c.handlerFor(message.Topic); handler != nil {
		handler(message)
		return true, nil
	}
	if c.onMessage != nil {
		c.onMessage(message)
		return true, nil
	}
	return false, nil
}

func (c *Client) handlerFor(topic string) func(Message) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	filters := make([]string, 0, len(c.subscriptions))
	for filter := range c.subscriptions {
		filters = append(filters, filter)
	}
	sort.Slice(filters, func(i, j int) bool {
		return topicFilterSpecificity(filters[i]) > topicFilterSpecificity(filters[j])
	})
	for _, filter := range filters {
		if topicMatches(filter, topic) {
			return c.subscriptions[filter]
		}
	}
	return nil
}

func BrokerURL(endpoint string) (*url.URL, error) {
	if !strings.Contains(endpoint, ":") {
		endpoint += ":8883"
	}
	brokerURL, err := url.Parse("tls://" + endpoint)
	if err != nil {
		return nil, fmt.Errorf("parse MQTT endpoint %s: %w", endpoint, err)
	}
	return brokerURL, nil
}

func topicFilterSpecificity(filter string) int {
	score := 0
	for _, part := range strings.Split(filter, "/") {
		if part != "+" && part != "#" {
			score += len(part) + 1
		}
	}
	return score
}

func topicMatches(filter, topic string) bool {
	filterParts := strings.Split(filter, "/")
	topicParts := strings.Split(topic, "/")
	for i, filterPart := range filterParts {
		if filterPart == "#" {
			return i == len(filterParts)-1
		}
		if i >= len(topicParts) {
			return false
		}
		if filterPart != "+" && filterPart != topicParts[i] {
			return false
		}
	}
	return len(topicParts) == len(filterParts)
}

func TLSConfig(cfg rigconfig.Config) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(cfg.CertificateFile, cfg.PrivateKeyFile)
	if err != nil {
		return nil, err
	}
	rootCA, err := os.ReadFile(cfg.RootCAFile)
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(rootCA) {
		return nil, fmt.Errorf("parse root CA file %s", cfg.RootCAFile)
	}
	return &tls.Config{
		MinVersion:   tls.VersionTLS12,
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
	}, nil
}
