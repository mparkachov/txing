package controller

import (
	"encoding/base64"
	"math"
	"regexp"
	"strconv"
	"strings"

	"google.golang.org/protobuf/encoding/protowire"

	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

const (
	requestMetric  = "virtualQuad.requestId"
	revisionMetric = "virtualQuad.terminalRevision"
	sessionMetric  = "virtualQuad.sessionId"
	typeInt32      = 3
	typeString     = 12
)

var segment = regexp.MustCompile(`^[A-Za-z0-9_-]{1,128}$`)

type command struct {
	Assignment       lifecycle.Assignment
	Request          lifecycle.CommandRequest
	REDCON           uint8
	TerminalRevision uint64
	SessionID        string
}

type commandMetric struct {
	name     string
	datatype uint64
	number   uint64
	text     string
	hasInt   bool
	hasText  bool
}

func decodeCommand(topic, encoded string) (command, error) {
	parts := strings.Split(topic, "/")
	if len(parts) != 5 || parts[0] != "spBv1.0" || parts[2] != "DCMD" ||
		!segment.MatchString(parts[1]) || !segment.MatchString(parts[3]) || !segment.MatchString(parts[4]) ||
		!strings.HasPrefix(parts[4], "virtual-quad-") || len(encoded) > 4096 {
		return command{}, lifecycle.ErrInvalidRequest
	}
	payload, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return command{}, lifecycle.ErrInvalidRequest
	}
	metrics := make(map[string]commandMetric, 3)
	var sequence uint32
	var hasSequence bool
	valid := walkWire(payload, func(field protowire.Number, kind protowire.Type, raw []byte) bool {
		switch field {
		case 2:
			if kind != protowire.BytesType || len(metrics) >= 3 {
				return false
			}
			body, _ := protowire.ConsumeBytes(raw)
			metric, ok := decodeCommandMetric(body)
			if _, duplicate := metrics[metric.name]; duplicate || !ok {
				return false
			}
			metrics[metric.name] = metric
		case 3:
			value, n := protowire.ConsumeVarint(raw)
			if kind != protowire.VarintType || hasSequence || n < 0 || value > math.MaxInt32 {
				return false
			}
			hasSequence, sequence = true, uint32(value)
		}
		return true
	})
	redcon := metrics["redcon"]
	request := metrics[requestMetric]
	if !valid || !hasSequence || len(metrics) != 3 || redcon.datatype != typeInt32 || !redcon.hasInt ||
		(redcon.number != 1 && redcon.number != 4) || request.datatype != typeString || !request.hasText || !lifecycle.ValidRequestID(request.text) {
		return command{}, lifecycle.ErrInvalidRequest
	}
	result := command{
		Assignment: lifecycle.Assignment{DeviceID: parts[4], TownID: parts[1], RigID: parts[3]},
		Request:    lifecycle.CommandRequest{ID: request.text, Sequence: sequence}, REDCON: uint8(redcon.number),
	}
	if result.REDCON == 1 {
		revision := metrics[revisionMetric]
		value, err := strconv.ParseUint(revision.text, 10, 64)
		if revision.datatype != typeString || !revision.hasText || err != nil || strconv.FormatUint(value, 10) != revision.text {
			return command{}, lifecycle.ErrInvalidRequest
		}
		result.TerminalRevision = value
	} else {
		session := metrics[sessionMetric]
		if session.datatype != typeString || !session.hasText || !segment.MatchString(session.text) {
			return command{}, lifecycle.ErrInvalidRequest
		}
		result.SessionID = session.text
	}
	return result, nil
}

func decodeCommandMetric(data []byte) (commandMetric, bool) {
	var metric commandMetric
	var hasType bool
	valid := walkWire(data, func(field protowire.Number, kind protowire.Type, raw []byte) bool {
		switch field {
		case 1, 15:
			if kind != protowire.BytesType {
				return false
			}
			value, _ := protowire.ConsumeString(raw)
			if field == 1 {
				if metric.name != "" || value == "" {
					return false
				}
				metric.name = value
			} else {
				if metric.hasText || metric.hasInt {
					return false
				}
				metric.hasText, metric.text = true, value
			}
		case 4, 10:
			if kind != protowire.VarintType {
				return false
			}
			value, _ := protowire.ConsumeVarint(raw)
			if field == 4 {
				if hasType {
					return false
				}
				hasType, metric.datatype = true, value
			} else {
				if metric.hasInt || metric.hasText {
					return false
				}
				metric.hasInt, metric.number = true, value
			}
		case 7, 11, 12, 13, 14, 16, 17, 18, 19:
			// Null or alternate value fields cannot participate in commands.
			return false
		}
		return true
	})
	return metric, valid && hasType && metric.name != "" && (metric.hasInt || metric.hasText)
}

func walkWire(payload []byte, visit func(protowire.Number, protowire.Type, []byte) bool) bool {
	for len(payload) > 0 {
		field, kind, tagLength := protowire.ConsumeTag(payload)
		if tagLength < 0 {
			return false
		}
		payload = payload[tagLength:]
		length := protowire.ConsumeFieldValue(field, kind, payload)
		if length < 0 || !visit(field, kind, payload[:length]) {
			return false
		}
		payload = payload[length:]
	}
	return true
}
