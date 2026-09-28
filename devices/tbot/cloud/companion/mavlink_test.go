package companion

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"math"
	"testing"
)

// Generated with the repository-pinned common C bindings (pack/to_send_buffer),
// independently of the Go recognizer and its CRC implementation.
var commandVectors = map[string]string{
	"long-arm":      "fd20000000ffbe4c00000000803f000000000000000000000000000000000000000000000000900101019e4e",
	"long-disarm":   "fd20000001ffbe4c00000000000000000000000000000000000000000000000000000000000090010101675c",
	"int-arm":       "fd20000002ffbe4b00000000803f00000000000000000000000000000000000000000000000090010101aae3",
	"int-disarm":    "fd20000003ffbe4b0000000000000000000000000000000000000000000000000000000000009001010153f1",
	"ack":           "fd0a00000401014d00009001000000000000ffbe5613",
	"broadcast-arm": "fd1e000005ffbe4c00000000803f0000000000000000000000000000000000000000000000009001d8c0",
	"truncated-ack": "fd0200000601014d00009001bffc",
}

func vector(name string) []byte {
	data, err := hex.DecodeString(commandVectors[name])
	if err != nil {
		panic(err)
	}
	return data
}

// Independent bitwise CRC-16/MCRF4XX for mutated test packets.
func testChecksum(frame []byte, extra byte) {
	crc := uint16(0xffff)
	for _, value := range append(append([]byte(nil), frame[1:10+int(frame[1])]...), extra) {
		crc ^= uint16(value)
		for bit := 0; bit < 8; bit++ {
			if crc&1 != 0 {
				crc = (crc >> 1) ^ 0x8408
			} else {
				crc >>= 1
			}
		}
	}
	binary.LittleEndian.PutUint16(frame[10+int(frame[1]):], crc)
}
func signedFrame(frame []byte, extra byte) []byte {
	frame = append([]byte(nil), frame...)
	frame[2] = 1
	testChecksum(frame, extra)
	return append(frame, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
}
func unfamiliarFrame(payloadSize int, signed bool) []byte {
	n := 12 + payloadSize
	if signed {
		n += 13
	}
	frame := make([]byte, n)
	frame[0] = 0xfd
	frame[1] = byte(payloadSize)
	frame[7] = 0x12
	frame[8] = 0x34
	frame[9] = 0x56
	if signed {
		frame[2] = 1
	}
	for i := 10; i < n; i++ {
		frame[i] = byte(i)
	}
	return frame
}
func TestMAVLinkDatagramBoundaries(t *testing.T) {
	known := vector("long-arm")
	unknown := unfamiliarFrame(255, true)
	packet := append(append([]byte(nil), known...), unknown...)
	frames, err := SplitMAVLink(packet)
	if err != nil || len(frames) != 2 || !bytes.Equal(frames[0], known) || !bytes.Equal(frames[1], unknown) {
		t.Fatal("frames changed", err)
	}
	for _, frame := range [][]byte{unfamiliarFrame(0, false), unfamiliarFrame(0, true), unknown, signedFrame(known, 152)} {
		got, err := SplitMAVLink(frame)
		if err != nil || len(got) != 1 || !bytes.Equal(got[0], frame) {
			t.Fatal("valid boundary rejected", err)
		}
	}
	badFlag := append([]byte(nil), known...)
	badFlag[2] = 2
	mav1 := append([]byte(nil), known...)
	mav1[0] = 0xfe
	for _, bad := range [][]byte{nil, {}, known[:11], known[:len(known)-1], unknown[:len(unknown)-1], append(packet, 0), badFlag, mav1} {
		if frames, err := SplitMAVLink(bad); err == nil || frames != nil {
			t.Fatal("malformed datagram partially accepted")
		}
	}
	for n := 1; n < len(unknown); n++ {
		if _, err := SplitMAVLink(unknown[:n]); err == nil {
			t.Fatalf("accepted truncated frame at %d", n)
		}
	}
}
func TestArmRecognitionUsesPinnedCRCAndZeroPadding(t *testing.T) {
	for _, name := range []string{"long-arm", "int-arm", "long-disarm", "int-disarm", "broadcast-arm"} {
		frame := vector(name)
		command, ok := decodeArmCommand(frame)
		if !ok || command.arm != (name != "long-disarm" && name != "int-disarm") {
			t.Fatal(name, command, ok)
		}
		extra := byte(152)
		if messageID(frame) == 75 {
			extra = 158
		}
		if _, ok := decodeArmCommand(signedFrame(frame, extra)); !ok {
			t.Fatal("signed command rejected")
		}
		bad := append([]byte(nil), frame...)
		bad[len(bad)-1] ^= 1
		if _, ok := decodeArmCommand(bad); ok {
			t.Fatal("invalid CRC triggers authority")
		}
	}
	for _, value := range []float32{2, -1, float32(math.NaN()), float32(math.Inf(1))} {
		frame := vector("long-arm")
		binary.LittleEndian.PutUint32(frame[10:14], math.Float32bits(value))
		testChecksum(frame, 152)
		if _, ok := decodeArmCommand(frame); ok {
			t.Fatal("invalid arm parameter recognized")
		}
	}
	frame := vector("long-arm")
	frame[38] = 0x91
	testChecksum(frame, 152)
	if _, ok := decodeArmCommand(frame); ok {
		t.Fatal("another command recognized as arm")
	}
	tooLong := append(vector("long-arm")[:42], 0, 0, 0, 0)
	tooLong[1] = 34
	testChecksum(tooLong, 152)
	if _, ok := decodeArmCommand(tooLong); ok {
		t.Fatal("invalid command payload length accepted")
	}
}
func FuzzMAVLinkBoundaries(f *testing.F) {
	f.Add(vector("long-arm"))
	f.Add(unfamiliarFrame(255, true))
	f.Add([]byte{})
	f.Fuzz(func(t *testing.T, data []byte) {
		frames, err := SplitMAVLink(data)
		if err != nil {
			if frames != nil {
				t.Fatal("partial result")
			}
			return
		}
		var combined []byte
		for _, frame := range frames {
			if len(frame) > 280 || len(frame) < 12 {
				t.Fatal("bad size")
			}
			combined = append(combined, frame...)
			decodeArmCommand(frame)
			disarmAcknowledged(frame, armCommand{})
		}
		if !bytes.Equal(data, combined) {
			t.Fatal("bytes changed")
		}
	})
}
