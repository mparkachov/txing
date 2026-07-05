// MQTT 5 client copied from devices/unit/daemon/internal/daemon/runtime.go
// (MQTTPublisher and packet codec). Keep byte-compatible with the unit
// daemon: QoS 1 publishes, retained messages with MQTT 5 message expiry,
// 60 second keep-alive.
package action

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

const (
	mqttKeepAliveSeconds = 60
	mqttPublishQoS       = 1
)

type PublishedMessage struct {
	Topic                string
	Payload              []byte
	Retain               bool
	MessageExpirySeconds *uint32
}

type Publisher interface {
	Publish(context.Context, PublishedMessage) error
}

type RuntimeMqttEvent struct {
	Topic        string
	Payload      []byte
	Disconnected bool
}

type MQTTPublisher struct {
	conn     net.Conn
	incoming chan RuntimeMqttEvent
	done     chan struct{}
	stopping atomic.Bool
	packetID atomic.Uint32
	writeMu  sync.Mutex
}

func ConnectMQTT(ctx context.Context, config Config) (*MQTTPublisher, <-chan RuntimeMqttEvent, error) {
	cert, err := tls.LoadX509KeyPair(config.IoTCertFile, config.IoTPrivateKeyFile)
	if err != nil {
		return nil, nil, fmt.Errorf("load MQTT client identity: %w", err)
	}
	rootPEM, err := os.ReadFile(config.IoTRootCAFile)
	if err != nil {
		return nil, nil, fmt.Errorf("read MQTT root CA %s: %w", config.IoTRootCAFile, err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(rootPEM) {
		return nil, nil, errors.New("load MQTT root CA")
	}
	dialer := &net.Dialer{}
	conn, err := tls.DialWithDialer(dialer, "tcp", fmt.Sprintf("%s:%d", config.IoTEndpoint, MQTTPort), &tls.Config{
		ServerName:   config.IoTEndpoint,
		Certificates: []tls.Certificate{cert},
		RootCAs:      roots,
		MinVersion:   tls.VersionTLS12,
	})
	if err != nil {
		return nil, nil, fmt.Errorf("connect MQTT mTLS: %w", err)
	}
	publisher := &MQTTPublisher{conn: conn, incoming: make(chan RuntimeMqttEvent, 32), done: make(chan struct{})}
	if err := publisher.writePacket(ctx, mqttPacketConnect(config.ClientID)); err != nil {
		_ = conn.Close()
		return nil, nil, err
	}
	packetType, _, payload, err := readMQTTPacket(conn)
	if err != nil {
		_ = conn.Close()
		return nil, nil, fmt.Errorf("read MQTT CONNACK: %w", err)
	}
	if packetType != 2 || !mqttConnAckAccepted(payload) {
		_ = conn.Close()
		return nil, nil, fmt.Errorf("MQTT connection failed: connack=%x", payload)
	}
	go publisher.readLoop()
	go publisher.pingLoop()
	return publisher, publisher.incoming, nil
}

func (p *MQTTPublisher) Subscribe(ctx context.Context, topicFilter string) error {
	packetID := p.nextPacketID()
	return p.writePacket(ctx, mqttPacketSubscribe(packetID, topicFilter))
}

func (p *MQTTPublisher) Publish(ctx context.Context, message PublishedMessage) error {
	packetID := p.nextPacketID()
	return p.writePacket(ctx, mqttPacketPublish(packetID, message.Topic, message.Payload, message.Retain, message.MessageExpirySeconds))
}

func (p *MQTTPublisher) Stop() error {
	p.stopping.Store(true)
	_ = p.writePacket(context.Background(), []byte{0xe0, 0x00})
	err := p.conn.Close()
	<-p.done
	return err
}

func (p *MQTTPublisher) nextPacketID() uint16 {
	next := uint16(p.packetID.Add(1) & 0xffff)
	if next == 0 {
		next = uint16(p.packetID.Add(1) & 0xffff)
	}
	return next
}

func (p *MQTTPublisher) writePacket(ctx context.Context, packet []byte) error {
	p.writeMu.Lock()
	defer p.writeMu.Unlock()
	if deadline, ok := ctx.Deadline(); ok {
		_ = p.conn.SetWriteDeadline(deadline)
		defer p.conn.SetWriteDeadline(time.Time{})
	}
	_, err := p.conn.Write(packet)
	return err
}

func (p *MQTTPublisher) readLoop() {
	defer close(p.done)
	for {
		packetType, flags, payload, err := readMQTTPacket(p.conn)
		if err != nil {
			if !p.stopping.Load() {
				p.incoming <- RuntimeMqttEvent{Disconnected: true}
			}
			close(p.incoming)
			return
		}
		if packetType == 3 {
			topic, packetID, body, qos, ok := parseMQTTPublish(flags, payload)
			if ok {
				if qos == 1 {
					_ = p.writePacket(context.Background(), mqttPacketPubAck(packetID))
				}
				p.incoming <- RuntimeMqttEvent{Topic: topic, Payload: body}
			}
		}
	}
}

func (p *MQTTPublisher) pingLoop() {
	ticker := time.NewTicker(time.Duration(mqttKeepAliveSeconds/2) * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			if p.stopping.Load() {
				return
			}
			_ = p.writePacket(context.Background(), []byte{0xc0, 0x00})
		case <-p.done:
			return
		}
	}
}

func publishJSON(ctx context.Context, publisher Publisher, topic string, payload interface{}, retain bool) error {
	return publishJSONWithOptions(ctx, publisher, topic, payload, retain, nil)
}

func publishRetainedDynamicJSON(ctx context.Context, publisher Publisher, topic string, payload interface{}, ttl time.Duration) error {
	return publishJSONWithOptions(ctx, publisher, topic, payload, true, retainedExpirySeconds(ttl))
}

func publishJSONWithOptions(ctx context.Context, publisher Publisher, topic string, payload interface{}, retain bool, messageExpirySeconds *uint32) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return publisher.Publish(ctx, PublishedMessage{Topic: topic, Payload: encoded, Retain: retain, MessageExpirySeconds: messageExpirySeconds})
}

