package sparkplug

import (
	"encoding/binary"
	"errors"
	"fmt"
	"math"
)

const Namespace = "spBv1.0"

type DataType uint64

const (
	DataTypeInt32   DataType = 3
	DataTypeUInt64  DataType = 8
	DataTypeDouble  DataType = 10
	DataTypeBoolean DataType = 11
	DataTypeString  DataType = 12
)

type MetricValueKind int

const (
	MetricInt32 MetricValueKind = iota
	MetricUInt64
	MetricDouble
	MetricBoolean
	MetricString
)

type MetricValue struct {
	Kind    MetricValueKind
	Int32   int32
	UInt64  uint64
	Double  float64
	Boolean bool
	String  string
}

type Metric struct {
	Name  string
	Value MetricValue
}

type Payload struct {
	Timestamp uint64
	Metrics   []Metric
	Seq       *uint64
}

type DecodedCommand struct {
	MetricName string
	Value      uint8
	Seq        *uint64
	Timestamp  *uint64
}

func NewInt32Metric(name string, value int32) Metric {
	return Metric{Name: name, Value: MetricValue{Kind: MetricInt32, Int32: value}}
}

func NewUInt64Metric(name string, value uint64) Metric {
	return Metric{Name: name, Value: MetricValue{Kind: MetricUInt64, UInt64: value}}
}

func NewDoubleMetric(name string, value float64) Metric {
	return Metric{Name: name, Value: MetricValue{Kind: MetricDouble, Double: value}}
}

func NewBooleanMetric(name string, value bool) Metric {
	return Metric{Name: name, Value: MetricValue{Kind: MetricBoolean, Boolean: value}}
}

func NewStringMetric(name string, value string) Metric {
	return Metric{Name: name, Value: MetricValue{Kind: MetricString, String: value}}
}

func BuildNodeTopic(groupID, messageType, edgeNodeID string) string {
	return fmt.Sprintf("%s/%s/%s/%s", Namespace, groupID, messageType, edgeNodeID)
}

func BuildNodeCommandTopic(groupID, edgeNodeID string) string {
	return BuildNodeTopic(groupID, "NCMD", edgeNodeID)
}

func BuildDeviceTopic(groupID, messageType, edgeNodeID, deviceID string) string {
	return fmt.Sprintf("%s/%s/%s/%s/%s", Namespace, groupID, messageType, edgeNodeID, deviceID)
}

func EncodePayload(payload Payload) ([]byte, error) {
	out := make([]byte, 0, 64)
	appendVarintField(&out, 1, payload.Timestamp)
	for _, metric := range payload.Metrics {
		encoded, err := EncodeMetric(metric)
		if err != nil {
			return nil, err
		}
		appendBytesField(&out, 2, encoded)
	}
	if payload.Seq != nil {
		appendVarintField(&out, 3, *payload.Seq)
	}
	return out, nil
}

func EncodeMetric(metric Metric) ([]byte, error) {
	out := make([]byte, 0, 32)
	appendStringField(&out, 1, metric.Name)
	switch metric.Value.Kind {
	case MetricInt32:
		appendVarintField(&out, 4, uint64(DataTypeInt32))
		appendVarintField(&out, 10, uint64(metric.Value.Int32))
	case MetricUInt64:
		appendVarintField(&out, 4, uint64(DataTypeUInt64))
		appendVarintField(&out, 11, metric.Value.UInt64)
	case MetricDouble:
		appendVarintField(&out, 4, uint64(DataTypeDouble))
		appendFixed64Field(&out, 13, metric.Value.Double)
	case MetricBoolean:
		appendVarintField(&out, 4, uint64(DataTypeBoolean))
		value := uint64(0)
		if metric.Value.Boolean {
			value = 1
		}
		appendVarintField(&out, 14, value)
	case MetricString:
		appendVarintField(&out, 4, uint64(DataTypeString))
		appendStringField(&out, 15, metric.Value.String)
	default:
		return nil, fmt.Errorf("unsupported Sparkplug metric value kind %d", metric.Value.Kind)
	}
	return out, nil
}

func DecodePayload(data []byte) (Payload, error) {
	offset := 0
	var timestamp uint64
	var seq *uint64
	var metrics []Metric
	for offset < len(data) {
		fieldNumber, wireType, next, err := readKey(data, offset)
		if err != nil {
			return Payload{}, err
		}
		offset = next
		switch {
		case fieldNumber == 1 && wireType == 0:
			value, next, err := readVarint(data, offset)
			if err != nil {
				return Payload{}, err
			}
			timestamp = value
			offset = next
		case fieldNumber == 2 && wireType == 2:
			value, next, err := readLengthDelimited(data, offset)
			if err != nil {
				return Payload{}, err
			}
			metric, err := DecodeMetric(value)
			if err != nil {
				return Payload{}, err
			}
			metrics = append(metrics, metric)
			offset = next
		case fieldNumber == 3 && wireType == 0:
			value, next, err := readVarint(data, offset)
			if err != nil {
				return Payload{}, err
			}
			valueCopy := value
			seq = &valueCopy
			offset = next
		default:
			next, err := skipField(data, offset, wireType)
			if err != nil {
				return Payload{}, err
			}
			offset = next
		}
	}
	return Payload{Timestamp: timestamp, Metrics: metrics, Seq: seq}, nil
}

