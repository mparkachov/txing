package thread

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net"
	"strings"
	"time"
)

const (
	coapVersion      = byte(1)
	coapTypeCON      = byte(0)
	coapTypeACK      = byte(2)
	coapCodeGET      = byte(1)
	coapCodePUT      = byte(3)
	coapCodeContent  = byte(69)
	coapCodeChanged  = byte(68)
	coapOptionPath   = uint16(11)
	coapOptionFormat = uint16(12)
	coapJSON         = uint32(50)
	coapPayloadMark  = byte(0xff)
)

type CoAPClient struct {
	Dialer   net.Dialer
	Timeout  time.Duration
	Attempts int
}

func (c CoAPClient) GetState(ctx context.Context, endpoint Endpoint) (DeviceState, error) {
	payload, err := c.do(ctx, endpoint, coapCodeGET, []string{"txing", "v1", "state"}, nil)
	if err != nil {
		return DeviceState{}, err
	}
	return DecodeDeviceState(payload, endpoint, NowMS(), 0)
}

func (c CoAPClient) PutRedcon(ctx context.Context, endpoint Endpoint, target uint8) (DeviceState, error) {
	request, err := EncodeRedconRequest(target)
	if err != nil {
		return DeviceState{}, err
	}
	payload, err := c.do(ctx, endpoint, coapCodePUT, []string{"txing", "v1", "redcon"}, request)
	if err != nil {
		return DeviceState{}, err
	}
	return DecodeDeviceState(payload, endpoint, NowMS(), 0)
}

func (c CoAPClient) do(ctx context.Context, endpoint Endpoint, code byte, path []string, payload []byte) ([]byte, error) {
	attempts := c.Attempts
	if attempts <= 0 {
		attempts = 2
	}
	timeout := c.Timeout
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	var lastErr error
	for attempt := 0; attempt < attempts; attempt++ {
		callCtx, cancel := context.WithTimeout(ctx, timeout)
		response, err := c.exchange(callCtx, endpoint, code, path, payload)
		cancel()
		if err == nil {
			return response, nil
		}
		lastErr = err
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
	}
	return nil, lastErr
}

func (c CoAPClient) exchange(ctx context.Context, endpoint Endpoint, code byte, path []string, payload []byte) ([]byte, error) {
	messageID, token := coapIDs()
	request, err := buildCoAPMessage(code, messageID, token, path, payload)
	if err != nil {
		return nil, err
	}
	conn, err := c.Dialer.DialContext(ctx, "udp", net.JoinHostPort(endpoint.Address.String(), fmt.Sprintf("%d", endpoint.Port)))
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(deadline)
	}
	if _, err := conn.Write(request); err != nil {
		return nil, err
	}
	buffer := make([]byte, 4096)
	for {
		n, err := conn.Read(buffer)
		if err != nil {
			return nil, err
		}
		response, err := parseCoAPResponse(buffer[:n], messageID, token)
		if err != nil {
			if strings.Contains(err.Error(), "token mismatch") || strings.Contains(err.Error(), "message id mismatch") {
				continue
			}
			return nil, err
		}
		return response, nil
	}
}

func buildCoAPMessage(code byte, messageID uint16, token []byte, path []string, payload []byte) ([]byte, error) {
	if len(token) > 8 {
		return nil, fmt.Errorf("CoAP token too large")
	}
	message := []byte{(coapVersion << 6) | (coapTypeCON << 4) | byte(len(token)), code, byte(messageID >> 8), byte(messageID)}
	message = append(message, token...)
	lastOption := uint16(0)
	for _, segment := range path {
		option, err := encodeCoAPOption(coapOptionPath-lastOption, []byte(segment))
		if err != nil {
			return nil, err
		}
		message = append(message, option...)
		lastOption = coapOptionPath
	}
	if payload != nil {
		option, err := encodeCoAPOption(coapOptionFormat-lastOption, encodeCoAPUint(coapJSON))
		if err != nil {
			return nil, err
		}
		message = append(message, option...)
		message = append(message, coapPayloadMark)
		message = append(message, payload...)
	}
	return message, nil
}

