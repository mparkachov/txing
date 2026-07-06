// Read-only MCP stub. Trimmed from the unit daemon MCP server: the mac
// device exposes only observation tools (control.get_state,
// robot.get_state); there is no active-control ownership and no actuator
// surface yet. The future command-line control milestone extends this.
package action

import (
	"encoding/json"
	"fmt"
	"strings"
)

type MCPTransportMode string

const (
	MCPTransportMQTT              MCPTransportMode = "mqtt-jsonrpc"
	MCPTransportWebRTCDataChannel MCPTransportMode = "webrtc-datachannel"
)

type RuntimeMcpOpenEvent struct {
	SessionID string
	Transport string
	PeerID    string
}

type RuntimeMcpRequestEvent struct {
	SessionID string
	Payload   string
	Response  chan *string
}

type RuntimeMcpCloseEvent struct {
	SessionID string
	Reason    string
}

type RobotControlReport struct {
	ActiveRequired       bool        `json:"activeRequired"`
	ActiveTTLMS          uint64      `json:"activeTtlMs"`
	ActiveHeldByCaller   bool        `json:"activeHeldByCaller"`
	ActiveOwnerSessionID *string     `json:"activeOwnerSessionId"`
	ActiveExpiresAtMS    *uint64     `json:"activeExpiresAtMs"`
	ActiveEpoch          *uint64     `json:"activeEpoch"`
	ActiveControl        interface{} `json:"activeControl"`
}

type RobotVideoReport struct {
	Available       bool    `json:"available"`
	Ready           bool    `json:"ready"`
	Status          string  `json:"status"`
	ViewerConnected bool    `json:"viewerConnected"`
	LastError       *string `json:"lastError"`
}

type RobotMotionReport struct {
	LeftSpeed  int32  `json:"leftSpeed"`
	RightSpeed int32  `json:"rightSpeed"`
	Sequence   uint64 `json:"sequence"`
}

type RobotStateReport struct {
	Control RobotControlReport `json:"control"`
	Motion  RobotMotionReport  `json:"motion"`
	Video   RobotVideoReport   `json:"video"`
}

func readOnlyControlReport() RobotControlReport {
	return RobotControlReport{ActiveRequired: false, ActiveControl: nil}
}

func (s VideoRuntimeState) RobotReport() RobotVideoReport {
	return RobotVideoReport{
		Available:       s.Available,
		Ready:           s.Ready,
		Status:          s.Status,
		ViewerConnected: s.ViewerConnected,
		LastError:       s.LastError,
	}
}

func MCPStatusPayload(nowMS uint64) map[string]interface{} {
	return map[string]interface{}{
		"serviceId":       MCPCapability,
		"available":       true,
		"status":          "ready",
		"protocolVersion": MCPProtocolVersion,
		"observedAtMs":    nowMS,
		"activeControl":   nil,
	}
}

func MCPUnavailablePayload(nowMS uint64) map[string]interface{} {
	return map[string]interface{}{
		"serviceId":       MCPCapability,
		"available":       false,
		"status":          "offline",
		"protocolVersion": MCPProtocolVersion,
		"observedAtMs":    nowMS,
		"activeControl":   nil,
	}
}

// HandleMCPJSONRPC answers a decoded JSON-RPC request. Requests without
// an id are notifications and produce no response (nil).
func HandleMCPJSONRPC(request map[string]interface{}, daemonVersion string, video VideoRuntimeState) map[string]interface{} {
	method, ok := request["method"].(string)
	if !ok {
		return jsonRPCErrorResponse(request["id"], jsonRPCError(-32600, "invalid request"))
	}
	id, hasID := request["id"]
	if !hasID {
		return nil
	}
	switch method {
	case "initialize":
		return jsonRPCSuccess(id, map[string]interface{}{
			"protocolVersion": MCPProtocolVersion,
			"serverInfo":      map[string]interface{}{"name": ServerName, "version": daemonVersion},
			"capabilities":    map[string]interface{}{"tools": map[string]interface{}{}},
		})
	case "tools/list":
		return jsonRPCSuccess(id, map[string]interface{}{
			"tools": []map[string]string{{"name": "control.get_state"}, {"name": "robot.get_state"}},
		})
	case "tools/call":
		params, _ := request["params"].(map[string]interface{})
		name, _ := params["name"].(string)
		structured, err := handleMCPTool(name, video)
		if err != nil {
			return jsonRPCErrorResponse(id, jsonRPCError(-32602, err.Error()))
		}
		return jsonRPCSuccess(id, map[string]interface{}{
			"structuredContent": structured,
			"content":           []map[string]interface{}{{"type": "json", "json": structured}},
		})
	default:
		return jsonRPCErrorResponse(id, jsonRPCError(-32601, "method not found"))
	}
}

func handleMCPTool(name string, video VideoRuntimeState) (interface{}, error) {
	switch strings.TrimSpace(name) {
	case "":
		return nil, fmt.Errorf("MCP tools/call requires a tool name")
	case "control.get_state":
		return readOnlyControlReport(), nil
	case "robot.get_state":
		return RobotStateReport{
			Control: readOnlyControlReport(),
			Motion:  RobotMotionReport{},
			Video:   video.RobotReport(),
		}, nil
	default:
		return nil, fmt.Errorf("unknown MCP tool %s", name)
	}
}

// HandleMCPPayload parses raw JSON-RPC bytes and returns the encoded
// response, or nil for notifications.
func HandleMCPPayload(payload []byte, daemonVersion string, video VideoRuntimeState) *string {
	var request map[string]interface{}
	if err := json.Unmarshal(payload, &request); err != nil {
		response := jsonRPCErrorResponse(nil, jsonRPCError(-32700, "parse error: "+err.Error()))
		encoded, _ := json.Marshal(response)
		value := string(encoded)
		return &value
	}
	response := HandleMCPJSONRPC(request, daemonVersion, video)
	if response == nil {
		return nil
	}
	encoded, _ := json.Marshal(response)
	value := string(encoded)
	return &value
}

func jsonRPCSuccess(id interface{}, result interface{}) map[string]interface{} {
	return map[string]interface{}{"jsonrpc": "2.0", "id": id, "result": result}
}

func jsonRPCErrorResponse(id interface{}, err map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{"jsonrpc": "2.0", "id": id, "error": err}
}

func jsonRPCError(code int64, message string) map[string]interface{} {
	return map[string]interface{}{"code": code, "message": message}
}