func DecodeMetric(data []byte) (Metric, error) {
	offset := 0
	name := ""
	var dataType uint64
	var intValue *int32
	var longValue *uint64
	var doubleValue *float64
	var boolValue *bool
	var stringValue *string
	for offset < len(data) {
		fieldNumber, wireType, next, err := readKey(data, offset)
		if err != nil {
			return Metric{}, err
		}
		offset = next
		switch {
		case fieldNumber == 1 && wireType == 2:
			value, next, err := readLengthDelimited(data, offset)
			if err != nil {
				return Metric{}, err
			}
			name = string(value)
			offset = next
		case fieldNumber == 4 && wireType == 0:
			value, next, err := readVarint(data, offset)
			if err != nil {
				return Metric{}, err
			}
			dataType = value
			offset = next
		case fieldNumber == 10 && wireType == 0:
			value, next, err := readVarint(data, offset)
			if err != nil {
				return Metric{}, err
			}
			converted := int32(value)
			intValue = &converted
			offset = next
		case fieldNumber == 11 && wireType == 0:
			value, next, err := readVarint(data, offset)
			if err != nil {
				return Metric{}, err
			}
			longValue = &value
			offset = next
		case fieldNumber == 13 && wireType == 1:
			value, next, err := readFixed64(data, offset)
			if err != nil {
				return Metric{}, err
			}
			doubleValue = &value
			offset = next
		case fieldNumber == 14 && wireType == 0:
			value, next, err := readVarint(data, offset)
			if err != nil {
				return Metric{}, err
			}
			converted := value != 0
			boolValue = &converted
			offset = next
		case fieldNumber == 15 && wireType == 2:
			value, next, err := readLengthDelimited(data, offset)
			if err != nil {
				return Metric{}, err
			}
			converted := string(value)
			stringValue = &converted
			offset = next
		default:
			next, err := skipField(data, offset, wireType)
			if err != nil {
				return Metric{}, err
			}
			offset = next
		}
	}

	var value MetricValue
	switch DataType(dataType) {
	case DataTypeInt32:
		if intValue == nil {
			return Metric{}, errors.New("Int32 metric missing value")
		}
		value = MetricValue{Kind: MetricInt32, Int32: *intValue}
	case DataTypeUInt64:
		if longValue == nil {
			return Metric{}, errors.New("UInt64 metric missing value")
		}
		value = MetricValue{Kind: MetricUInt64, UInt64: *longValue}
	case DataTypeDouble:
		if doubleValue == nil {
			return Metric{}, errors.New("Double metric missing value")
		}
		value = MetricValue{Kind: MetricDouble, Double: *doubleValue}
	case DataTypeBoolean:
		if boolValue == nil {
			return Metric{}, errors.New("Boolean metric missing value")
		}
		value = MetricValue{Kind: MetricBoolean, Boolean: *boolValue}
	case DataTypeString:
		if stringValue == nil {
			return Metric{}, errors.New("String metric missing value")
		}
		value = MetricValue{Kind: MetricString, String: *stringValue}
	default:
		return Metric{}, fmt.Errorf("unsupported Sparkplug metric datatype %d", dataType)
	}
	return Metric{Name: name, Value: value}, nil
}

func DecodeRedconCommand(data []byte) (*DecodedCommand, error) {
	payload, err := DecodePayload(data)
	if err != nil {
		return nil, err
	}
	for _, metric := range payload.Metrics {
		if metric.Name != "redcon" {
			continue
		}
		var value int32
		switch metric.Value.Kind {
		case MetricInt32:
			value = metric.Value.Int32
		case MetricUInt64:
			if metric.Value.UInt64 > math.MaxInt32 {
				return nil, nil
			}
			value = int32(metric.Value.UInt64)
		default:
			return nil, nil
		}
		if value < 1 || value > 4 {
			return nil, nil
		}
		timestamp := payload.Timestamp
		return &DecodedCommand{
			MetricName: metric.Name,
			Value:      uint8(value),
			Seq:        payload.Seq,
			Timestamp:  &timestamp,
		}, nil
	}
	return nil, nil
}

func BuildRedconPayload(redcon uint8, seq uint64, timestamp uint64) ([]byte, error) {
	if err := ValidateRedcon(redcon); err != nil {
		return nil, err
	}
	return EncodePayload(Payload{
		Timestamp: timestamp,
		Metrics:   []Metric{NewInt32Metric("redcon", int32(redcon))},
		Seq:       &seq,
	})
}

func BuildDeviceReportPayload(redcon uint8, seq uint64, timestamp uint64, metrics []Metric) ([]byte, error) {
	if err := ValidateRedcon(redcon); err != nil {
		return nil, err
	}
	allMetrics := make([]Metric, 0, len(metrics)+1)
	allMetrics = append(allMetrics, NewInt32Metric("redcon", int32(redcon)))
	allMetrics = append(allMetrics, metrics...)
	return EncodePayload(Payload{Timestamp: timestamp, Metrics: allMetrics, Seq: &seq})
}