func parseCoAPResponse(payload []byte, messageID uint16, token []byte) ([]byte, error) {
	if len(payload) < 4 {
		return nil, fmt.Errorf("short CoAP response")
	}
	version := payload[0] >> 6
	messageType := (payload[0] >> 4) & 0x03
	tokenLen := int(payload[0] & 0x0f)
	if version != coapVersion {
		return nil, fmt.Errorf("unsupported CoAP version %d", version)
	}
	if messageType != coapTypeACK && messageType != coapTypeCON {
		return nil, fmt.Errorf("unsupported CoAP response type %d", messageType)
	}
	if len(payload) < 4+tokenLen {
		return nil, fmt.Errorf("short CoAP token")
	}
	gotID := binary.BigEndian.Uint16(payload[2:4])
	if gotID != messageID {
		return nil, fmt.Errorf("CoAP message id mismatch")
	}
	if !bytes.Equal(payload[4:4+tokenLen], token) {
		return nil, fmt.Errorf("CoAP token mismatch")
	}
	code := payload[1]
	body, err := coapPayload(payload[4+tokenLen:])
	if err != nil {
		return nil, err
	}
	if code != coapCodeContent && code != coapCodeChanged {
		return nil, fmt.Errorf("CoAP error code %s: %s", coapCodeString(code), string(body))
	}
	return body, nil
}

func coapPayload(payload []byte) ([]byte, error) {
	for i := 0; i < len(payload); {
		if payload[i] == coapPayloadMark {
			return append([]byte(nil), payload[i+1:]...), nil
		}
		if i+1 > len(payload) {
			return nil, fmt.Errorf("malformed CoAP option")
		}
		deltaNibble := payload[i] >> 4
		lengthNibble := payload[i] & 0x0f
		i++
		_, deltaExtra, err := decodeCoAPOptionNibble(deltaNibble, payload[i:])
		if err != nil {
			return nil, err
		}
		i += deltaExtra
		length, lengthExtra, err := decodeCoAPOptionNibble(lengthNibble, payload[i:])
		if err != nil {
			return nil, err
		}
		i += lengthExtra
		if length > uint32(len(payload)-i) {
			return nil, fmt.Errorf("CoAP option exceeds response")
		}
		i += int(length)
	}
	return nil, nil
}

func encodeCoAPOption(delta uint16, value []byte) ([]byte, error) {
	deltaNibble, deltaExtra, err := encodeCoAPOptionNibble(uint32(delta))
	if err != nil {
		return nil, err
	}
	lengthNibble, lengthExtra, err := encodeCoAPOptionNibble(uint32(len(value)))
	if err != nil {
		return nil, err
	}
	option := []byte{(deltaNibble << 4) | lengthNibble}
	option = append(option, deltaExtra...)
	option = append(option, lengthExtra...)
	option = append(option, value...)
	return option, nil
}

func encodeCoAPOptionNibble(value uint32) (byte, []byte, error) {
	switch {
	case value < 13:
		return byte(value), nil, nil
	case value < 269:
		return 13, []byte{byte(value - 13)}, nil
	case value < 65805:
		adjusted := value - 269
		return 14, []byte{byte(adjusted >> 8), byte(adjusted)}, nil
	default:
		return 0, nil, fmt.Errorf("CoAP option value too large")
	}
}

func decodeCoAPOptionNibble(nibble byte, payload []byte) (uint32, int, error) {
	switch nibble {
	case 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12:
		return uint32(nibble), 0, nil
	case 13:
		if len(payload) < 1 {
			return 0, 0, fmt.Errorf("short CoAP option extension")
		}
		return uint32(payload[0]) + 13, 1, nil
	case 14:
		if len(payload) < 2 {
			return 0, 0, fmt.Errorf("short CoAP option extension")
		}
		return uint32(binary.BigEndian.Uint16(payload[:2])) + 269, 2, nil
	default:
		return 0, 0, fmt.Errorf("reserved CoAP option nibble")
	}
}

func encodeCoAPUint(value uint32) []byte {
	if value == 0 {
		return nil
	}
	var buffer [4]byte
	binary.BigEndian.PutUint32(buffer[:], value)
	index := 0
	for index < len(buffer) && buffer[index] == 0 {
		index++
	}
	return buffer[index:]
}

func coapIDs() (uint16, []byte) {
	var raw [10]byte
	if _, err := rand.Read(raw[:]); err != nil {
		now := time.Now().UnixNano()
		binary.BigEndian.PutUint64(raw[2:], uint64(now))
		binary.BigEndian.PutUint16(raw[:2], uint16(now))
	}
	return binary.BigEndian.Uint16(raw[:2]), raw[2:]
}

func coapCodeString(code byte) string {
	return fmt.Sprintf("%d.%02d", code>>5, code&0x1f)
}

func JSONPayload(value any) []byte {
	payload, _ := json.Marshal(value)
	return payload
}