func retainedExpirySeconds(ttl time.Duration) *uint32 {
	seconds := uint64(ttl / time.Second)
	if ttl%time.Second != 0 {
		seconds++
	}
	if seconds == 0 {
		seconds = 1
	}
	if seconds > uint64(^uint32(0)) {
		seconds = uint64(^uint32(0))
	}
	value := uint32(seconds)
	return &value
}

func mqttPacketConnect(clientID string) []byte {
	var variable bytes.Buffer
	writeMQTTString(&variable, "MQTT")
	variable.WriteByte(5)
	variable.WriteByte(2)
	_ = binary.Write(&variable, binary.BigEndian, uint16(mqttKeepAliveSeconds))
	writeMQTTVariableByteInteger(&variable, 5)
	variable.WriteByte(0x11)
	_ = binary.Write(&variable, binary.BigEndian, uint32(0))
	writeMQTTString(&variable, clientID)
	return appendMQTTFixedHeader(0x10, variable.Bytes())
}

func mqttPacketSubscribe(packetID uint16, topicFilter string) []byte {
	var variable bytes.Buffer
	_ = binary.Write(&variable, binary.BigEndian, packetID)
	writeMQTTVariableByteInteger(&variable, 0)
	writeMQTTString(&variable, topicFilter)
	variable.WriteByte(mqttPublishQoS)
	return appendMQTTFixedHeader(0x82, variable.Bytes())
}

func mqttPacketPublish(packetID uint16, topic string, payload []byte, retain bool, messageExpirySeconds *uint32) []byte {
	var variable bytes.Buffer
	writeMQTTString(&variable, topic)
	_ = binary.Write(&variable, binary.BigEndian, packetID)
	var properties bytes.Buffer
	if messageExpirySeconds != nil {
		properties.WriteByte(0x02)
		_ = binary.Write(&properties, binary.BigEndian, *messageExpirySeconds)
	}
	writeMQTTVariableByteInteger(&variable, properties.Len())
	variable.Write(properties.Bytes())
	variable.Write(payload)
	header := byte(0x30 | 0x02)
	if retain {
		header |= 0x01
	}
	return appendMQTTFixedHeader(header, variable.Bytes())
}

