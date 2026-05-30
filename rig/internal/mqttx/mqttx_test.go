package mqttx

import (
	"crypto/tls"
	"net/url"
	"testing"
)

func TestClientConfigUsesMQTT5SessionDefaults(t *testing.T) {
	brokerURL, err := url.Parse("tls://example.iot:8883")
	if err != nil {
		t.Fatal(err)
	}
	client := &Client{}
	config := newClientConfig(Options{
		ClientID:    "client-1",
		WillTopic:   "spBv1.0/town/NDEATH/rig-1",
		WillPayload: []byte("dead"),
	}, brokerURL, &tls.Config{}, client)

	if len(config.ServerUrls) != 1 || config.ServerUrls[0].String() != "tls://example.iot:8883" {
		t.Fatalf("server urls = %#v", config.ServerUrls)
	}
	if config.ClientID != "client-1" {
		t.Fatalf("client id = %s", config.ClientID)
	}
	if !config.CleanStartOnInitialConnection {
		t.Fatal("clean start must be enabled for the initial MQTT5 connection")
	}
	if config.SessionExpiryInterval != 0 {
		t.Fatalf("session expiry = %d, want 0", config.SessionExpiryInterval)
	}
	if config.KeepAlive != 60 {
		t.Fatalf("keep alive = %d, want 60", config.KeepAlive)
	}
	if config.WillMessage == nil {
		t.Fatal("will message is missing")
	}
	if config.WillMessage.Topic != "spBv1.0/town/NDEATH/rig-1" {
		t.Fatalf("will topic = %s", config.WillMessage.Topic)
	}
	if config.WillMessage.QoS != 1 {
		t.Fatalf("will qos = %d, want 1", config.WillMessage.QoS)
	}
	if config.WillMessage.Retain {
		t.Fatal("will message must not be retained")
	}
}

func TestBrokerURLDefaultsToMQTTTLS(t *testing.T) {
	brokerURL, err := BrokerURL("example.iot")
	if err != nil {
		t.Fatal(err)
	}
	if brokerURL.String() != "tls://example.iot:8883" {
		t.Fatalf("broker url = %s", brokerURL.String())
	}
}
