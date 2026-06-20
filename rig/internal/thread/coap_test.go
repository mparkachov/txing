package thread

import (
	"context"
	"encoding/binary"
	"net"
	"testing"
	"time"
)

func TestCoAPClientGetsState(t *testing.T) {
	endpoint, done := startCoAPTestServer(t, func(request coapTestRequest) (byte, []byte) {
		if request.code != coapCodeGET || request.path != "txing/v1/state" {
			t.Fatalf("request = %#v", request)
		}
		return coapCodeContent, JSONPayload(DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 4})
	})
	defer done()

	state, err := (CoAPClient{Timeout: time.Second, Attempts: 1}).GetState(context.Background(), endpoint)
	if err != nil {
		t.Fatal(err)
	}
	if state.ThingName != "power-si-001" || state.Redcon != 4 {
		t.Fatalf("state = %#v", state)
	}
}

func TestCoAPClientPutRedconReturnsConfirmedState(t *testing.T) {
	endpoint, done := startCoAPTestServer(t, func(request coapTestRequest) (byte, []byte) {
		if request.code != coapCodePUT || request.path != "txing/v1/redcon" {
			t.Fatalf("request = %#v", request)
		}
		return coapCodeChanged, JSONPayload(DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3})
	})
	defer done()

	state, err := (CoAPClient{Timeout: time.Second, Attempts: 1}).PutRedcon(context.Background(), endpoint, 3)
	if err != nil {
		t.Fatal(err)
	}
	if state.Redcon != 3 {
		t.Fatalf("redcon = %d, want 3", state.Redcon)
	}
}

func TestCoAPClientReturnsErrorForCoAPFailure(t *testing.T) {
	endpoint, done := startCoAPTestServer(t, func(request coapTestRequest) (byte, []byte) {
		return 128, []byte(`{"error":"bad redcon"}`)
	})
	defer done()

	_, err := (CoAPClient{Timeout: time.Second, Attempts: 1}).PutRedcon(context.Background(), endpoint, 3)
	if err == nil {
		t.Fatal("expected CoAP failure")
	}
}

type coapTestRequest struct {
	code      byte
	messageID uint16
	token     []byte
	path      string
}

func startCoAPTestServer(t *testing.T, handler func(coapTestRequest) (byte, []byte)) (Endpoint, func()) {
	t.Helper()
	conn, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv6loopback, Port: 0})
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		buffer := make([]byte, 2048)
		n, addr, err := conn.ReadFromUDP(buffer)
		if err != nil {
			return
		}
		request, err := parseCoAPTestRequest(buffer[:n])
		if err != nil {
			t.Errorf("parse request: %v", err)
			return
		}
		code, payload := handler(request)
		response := buildCoAPTestResponse(code, request.messageID, request.token, payload)
		_, _ = conn.WriteToUDP(response, addr)
	}()
	endpoint := testEndpoint("power-si-001")
	endpoint.Address = net.IPv6loopback
	endpoint.Port = uint16(conn.LocalAddr().(*net.UDPAddr).Port)
	return endpoint, func() {
		_ = conn.Close()
		<-done
	}
}

func parseCoAPTestRequest(payload []byte) (coapTestRequest, error) {
	tokenLen := int(payload[0] & 0x0f)
	request := coapTestRequest{
		code:      payload[1],
		messageID: binary.BigEndian.Uint16(payload[2:4]),
		token:     append([]byte(nil), payload[4:4+tokenLen]...),
	}
	optionNumber := uint32(0)
	segments := []string{}
	for i := 4 + tokenLen; i < len(payload); {
		if payload[i] == coapPayloadMark {
			break
		}
		deltaNibble := payload[i] >> 4
		lengthNibble := payload[i] & 0x0f
		i++
		delta, deltaExtra, err := decodeCoAPOptionNibble(deltaNibble, payload[i:])
		if err != nil {
			return request, err
		}
		i += deltaExtra
		length, lengthExtra, err := decodeCoAPOptionNibble(lengthNibble, payload[i:])
		if err != nil {
			return request, err
		}
		i += lengthExtra
		optionNumber += delta
		value := payload[i : i+int(length)]
		i += int(length)
		if optionNumber == uint32(coapOptionPath) {
			segments = append(segments, string(value))
		}
	}
	for index, segment := range segments {
		if index > 0 {
			request.path += "/"
		}
		request.path += segment
	}
	return request, nil
}

func buildCoAPTestResponse(code byte, messageID uint16, token []byte, payload []byte) []byte {
	response := []byte{(coapVersion << 6) | (coapTypeACK << 4) | byte(len(token)), code, byte(messageID >> 8), byte(messageID)}
	response = append(response, token...)
	if payload != nil {
		response = append(response, coapPayloadMark)
		response = append(response, payload...)
	}
	return response
}
