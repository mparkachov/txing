package controller

import (
	"context"
	"encoding/base64"
	"errors"
	"google.golang.org/protobuf/encoding/protowire"
	"testing"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

const commandTopic = "spBv1.0/town-test/DCMD/cloud-test/virtual-quad-test"

const officeStart = "COgHEgwKBnJlZGNvbiADUAESPwoVdmlydHVhbFF1YWQucmVxdWVzdElkIAx6JDAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMRIyChx2aXJ0dWFsUXVhZC50ZXJtaW5hbFJldmlzaW9uIAx6EDkwMDcxOTkyNTQ3NDA5OTEYGQ=="
const officeStop = "COgHEgwKBnJlZGNvbiADUAQSPwoVdmlydHVhbFF1YWQucmVxdWVzdElkIAx6JDAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMhInChV2aXJ0dWFsUXVhZC5zZXNzaW9uSWQgDHoMU0VTU0lPTl9URVNUGBk="
const startID = "00000000-0000-4000-8000-000000000001"
const stopID = "00000000-0000-4000-8000-000000000002"

var testAssignment = lifecycle.Assignment{DeviceID: "virtual-quad-test", TownID: "town-test", RigID: "cloud-test"}

func TestOfficeCommandEncoding(t *testing.T) {
	start, err := decodeCommand(commandTopic, officeStart)
	if err != nil || start.Assignment != testAssignment || start.REDCON != 1 ||
		start.Request.ID != startID || start.Request.Sequence != 25 || start.TerminalRevision != 9007199254740991 {
		t.Fatalf("Office Start did not preserve its command metadata: %#v %v", start, err)
	}
	stop, err := decodeCommand(commandTopic, officeStop)
	if err != nil || stop.REDCON != 4 || stop.SessionID != "SESSION_TEST" || stop.Request.ID != stopID {
		t.Fatalf("Office Stop did not preserve its session target: %#v %v", stop, err)
	}
	for _, payload := range []string{
		encodeTestCommand(1, startID, sessionMetric, "SESSION_TEST"),
		encodeTestCommand(4, stopID, revisionMetric, "1"),
		encodeTestCommand(1, startID, revisionMetric, "01"),
		encodeTestCommand(1, startID, requestMetric, startID),
		"not a packet",
	} {
		if _, err := decodeCommand(commandTopic, payload); !errors.Is(err, lifecycle.ErrInvalidRequest) {
			t.Fatalf("invalid command accepted: %v", err)
		}
	}
}

func encodeTestCommand(redcon uint64, request, targetName, targetValue string) string {
	appendMetric := func(packet []byte, name string, datatype uint64, value []byte) []byte {
		metric := protowire.AppendString(protowire.AppendTag(nil, 1, protowire.BytesType), name)
		metric = protowire.AppendVarint(protowire.AppendTag(metric, 4, protowire.VarintType), datatype)
		metric = append(metric, value...)
		return protowire.AppendBytes(protowire.AppendTag(packet, 2, protowire.BytesType), metric)
	}
	text := func(value string) []byte {
		return protowire.AppendString(protowire.AppendTag(nil, 15, protowire.BytesType), value)
	}
	packet := appendMetric(nil, "redcon", typeInt32, protowire.AppendVarint(protowire.AppendTag(nil, 10, protowire.VarintType), redcon))
	packet = appendMetric(packet, requestMetric, typeString, text(request))
	packet = appendMetric(packet, targetName, typeString, text(targetValue))
	packet = protowire.AppendVarint(protowire.AppendTag(packet, 3, protowire.VarintType), 25)
	return base64.StdEncoding.EncodeToString(packet)
}

type testRegistry struct {
	awake bool
	err   error
}

func (r testRegistry) Assignment(context.Context, string) (lifecycle.Assignment, bool, error) {
	return testAssignment, r.awake, r.err
}