func BuildDeviceDeathPayload(seq uint64, timestamp uint64) ([]byte, error) {
	return EncodePayload(Payload{Timestamp: timestamp, Seq: &seq})
}

func BuildNodeBirthPayload(redcon uint8, bdSeq uint64, seq uint64, timestamp uint64) ([]byte, error) {
	return BuildNodeBirthPayloadWithMetrics(redcon, bdSeq, seq, timestamp, nil)
}

func BuildNodeBirthPayloadWithMetrics(redcon uint8, bdSeq uint64, seq uint64, timestamp uint64, metrics []Metric) ([]byte, error) {
	if err := ValidateRedcon(redcon); err != nil {
		return nil, err
	}
	allMetrics := []Metric{
		NewUInt64Metric("bdSeq", bdSeq),
		NewInt32Metric("redcon", int32(redcon)),
	}
	allMetrics = append(allMetrics, metrics...)
	return EncodePayload(Payload{
		Timestamp: timestamp,
		Metrics:   allMetrics,
		Seq:       &seq,
	})
}

func BuildNodeDeathPayload(redcon uint8, bdSeq uint64, timestamp uint64) ([]byte, error) {
	if err := ValidateRedcon(redcon); err != nil {
		return nil, err
	}
	return EncodePayload(Payload{
		Timestamp: timestamp,
		Metrics: []Metric{
			NewUInt64Metric("bdSeq", bdSeq),
			NewInt32Metric("redcon", int32(redcon)),
		},
	})
}

func ValidateRedcon(level uint8) error {
	if level < 1 || level > 4 {
		return fmt.Errorf("redcon must be between 1 and 4, got %d", level)
	}
	return nil
}

func appendKey(out *[]byte, fieldNumber uint64, wireType uint64) {
	appendVarint(out, (fieldNumber<<3)|wireType)
}

func appendVarintField(out *[]byte, fieldNumber uint64, value uint64) {
	appendKey(out, fieldNumber, 0)
	appendVarint(out, value)
}

func appendStringField(out *[]byte, fieldNumber uint64, value string) {
	appendBytesField(out, fieldNumber, []byte(value))
}

func appendBytesField(out *[]byte, fieldNumber uint64, value []byte) {
	appendKey(out, fieldNumber, 2)
	appendVarint(out, uint64(len(value)))
	*out = append(*out, value...)
}

func appendFixed64Field(out *[]byte, fieldNumber uint64, value float64) {
	appendKey(out, fieldNumber, 1)
	var bytes [8]byte
	binary.LittleEndian.PutUint64(bytes[:], math.Float64bits(value))
	*out = append(*out, bytes[:]...)
}

func appendVarint(out *[]byte, value uint64) {
	for {
		next := byte(value & 0x7f)
		value >>= 7
		if value != 0 {
			*out = append(*out, next|0x80)
			continue
		}
		*out = append(*out, next)
		return
	}
}

func readKey(data []byte, offset int) (uint64, uint64, int, error) {
	key, next, err := readVarint(data, offset)
	if err != nil {
		return 0, 0, 0, err
	}
	return key >> 3, key & 0x07, next, nil
}

func readVarint(data []byte, offset int) (uint64, int, error) {
	var value uint64
	shift := 0
	index := offset
	for {
		if index >= len(data) {
			return 0, 0, errors.New("unexpected end of buffer while reading varint")
		}
		next := data[index]
		index++
		value |= uint64(next&0x7f) << shift
		if next&0x80 == 0 {
			return value, index, nil
		}
		shift += 7
		if shift > 63 {
			return 0, 0, errors.New("varint is too large")
		}
	}
}

func readLengthDelimited(data []byte, offset int) ([]byte, int, error) {
	length, next, err := readVarint(data, offset)
	if err != nil {
		return nil, 0, err
	}
	end := next + int(length)
	if end > len(data) {
		return nil, 0, errors.New("unexpected end of buffer while reading bytes field")
	}
	return data[next:end], end, nil
}

func readFixed64(data []byte, offset int) (float64, int, error) {
	end := offset + 8
	if end > len(data) {
		return 0, 0, errors.New("unexpected end of buffer while reading fixed64 field")
	}
	return math.Float64frombits(binary.LittleEndian.Uint64(data[offset:end])), end, nil
}

func skipField(data []byte, offset int, wireType uint64) (int, error) {
	switch wireType {
	case 0:
		_, next, err := readVarint(data, offset)
		return next, err
	case 1:
		next := offset + 8
		if next > len(data) {
			return 0, errors.New("unexpected end of buffer while skipping fixed64 field")
		}
		return next, nil
	case 2:
		_, next, err := readLengthDelimited(data, offset)
		return next, err
	case 5:
		next := offset + 4
		if next > len(data) {
			return 0, errors.New("unexpected end of buffer while skipping fixed32 field")
		}
		return next, nil
	default:
		return 0, fmt.Errorf("unsupported wire type %d", wireType)
	}
}