func mqttPacketPubAck(packetID uint16) []byte {
	return []byte{0x40, 0x04, byte(packetID >> 8), byte(packetID), 0x00, 0x00}
}

func appendMQTTFixedHeader(first byte, payload []byte) []byte {
	packet := []byte{first}
	remaining := len(payload)
	for {
		encoded := byte(remaining % 128)
		remaining /= 128
		if remaining > 0 {
			encoded |= 128
		}
		packet = append(packet, encoded)
		if remaining == 0 {
			break
		}
	}
	return append(packet, payload...)
}

func mqttConnAckAccepted(payload []byte) bool {
	if len(payload) < 3 || payload[1] != 0 {
		return false
	}
	propertyLength, propertyLengthBytes, ok := readMQTTVariableByteInteger(payload[2:])
	if !ok {
		return false
	}
	return 2+propertyLengthBytes+propertyLength == len(payload)
}

func readMQTTPacket(reader io.Reader) (byte, byte, []byte, error) {
	var first [1]byte
	if _, err := io.ReadFull(reader, first[:]); err != nil {
		return 0, 0, nil, err
	}
	multiplier := 1
	remaining := 0
	for i := 0; i < 4; i++ {
		var encoded [1]byte
		if _, err := io.ReadFull(reader, encoded[:]); err != nil {
			return 0, 0, nil, err
		}
		remaining += int(encoded[0]&127) * multiplier
		if encoded[0]&128 == 0 {
			payload := make([]byte, remaining)
			_, err := io.ReadFull(reader, payload)
			return first[0] >> 4, first[0] & 0x0f, payload, err
		}
		multiplier *= 128
	}
	return 0, 0, nil, errors.New("MQTT remaining length exceeded 4 bytes")
}

func parseMQTTPublish(flags byte, payload []byte) (string, uint16, []byte, byte, bool) {
	if len(payload) < 2 {
		return "", 0, nil, 0, false
	}
	topicLen := int(binary.BigEndian.Uint16(payload[:2]))
	if len(payload) < 2+topicLen {
		return "", 0, nil, 0, false
	}
	topic := string(payload[2 : 2+topicLen])
	offset := 2 + topicLen
	var packetID uint16
	qos := (flags & 0x06) >> 1
	if qos > 0 {
		if len(payload) < offset+2 {
			return "", 0, nil, 0, false
		}
		packetID = binary.BigEndian.Uint16(payload[offset : offset+2])
		offset += 2
	}
	propertyLength, propertyLengthBytes, ok := readMQTTVariableByteInteger(payload[offset:])
	if !ok {
		return "", 0, nil, 0, false
	}
	offset += propertyLengthBytes
	if len(payload) < offset+propertyLength {
		return "", 0, nil, 0, false
	}
	offset += propertyLength
	return topic, packetID, payload[offset:], qos, true
}

func writeMQTTString(buffer *bytes.Buffer, value string) {
	_ = binary.Write(buffer, binary.BigEndian, uint16(len(value)))
	buffer.WriteString(value)
}

func writeMQTTVariableByteInteger(buffer *bytes.Buffer, value int) {
	for {
		encoded := byte(value % 128)
		value /= 128
		if value > 0 {
			encoded |= 128
		}
		buffer.WriteByte(encoded)
		if value == 0 {
			return
		}
	}
}

func readMQTTVariableByteInteger(payload []byte) (int, int, bool) {
	multiplier := 1
	value := 0
	for i := 0; i < 4; i++ {
		if i >= len(payload) {
			return 0, 0, false
		}
		encoded := payload[i]
		value += int(encoded&127) * multiplier
		if encoded&128 == 0 {
			return value, i + 1, true
		}
		multiplier *= 128
	}
	return 0, 0, false
}
