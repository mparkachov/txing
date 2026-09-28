package companion

import (
	"encoding/binary"
	"errors"
	"math"
)

// SplitMAVLink validates the entire datagram before returning any frames. The
// tunnel is dialect-independent: only safety-triggering commands/ACKs need a
// known CRC extra. Signatures, IDs and payloads are never rewritten.
func SplitMAVLink(data []byte) ([][]byte, error) {
	if len(data) == 0 {
		return nil, errors.New("empty MAVLink datagram")
	}
	var frames [][]byte
	for len(data) > 0 {
		if len(data) < 12 || data[0] != 0xfd || data[2]&^byte(1) != 0 {
			return nil, errors.New("invalid MAVLink 2 header")
		}
		size := 12 + int(data[1])
		if data[2]&1 != 0 {
			size += 13
		}
		if len(data) < size {
			return nil, errors.New("incomplete MAVLink 2 frame")
		}
		frames = append(frames, data[:size])
		data = data[size:]
	}
	return frames, nil
}

func messageID(frame []byte) uint32 {
	return uint32(frame[7]) | uint32(frame[8])<<8 | uint32(frame[9])<<16
}
func crcAccumulate(crc uint16, value byte) uint16 {
	tmp := value ^ byte(crc)
	tmp ^= tmp << 4
	return (crc >> 8) ^ (uint16(tmp) << 8) ^ (uint16(tmp) << 3) ^ (uint16(tmp) >> 4)
}
func validCRC(frame []byte, extra byte) bool {
	n := 10 + int(frame[1])
	crc := uint16(0xffff)
	for _, value := range frame[1:n] {
		crc = crcAccumulate(crc, value)
	}
	crc = crcAccumulate(crc, extra)
	return crc == binary.LittleEndian.Uint16(frame[n:n+2])
}

// Constants/layouts come from the pinned common C bindings under
// devices/common/board/mavlink/include/mavlink/v2.0/common. MAVLink 2 truncates
// trailing zero payload bytes; decoding pads them without altering the frame.
type armCommand struct {
	arm                                              bool
	system, component, senderSystem, senderComponent byte
}

func decodeArmCommand(frame []byte) (armCommand, bool) {
	var length int
	var extra byte
	switch messageID(frame) {
	case 76: // COMMAND_LONG
		length, extra = 33, 152
	case 75: // COMMAND_INT
		length, extra = 35, 158
	default:
		return armCommand{}, false
	}
	if int(frame[1]) > length || !validCRC(frame, extra) {
		return armCommand{}, false
	}
	var payload [35]byte
	copy(payload[:], frame[10:10+int(frame[1])])
	if binary.LittleEndian.Uint16(payload[28:30]) != 400 { // MAV_CMD_COMPONENT_ARM_DISARM
		return armCommand{}, false
	}
	param := math.Float32frombits(binary.LittleEndian.Uint32(payload[:4]))
	if param != 0 && param != 1 {
		return armCommand{}, false
	}
	return armCommand{param == 1, payload[30], payload[31], frame[5], frame[6]}, true
}
func disarmAcknowledged(frame []byte, command armCommand) bool {
	if messageID(frame) != 77 || frame[1] > 10 || !validCRC(frame, 143) {
		return false
	}
	var payload [10]byte
	copy(payload[:], frame[10:10+int(frame[1])])
	return binary.LittleEndian.Uint16(payload[:2]) == 400 && payload[2] != 5 && // MAV_RESULT_IN_PROGRESS is not terminal
		(command.system == 0 || command.system == frame[5]) &&
		(command.component == 0 || command.component == frame[6]) &&
		(payload[8] == 0 || payload[8] == command.senderSystem) &&
		(payload[9] == 0 || payload[9] == command.senderComponent)
}
