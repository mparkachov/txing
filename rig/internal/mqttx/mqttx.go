package mqttx

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"os"
	"strings"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
)

type Message struct {
	Topic   string
	Payload []byte
}

type Client struct {
	client mqtt.Client
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
	endpoint := options.Config.IoTEndpoint
	if !strings.Contains(endpoint, ":") {
		endpoint += ":8883"
	}
	clientOptions := mqtt.NewClientOptions().
		AddBroker("ssl://" + endpoint).
		SetClientID(options.ClientID).
		SetTLSConfig(tlsConfig).
		SetCleanSession(true).
		SetKeepAlive(60 * time.Second).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetConnectRetryInterval(2 * time.Second)
	if options.WillTopic != "" {
		clientOptions.SetBinaryWill(options.WillTopic, options.WillPayload, 1, false)
	}
	if options.OnMessage != nil {
		clientOptions.SetDefaultPublishHandler(func(_ mqtt.Client, message mqtt.Message) {
			options.OnMessage(Message{Topic: message.Topic(), Payload: append([]byte(nil), message.Payload()...)})
		})
	}
	if options.OnConnection != nil {
		clientOptions.SetOnConnectHandler(func(_ mqtt.Client) { options.OnConnection() })
	}
	if options.OnConnectionLost != nil {
		clientOptions.SetConnectionLostHandler(func(_ mqtt.Client, err error) { options.OnConnectionLost(err) })
	}
	return &Client{client: mqtt.NewClient(clientOptions)}, nil
}

func (c *Client) Connect() error {
	token := c.client.Connect()
	if !token.WaitTimeout(30 * time.Second) {
		return fmt.Errorf("MQTT connect timed out")
	}
	return token.Error()
}

func (c *Client) Disconnect(quiesce uint) {
	c.client.Disconnect(quiesce)
}

func (c *Client) Subscribe(filter string, handler func(Message)) error {
	var callback mqtt.MessageHandler
	if handler != nil {
		callback = func(_ mqtt.Client, message mqtt.Message) {
			handler(Message{Topic: message.Topic(), Payload: append([]byte(nil), message.Payload()...)})
		}
	}
	token := c.client.Subscribe(filter, 1, callback)
	if !token.WaitTimeout(30 * time.Second) {
		return fmt.Errorf("MQTT subscribe %s timed out", filter)
	}
	return token.Error()
}

func (c *Client) Publish(topic string, payload []byte, retained bool) error {
	token := c.client.Publish(topic, 1, retained, payload)
	if !token.WaitTimeout(30 * time.Second) {
		return fmt.Errorf("MQTT publish %s timed out", topic)
	}
	return token.Error()
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
