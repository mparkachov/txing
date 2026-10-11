package daemon

import (
	"bytes"
	"context"
	"encoding/json"
	"net"
	"testing"
	"time"

	mavlinkbridgev1 "github.com/mparkachov/txing/devices/common/board/daemon/internal/proto/mavlinkbridgev1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
)

func TestMAVLinkBridgeRetainsObserverAfterStaleUplink(t *testing.T) {
	for _, transition := range []string{"release", "expiry", "takeover"} {
		t.Run(transition, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			config := testRuntimeConfig()
			config.Capabilities = []string{BoardCapability, MAVLinkCapability}
			state, err := NewRuntimeState(config)
			if err != nil {
				cancel()
				t.Fatal(err)
			}
			transport := &fakeMAVLinkFlightTransport{}
			state.mavlinkFlight = transport
			events := make(chan interface{}, 32)
			processedFrames := make(chan struct{}, 8)
			runtimeErrors := make(chan error, 8)
			runtimeDone := make(chan struct{})
			nowMS := uint64(100)
			go func() {
				defer close(runtimeDone)
				for {
					select {
					case <-ctx.Done():
						return
					case event := <-events:
						if action, ok := event.(func()); ok {
							action()
							continue
						}
						if err := state.HandleMAVLinkBridgeEvent(ctx, &fakePublisher{}, event, nowMS); err != nil {
							runtimeErrors <- err
						}
						if _, ok := event.(runtimeMAVLinkBridgeFrameEvent); ok {
							processedFrames <- struct{}{}
						}
					}
				}
			}()
			t.Cleanup(func() { cancel(); <-runtimeDone })
			onRuntime := func(action func()) {
				t.Helper()
				done := make(chan struct{})
				events <- func() { action(); close(done) }
				select {
				case <-done:
				case <-ctx.Done():
					t.Fatal("daemon runtime stopped responding")
				}
			}

			listener := bufconn.Listen(1024 * 1024)
			server := grpc.NewServer()
			mavlinkbridgev1.RegisterBoardMavlinkBridgeServer(server, NewMAVLinkBridgeService(config, events))
			go server.Serve(listener)
			t.Cleanup(func() { server.Stop(); _ = listener.Close() })
			conn, err := grpc.NewClient("passthrough:///mavlink-test",
				grpc.WithTransportCredentials(insecure.NewCredentials()),
				grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.DialContext(ctx) }),
			)
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = conn.Close() })
			client := mavlinkbridgev1.NewBoardMavlinkBridgeClient(conn)
			peer, err := client.OpenPeer(ctx, &mavlinkbridgev1.OpenPeerRequest{PeerId: "office"})
			if err != nil {
				t.Fatal(err)
			}
			control := func(sessionID, operation string, epoch uint64) {
				t.Helper()
				request := map[string]interface{}{"type": "control." + operation, "requestId": operation}
				if operation == "activate" {
					request["actor"], request["takeover"] = "operator", true
				} else {
					request["epoch"] = epoch
				}
				payload, _ := json.Marshal(request)
				response, err := client.HandleControlMessage(ctx, &mavlinkbridgev1.ControlMessageRequest{SessionId: sessionID, Json: string(payload)})
				if err != nil {
					t.Fatalf("%s: %v", operation, err)
				}
				if mavlinkControlResponseHasType(t, response.GetJson(), "control.error") {
					t.Fatalf("%s: %s", operation, response.GetJson())
				}
			}
			control(peer.GetSessionId(), "activate", 0)
			stream, err := client.ExchangeFrames(ctx)
			if err != nil {
				t.Fatal(err)
			}
			if err := stream.Send(&mavlinkbridgev1.PeerFrame{SessionId: peer.GetSessionId()}); err != nil {
				t.Fatal(err)
			}
			frame := testMAVLinkFrame(mavlinkManualControlMessageID, testManualControlPayload(1), 255, 190)
			sendFrame := func(epoch uint64) {
				t.Helper()
				if err := stream.Send(&mavlinkbridgev1.PeerFrame{SessionId: peer.GetSessionId(), Epoch: epoch, Frame: frame}); err != nil {
					t.Fatal(err)
				}
				select {
				case <-processedFrames:
				case <-ctx.Done():
					t.Fatal("MAVLink frame stream stopped processing uplinks")
				}
			}
			sendFrame(1)
			switch transition {
			case "release":
				control(peer.GetSessionId(), "release_active", 1)
			case "expiry":
				onRuntime(func() {
					nowMS = 5100
					if err := state.TickWatchdogs(ctx, &fakePublisher{}, nowMS); err != nil {
						runtimeErrors <- err
					}
				})
			case "takeover":
				other, err := client.OpenPeer(ctx, &mavlinkbridgev1.OpenPeerRequest{PeerId: "other"})
				if err != nil {
					t.Fatal(err)
				}
				control(other.GetSessionId(), "activate", 0)
			}
			// A queued drive frame can be authorized after the independent
			// control RPC releases, expires, or transfers its lease.
			sendFrame(1)
			events <- runtimeMAVLinkTelemetryEvent{frame: frame}
			telemetry, err := stream.Recv()
			if err != nil || !bytes.Equal(telemetry.GetFrame(), frame) {
				t.Fatalf("observer telemetry after %s: frame=%v err=%v", transition, telemetry, err)
			}
			control(peer.GetSessionId(), "activate", 0)
			var activeEpoch uint64
			onRuntime(func() { activeEpoch = state.mavlink.Active().Epoch })
			// Reacquiring must not make frames carrying the old epoch valid.
			sendFrame(1)
			sendFrame(activeEpoch)
			var forwarded, safeRequests int
			onRuntime(func() { forwarded, safeRequests = len(transport.frames), len(transport.safeRequests) })
			if forwarded != 2 {
				t.Fatalf("forwarded %d frames, want only the two authorized uplinks", forwarded)
			}
			if transition != "takeover" && safeRequests != 1 {
				t.Fatalf("safe-state requests = %d, want 1", safeRequests)
			}
			select {
			case err := <-runtimeErrors:
				t.Fatal(err)
			default:
			}
		})
	}
}
