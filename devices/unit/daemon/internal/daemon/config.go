package daemon

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const (
	SchemaVersion                 = "2.0"
	AdapterID                     = "dev.txing.unit.Daemon"
	BoardCapability               = "board"
	MCPCapability                 = "mcp"
	VideoCapability               = "video"
	BoardShadowName               = "board"
	MCPShadowName                 = "mcp"
	VideoShadowName               = "video"
	MCPProtocolVersion            = "2026-05-19"
	DefaultConfigSubdir           = "txing/unit-daemon"
	DefaultEnvFileName            = "daemon.env"
	DefaultIoTCertFileName        = "certificate.pem.crt"
	DefaultIoTPrivateKeyFileName  = "private.pem.key"
	DefaultIoTRootCAFileName      = "AmazonRootCA1.pem"
	DefaultCapabilityTTLSeconds   = uint64(150)
	DefaultHeartbeatSeconds       = uint64(60)
	DefaultMCPActiveTTLMillis     = uint64(5000)
	DefaultLogRetentionDays       = int32(14)
	DefaultKVSMasterCommand       = "txing-board-kvs-master"
	DefaultMCPWebRTCSocketPath    = "/run/txing-unit-daemon/mcp-webrtc.sock"
	DefaultBoardVideoBridgeSocket = "/run/txing-unit-daemon/board-video-bridge.sock"
	DefaultHardwareSocketPath     = "/run/txing-unit-hardware-worker/unit-hardware.sock"
	DefaultHardwareTimeoutMillis  = uint64(700)
	MCPWebRTCDataChannelLabel     = "txing.mcp.v1"
	DefaultVideoCodec             = "h264"
	DefaultVideoTransport         = "aws-webrtc"
	VideoStatusStarting           = "starting"
	VideoStatusReady              = "ready"
	VideoStatusError              = "error"
	VideoStatusUnavailable        = "unavailable"
	MQTTPort                      = 8883
)

var DefaultDaemonEnvTemplate = mustReadDaemonEnvTemplate()

type CLI struct {
	EnvFile                    string
	ThingID                    string
	AWSRegion                  string
	IoTEndpoint                string
	IoTCredentialEndpoint      string
	IoTRoleAlias               string
	IoTCertFile                string
	IoTPrivateKeyFile          string
	IoTRootCAFile              string
	ClientID                   string
	Capabilities               []string
	CapabilityTTLSeconds       *uint64
	HeartbeatSeconds           *uint64
	CloudWatchLogGroup         string
	CloudWatchLogStream        string
	CloudWatchLogLevel         string
	CloudWatchLogRetentionDays *int32
	KVSMasterCommand           string
	MCPWebRTCSocketPath        string
	BoardVideoBridgeSocketPath string
	KVSPreferIPv6              string
	KVSDisableIPv4TURN         string
	VideoChannelName           string
	HardwareWorkerSocketPath   string
	HardwareWorkerTimeoutMS    *uint64
	ShowVersion                bool
}

type RuntimeConfig struct {
	ThingID                    string
	AWSRegion                  string
	IoTEndpoint                string
	IoTCredentialEndpoint      string
	IoTRoleAlias               string
	IoTCertFile                string
	IoTPrivateKeyFile          string
	IoTRootCAFile              string
	ClientID                   string
	Capabilities               []string
	CapabilityTTL              time.Duration
	Heartbeat                  time.Duration
	KVSMasterCommand           string
	MCPWebRTCSocketPath        string
	BoardVideoBridgeSocketPath string
	KVSPreferIPv6              bool
	KVSDisableIPv4TURN         bool
	VideoRegion                string
	VideoChannelName           string
	HardwareWorkerSocketPath   string
	HardwareWorkerTimeout      time.Duration
	CloudWatchLogging          *CloudWatchLogConfig
}

type CloudWatchLogLevel string

const (
	CloudWatchDebug CloudWatchLogLevel = "debug"
	CloudWatchInfo  CloudWatchLogLevel = "info"
	CloudWatchWarn  CloudWatchLogLevel = "warn"
	CloudWatchError CloudWatchLogLevel = "error"
)

type CloudWatchLogConfig struct {
	LogGroup      string
	LogStream     string
	Level         CloudWatchLogLevel
	RetentionDays int32
}

type LoadedEnvFile struct {
	Values map[string]string
	Path   string
}

func (l LoadedEnvFile) ParentDir() string {
	if l.Path == "" {
		return ""
	}
	return filepath.Dir(l.Path)
}

type stringSliceFlag []string

func (s *stringSliceFlag) String() string {
	return strings.Join(*s, ",")
}

func (s *stringSliceFlag) Set(value string) error {
	*s = append(*s, value)
	return nil
}

func ParseCLI(args []string) (CLI, error) {
	var cli CLI
	flags := flag.NewFlagSet("txing-unit-daemon", flag.ContinueOnError)
	flags.SetOutput(new(strings.Builder))
	flags.StringVar(&cli.EnvFile, "env-file", "", "")
	flags.StringVar(&cli.ThingID, "thing-id", "", "")
	flags.StringVar(&cli.AWSRegion, "aws-region", "", "")
	flags.StringVar(&cli.IoTEndpoint, "iot-endpoint", "", "")
	flags.StringVar(&cli.IoTCredentialEndpoint, "iot-credential-endpoint", "", "")
	flags.StringVar(&cli.IoTRoleAlias, "iot-role-alias", "", "")
	flags.StringVar(&cli.IoTCertFile, "iot-cert-file", "", "")
	flags.StringVar(&cli.IoTPrivateKeyFile, "iot-private-key-file", "", "")
	flags.StringVar(&cli.IoTRootCAFile, "iot-root-ca-file", "", "")
	flags.StringVar(&cli.ClientID, "client-id", "", "")
	flags.Var((*stringSliceFlag)(&cli.Capabilities), "capability", "")
	flags.Func("capability-ttl-seconds", "", func(value string) error {
		parsed, err := strconv.ParseUint(value, 10, 64)
		if err != nil {
			return fmt.Errorf("capability-ttl-seconds must be an unsigned integer")
		}
		cli.CapabilityTTLSeconds = &parsed
		return nil
	})
	flags.Func("heartbeat-seconds", "", func(value string) error {
		parsed, err := strconv.ParseUint(value, 10, 64)
		if err != nil {
			return fmt.Errorf("heartbeat-seconds must be an unsigned integer")
		}
		cli.HeartbeatSeconds = &parsed
		return nil
	})
	flags.StringVar(&cli.CloudWatchLogGroup, "cloudwatch-log-group", "", "")
	flags.StringVar(&cli.CloudWatchLogStream, "cloudwatch-log-stream", "", "")
	flags.StringVar(&cli.CloudWatchLogLevel, "cloudwatch-log-level", "", "")
	flags.Func("cloudwatch-log-retention-days", "", func(value string) error {
		parsed, err := strconv.ParseInt(value, 10, 32)
		if err != nil {
			return fmt.Errorf("cloudwatch-log-retention-days must be an integer")
		}
		n := int32(parsed)
		cli.CloudWatchLogRetentionDays = &n
		return nil
	})
	flags.StringVar(&cli.KVSMasterCommand, "kvs-master-command", "", "")
	flags.StringVar(&cli.MCPWebRTCSocketPath, "mcp-webrtc-socket-path", "", "")
	flags.StringVar(&cli.BoardVideoBridgeSocketPath, "board-video-bridge-socket-path", "", "")
	flags.StringVar(&cli.KVSPreferIPv6, "kvs-prefer-ipv6", "", "")
	flags.StringVar(&cli.KVSDisableIPv4TURN, "kvs-disable-ipv4-turn", "", "")
	flags.StringVar(&cli.VideoChannelName, "video-channel-name", "", "")
	flags.StringVar(&cli.HardwareWorkerSocketPath, "hardware-worker-socket-path", "", "")
	flags.Func("hardware-worker-timeout-ms", "", func(value string) error {
		parsed, err := strconv.ParseUint(value, 10, 64)
		if err != nil {
			return fmt.Errorf("hardware-worker-timeout-ms must be an unsigned integer")
		}
		cli.HardwareWorkerTimeoutMS = &parsed
		return nil
	})
	flags.BoolVar(&cli.ShowVersion, "version", false, "")
	if err := flags.Parse(args); err != nil {
		return CLI{}, err
	}
	if flags.NArg() != 0 {
		return CLI{}, fmt.Errorf("unexpected positional arguments: %s", strings.Join(flags.Args(), " "))
	}
	return cli, nil
}

func RuntimeConfigFromCLI(cli CLI) (RuntimeConfig, error) {
	processEnv := mapFromEnv(os.Environ())
	loaded, err := LoadEnvFileForCLI(cli, processEnv)
	if err != nil {
		return RuntimeConfig{}, err
	}
	return RuntimeConfigFromSourcesWithEnvFileDir(cli, processEnv, loaded.Values, loaded.ParentDir())
}

func RuntimeConfigFromSources(cli CLI, processEnv, fileEnv map[string]string) (RuntimeConfig, error) {
	return RuntimeConfigFromSourcesWithEnvFileDir(cli, processEnv, fileEnv, "")
}

func RuntimeConfigFromSourcesWithEnvFileDir(cli CLI, processEnv, fileEnv map[string]string, envFileDir string) (RuntimeConfig, error) {
	thingID, err := requiredConfigValue(cli.ThingID, processEnv, fileEnv, "TXING_THING_ID", "thing-id")
	if err != nil {
		return RuntimeConfig{}, err
	}
	if err := validateTopicSegment(thingID, "thing-id"); err != nil {
		return RuntimeConfig{}, err
	}
	capabilityTTLSeconds, err := resolveU64(cli.CapabilityTTLSeconds, processEnv, fileEnv, "TXING_CAPABILITY_TTL_SECONDS", DefaultCapabilityTTLSeconds)
	if err != nil {
		return RuntimeConfig{}, err
	}
	heartbeatSeconds, err := resolveU64(cli.HeartbeatSeconds, processEnv, fileEnv, "TXING_HEARTBEAT_SECONDS", DefaultHeartbeatSeconds)
	if err != nil {
		return RuntimeConfig{}, err
	}
	if capabilityTTLSeconds == 0 {
		return RuntimeConfig{}, errors.New("capability-ttl-seconds must be greater than 0")
	}
	if heartbeatSeconds == 0 {
		return RuntimeConfig{}, errors.New("heartbeat-seconds must be greater than 0")
	}
	if heartbeatSeconds >= capabilityTTLSeconds {
		return RuntimeConfig{}, errors.New("heartbeat-seconds must be less than capability-ttl-seconds")
	}
	capabilities, err := normalizeCapabilities(resolveCapabilities(cli.Capabilities, processEnv, fileEnv))
	if err != nil {
		return RuntimeConfig{}, err
	}
	clientID := optionalConfigValue(cli.ClientID, processEnv, fileEnv, "TXING_DAEMON_CLIENT_ID")
	if clientID == "" {
		clientID = defaultClientID(thingID, os.Getpid())
	}
	if err := validateClientID(thingID, clientID); err != nil {
		return RuntimeConfig{}, err
	}
	kvsMasterCommand := optionalConfigValue(cli.KVSMasterCommand, processEnv, fileEnv, "TXING_KVS_MASTER_COMMAND")
	if kvsMasterCommand == "" {
		kvsMasterCommand = DefaultKVSMasterCommand
	}
	mcpWebRTCSocketPath := optionalConfigValue(cli.MCPWebRTCSocketPath, processEnv, fileEnv, "TXING_MCP_WEBRTC_SOCKET_PATH")
	if mcpWebRTCSocketPath == "" {
		mcpWebRTCSocketPath = DefaultMCPWebRTCSocketPath
	}
	if strings.TrimSpace(mcpWebRTCSocketPath) == "" {
		return RuntimeConfig{}, errors.New("mcp-webrtc-socket-path must not be empty")
	}
	boardVideoBridgeSocketPath := optionalConfigValue(cli.BoardVideoBridgeSocketPath, processEnv, fileEnv, "TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH")
	if boardVideoBridgeSocketPath == "" {
		boardVideoBridgeSocketPath = DefaultBoardVideoBridgeSocket
	}
	if strings.TrimSpace(boardVideoBridgeSocketPath) == "" {
		return RuntimeConfig{}, errors.New("board-video-bridge-socket-path must not be empty")
	}
	hardwareSocketPath := optionalConfigValue(cli.HardwareWorkerSocketPath, processEnv, fileEnv, "TXING_HARDWARE_WORKER_SOCKET_PATH")
	if hardwareSocketPath == "" {
		hardwareSocketPath = DefaultHardwareSocketPath
	}
	if strings.TrimSpace(hardwareSocketPath) == "" {
		return RuntimeConfig{}, errors.New("hardware-worker-socket-path must not be empty")
	}
	hardwareTimeoutMS, err := resolveU64(cli.HardwareWorkerTimeoutMS, processEnv, fileEnv, "TXING_HARDWARE_WORKER_TIMEOUT_MS", DefaultHardwareTimeoutMillis)
	if err != nil {
		return RuntimeConfig{}, err
	}
	if hardwareTimeoutMS == 0 {
		return RuntimeConfig{}, errors.New("hardware-worker-timeout-ms must be positive")
	}
	kvsPreferIPv6, err := optionalBoolConfig(cli.KVSPreferIPv6, processEnv, fileEnv, "TXING_KVS_PREFER_IPV6", "kvs-prefer-ipv6")
	if err != nil {
		return RuntimeConfig{}, err
	}
	if kvsPreferIPv6 == nil {
		value := true
		kvsPreferIPv6 = &value
	}
	kvsDisableIPv4TURN, err := optionalBoolConfig(cli.KVSDisableIPv4TURN, processEnv, fileEnv, "TXING_KVS_DISABLE_IPV4_TURN", "kvs-disable-ipv4-turn")
	if err != nil {
		return RuntimeConfig{}, err
	}
	if kvsDisableIPv4TURN == nil {
		value := false
		kvsDisableIPv4TURN = &value
	}
	awsRegion, err := requiredConfigValue(cli.AWSRegion, processEnv, fileEnv, "AWS_REGION", "aws-region")
	if err != nil {
		return RuntimeConfig{}, err
	}
	videoChannelName := optionalConfigValue(cli.VideoChannelName, processEnv, fileEnv, "TXING_BOARD_VIDEO_CHANNEL_NAME")
	if videoChannelName == "" {
		videoChannelName = defaultVideoChannelName(thingID)
	}
	if err := validateTopicSegment(videoChannelName, "video-channel-name"); err != nil {
		return RuntimeConfig{}, err
	}
	if err := validateTopicSegment(awsRegion, "aws-region"); err != nil {
		return RuntimeConfig{}, err
	}
	cloudwatch, err := resolveCloudWatchLogConfig(cli, processEnv, fileEnv, clientID)
	if err != nil {
		return RuntimeConfig{}, err
	}
	iotEndpoint, err := requiredConfigValue(cli.IoTEndpoint, processEnv, fileEnv, "TXING_IOT_ENDPOINT", "iot-endpoint")
	if err != nil {
		return RuntimeConfig{}, err
	}
	if err := validateEndpointHost(iotEndpoint, "iot-endpoint"); err != nil {
		return RuntimeConfig{}, err
	}
	iotCredentialEndpoint, err := requiredConfigValue(cli.IoTCredentialEndpoint, processEnv, fileEnv, "TXING_IOT_CREDENTIAL_ENDPOINT", "iot-credential-endpoint")
	if err != nil {
		return RuntimeConfig{}, err
	}
	if err := validateEndpointHost(iotCredentialEndpoint, "iot-credential-endpoint"); err != nil {
		return RuntimeConfig{}, err
	}
	iotRoleAlias, err := requiredConfigValue(cli.IoTRoleAlias, processEnv, fileEnv, "TXING_IOT_ROLE_ALIAS", "iot-role-alias")
	if err != nil {
		return RuntimeConfig{}, err
	}
	if err := validateRoleAlias(iotRoleAlias); err != nil {
		return RuntimeConfig{}, err
	}
	iotCertFile, err := configValueOrColocatedFile(cli.IoTCertFile, processEnv, fileEnv, "TXING_IOT_CERT_FILE", "iot-cert-file", envFileDir, DefaultIoTCertFileName)
	if err != nil {
		return RuntimeConfig{}, err
	}
	iotPrivateKeyFile, err := configValueOrColocatedFile(cli.IoTPrivateKeyFile, processEnv, fileEnv, "TXING_IOT_PRIVATE_KEY_FILE", "iot-private-key-file", envFileDir, DefaultIoTPrivateKeyFileName)
	if err != nil {
		return RuntimeConfig{}, err
	}
	iotRootCAFile, err := configValueOrColocatedFile(cli.IoTRootCAFile, processEnv, fileEnv, "TXING_IOT_ROOT_CA_FILE", "iot-root-ca-file", envFileDir, DefaultIoTRootCAFileName)
	if err != nil {
		return RuntimeConfig{}, err
	}
	return RuntimeConfig{
		ThingID:                    thingID,
		AWSRegion:                  awsRegion,
		IoTEndpoint:                iotEndpoint,
		IoTCredentialEndpoint:      iotCredentialEndpoint,
		IoTRoleAlias:               iotRoleAlias,
		IoTCertFile:                iotCertFile,
		IoTPrivateKeyFile:          iotPrivateKeyFile,
		IoTRootCAFile:              iotRootCAFile,
		ClientID:                   clientID,
		Capabilities:               capabilities,
		CapabilityTTL:              time.Duration(capabilityTTLSeconds) * time.Second,
		Heartbeat:                  time.Duration(heartbeatSeconds) * time.Second,
		KVSMasterCommand:           kvsMasterCommand,
		MCPWebRTCSocketPath:        mcpWebRTCSocketPath,
		BoardVideoBridgeSocketPath: boardVideoBridgeSocketPath,
		KVSPreferIPv6:              *kvsPreferIPv6,
		KVSDisableIPv4TURN:         *kvsDisableIPv4TURN,
		VideoRegion:                awsRegion,
		VideoChannelName:           videoChannelName,
		HardwareWorkerSocketPath:   hardwareSocketPath,
		HardwareWorkerTimeout:      time.Duration(hardwareTimeoutMS) * time.Millisecond,
		CloudWatchLogging:          cloudwatch,
	}, nil
}

func LoadEnvFileForCLI(cli CLI, processEnv map[string]string) (LoadedEnvFile, error) {
	if envFile := normalizeOptional(cli.EnvFile); envFile != "" {
		return readEnvFile(envFile, true)
	}
	if envFile := normalizeOptional(processEnv["TXING_DAEMON_ENV_FILE"]); envFile != "" {
		return readEnvFile(envFile, true)
	}
	if configDir := normalizeOptional(processEnv["TXING_DAEMON_CONFIG_DIR"]); configDir != "" {
		return readEnvFile(filepath.Join(configDir, DefaultEnvFileName), true)
	}
	return readEnvFileCandidates(defaultEnvFileCandidates(processEnv), false)
}

func ParseEnvFileContents(contents string) (map[string]string, error) {
	values := make(map[string]string)
	lines := strings.Split(contents, "\n")
	for i, rawLine := range lines {
		lineNumber := i + 1
		line := strings.TrimSpace(rawLine)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return nil, fmt.Errorf("invalid daemon env line %d: expected KEY=VALUE", lineNumber)
		}
		key = strings.TrimSpace(key)
		if err := validateEnvKey(key); err != nil {
			return nil, fmt.Errorf("invalid daemon env line %d: %w", lineNumber, err)
		}
		parsed, err := parseEnvValue(strings.TrimSpace(value), lineNumber)
		if err != nil {
			return nil, err
		}
		values[key] = parsed
	}
	return values, nil
}

func readEnvFileCandidates(candidates []string, explicit bool) (LoadedEnvFile, error) {
	for _, candidate := range candidates {
		loaded, err := readEnvFile(candidate, false)
		if err != nil {
			return LoadedEnvFile{}, err
		}
		if loaded.Path != "" {
			return loaded, nil
		}
	}
	if explicit && len(candidates) > 0 {
		return readEnvFile(candidates[0], true)
	}
	return LoadedEnvFile{Values: map[string]string{}}, nil
}

func readEnvFile(path string, explicit bool) (LoadedEnvFile, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) && !explicit {
			return LoadedEnvFile{Values: map[string]string{}}, nil
		}
		return LoadedEnvFile{}, fmt.Errorf("read daemon env file %s: %w", path, err)
	}
	values, err := ParseEnvFileContents(string(contents))
	if err != nil {
		return LoadedEnvFile{}, err
	}
	return LoadedEnvFile{Values: values, Path: path}, nil
}

func defaultEnvFileCandidates(processEnv map[string]string) []string {
	var candidates []string
	if xdg := normalizeOptional(processEnv["XDG_CONFIG_HOME"]); xdg != "" {
		candidates = append(candidates, filepath.Join(xdg, DefaultConfigSubdir, DefaultEnvFileName))
	}
	if home := normalizeOptional(processEnv["HOME"]); home != "" {
		candidates = append(candidates, filepath.Join(home, ".config", DefaultConfigSubdir, DefaultEnvFileName))
	}
	return candidates
}

func parseEnvValue(value string, lineNumber int) (string, error) {
	if len(value) >= 2 {
		first := value[0]
		last := value[len(value)-1]
		if (first == '\'' && last == '\'') || (first == '"' && last == '"') {
			return value[1 : len(value)-1], nil
		}
	}
	if strings.HasPrefix(value, "'") || strings.HasPrefix(value, "\"") {
		return "", fmt.Errorf("invalid daemon env line %d: unterminated quoted value", lineNumber)
	}
	return value, nil
}

func validateEnvKey(key string) error {
	if key == "" {
		return errors.New("env key must start with an ASCII letter or underscore")
	}
	for i, r := range key {
		if i == 0 {
			if (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z') || r == '_' {
				continue
			}
			return errors.New("env key must start with an ASCII letter or underscore")
		}
		if !((r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '_') {
			return errors.New("env key must contain only ASCII letters, digits, and underscore")
		}
	}
	return nil
}

func requiredConfigValue(cliValue string, processEnv, fileEnv map[string]string, envName, label string) (string, error) {
	if value := optionalConfigValue(cliValue, processEnv, fileEnv, envName); value != "" {
		return value, nil
	}
	return "", fmt.Errorf("%s is required; pass --%s or set %s", label, label, envName)
}

func configValueOrColocatedFile(cliValue string, processEnv, fileEnv map[string]string, envName, label, envFileDir, fileName string) (string, error) {
	if value := optionalConfigValue(cliValue, processEnv, fileEnv, envName); value != "" {
		return value, nil
	}
	if envFileDir != "" {
		return filepath.Join(envFileDir, fileName), nil
	}
	return "", fmt.Errorf("%s is required; pass --%s, set %s, or load an env file from the daemon config directory", label, label, envName)
}

func optionalConfigValue(cliValue string, processEnv, fileEnv map[string]string, envName string) string {
	if value := normalizeOptional(cliValue); value != "" {
		return value
	}
	if value := normalizeOptional(processEnv[envName]); value != "" {
		return value
	}
	return normalizeOptional(fileEnv[envName])
}

func resolveU64(cliValue *uint64, processEnv, fileEnv map[string]string, envName string, defaultValue uint64) (uint64, error) {
	if cliValue != nil {
		return *cliValue, nil
	}
	value := optionalConfigValue("", processEnv, fileEnv, envName)
	if value == "" {
		return defaultValue, nil
	}
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%s must be an unsigned integer", envName)
	}
	return parsed, nil
}

func parseBoolText(value, label string) (bool, error) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "1", "true", "yes", "on":
		return true, nil
	case "0", "false", "no", "off":
		return false, nil
	default:
		return false, fmt.Errorf("%s expects one of true/false, 1/0, yes/no, on/off", label)
	}
}

func optionalBoolConfig(cliValue string, processEnv, fileEnv map[string]string, envName, label string) (*bool, error) {
	value := optionalConfigValue(cliValue, processEnv, fileEnv, envName)
	if value == "" {
		return nil, nil
	}
	parsed, err := parseBoolText(value, label)
	if err != nil {
		return nil, err
	}
	return &parsed, nil
}

func resolveCloudWatchLogConfig(cli CLI, processEnv, fileEnv map[string]string, clientID string) (*CloudWatchLogConfig, error) {
	logGroup := optionalConfigValue(cli.CloudWatchLogGroup, processEnv, fileEnv, "TXING_CLOUDWATCH_LOG_GROUP")
	logStream := optionalConfigValue(cli.CloudWatchLogStream, processEnv, fileEnv, "TXING_CLOUDWATCH_LOG_STREAM")
	logLevel := optionalConfigValue(cli.CloudWatchLogLevel, processEnv, fileEnv, "TXING_CLOUDWATCH_LOG_LEVEL")
	var retentionDays *int32
	if cli.CloudWatchLogRetentionDays != nil {
		retentionDays = cli.CloudWatchLogRetentionDays
	} else if value := optionalConfigValue("", processEnv, fileEnv, "TXING_CLOUDWATCH_LOG_RETENTION_DAYS"); value != "" {
		parsed, err := strconv.ParseInt(value, 10, 32)
		if err != nil {
			return nil, errors.New("TXING_CLOUDWATCH_LOG_RETENTION_DAYS must be an integer")
		}
		dayCount := int32(parsed)
		retentionDays = &dayCount
	}
	requested := logGroup != "" || logStream != "" || logLevel != "" || retentionDays != nil
	if logGroup == "" {
		if requested {
			return nil, errors.New("cloudwatch-log-group is required when CloudWatch logging options are set")
		}
		return nil, nil
	}
	if err := validateCloudWatchLogGroup(logGroup); err != nil {
		return nil, err
	}
	if logStream == "" {
		logStream = defaultCloudWatchLogStream(clientID)
	}
	if err := validateCloudWatchLogStream(logStream); err != nil {
		return nil, err
	}
	level := CloudWatchInfo
	if logLevel != "" {
		parsed, err := parseCloudWatchLevel(logLevel)
		if err != nil {
			return nil, err
		}
		level = parsed
	}
	days := DefaultLogRetentionDays
	if retentionDays != nil {
		days = *retentionDays
	}
	if days <= 0 {
		return nil, errors.New("cloudwatch-log-retention-days must be greater than 0")
	}
	return &CloudWatchLogConfig{LogGroup: logGroup, LogStream: logStream, Level: level, RetentionDays: days}, nil
}

func parseCloudWatchLevel(value string) (CloudWatchLogLevel, error) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "debug":
		return CloudWatchDebug, nil
	case "info":
		return CloudWatchInfo, nil
	case "warn", "warning":
		return CloudWatchWarn, nil
	case "error":
		return CloudWatchError, nil
	default:
		return "", fmt.Errorf("unsupported cloudwatch-log-level %q", value)
	}
}

func resolveCapabilities(cliCapabilities []string, processEnv, fileEnv map[string]string) []string {
	if len(cliCapabilities) > 0 {
		return append([]string(nil), cliCapabilities...)
	}
	value := optionalConfigValue("", processEnv, fileEnv, "TXING_DAEMON_CAPABILITIES")
	if value == "" {
		return nil
	}
	var capabilities []string
	for _, part := range strings.Split(value, ",") {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			capabilities = append(capabilities, trimmed)
		}
	}
	return capabilities
}

func normalizeCapabilities(values []string) ([]string, error) {
	set := make(map[string]struct{})
	if len(values) == 0 {
		set[BoardCapability] = struct{}{}
		set[MCPCapability] = struct{}{}
		set[VideoCapability] = struct{}{}
	} else {
		for _, value := range values {
			normalized := strings.TrimSpace(value)
			if normalized == "" {
				return nil, errors.New("capability must not be empty")
			}
			if err := validateCapabilityName(normalized); err != nil {
				return nil, err
			}
			set[normalized] = struct{}{}
		}
	}
	capabilities := make([]string, 0, len(set))
	for capability := range set {
		capabilities = append(capabilities, capability)
	}
	sort.Strings(capabilities)
	return capabilities, nil
}

func validateCapabilityName(value string) error {
	if err := validateTopicSegment(value, "capability"); err != nil {
		return err
	}
	switch value {
	case BoardCapability, MCPCapability, VideoCapability:
		return nil
	default:
		return fmt.Errorf("unsupported capability %q; supported capabilities are %q, %q, %q", value, BoardCapability, MCPCapability, VideoCapability)
	}
}

func validateTopicSegment(value, label string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s must not be empty", label)
	}
	if strings.ContainsAny(value, "/#+") {
		return fmt.Errorf("%s must not contain MQTT topic separators or wildcards", label)
	}
	return nil
}

func validateEndpointHost(value, label string) error {
	if err := validateTopicSegment(value, label); err != nil {
		return err
	}
	if strings.Contains(value, "://") || strings.ContainsAny(value, "/:") {
		return fmt.Errorf("%s must be an endpoint hostname without scheme, path, or port", label)
	}
	if strings.IndexFunc(value, unicode.IsSpace) >= 0 {
		return fmt.Errorf("%s must not contain whitespace", label)
	}
	return nil
}

func validateCloudWatchLogGroup(value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return errors.New("cloudwatch-log-group must not be empty")
	}
	if len(value) > 512 {
		return errors.New("cloudwatch-log-group must be 512 characters or fewer")
	}
	if strings.HasPrefix(value, "aws/") || strings.HasPrefix(value, "/aws/") {
		return errors.New("cloudwatch-log-group must not use the reserved aws/ prefix")
	}
	for _, ch := range value {
		if !(isASCIIAlnum(ch) || ch == '.' || ch == '_' || ch == '-' || ch == '/' || ch == '#') {
			return errors.New("cloudwatch-log-group contains an unsupported character")
		}
	}
	return nil
}

func validateCloudWatchLogStream(value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return errors.New("cloudwatch-log-stream must not be empty")
	}
	if len(value) > 512 {
		return errors.New("cloudwatch-log-stream must be 512 characters or fewer")
	}
	for _, ch := range value {
		if ch == ':' || ch == '*' || unicode.IsControl(ch) {
			return errors.New("cloudwatch-log-stream contains an unsupported character")
		}
	}
	return nil
}

func validateRoleAlias(value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return errors.New("iot-role-alias must not be empty")
	}
	if len(value) > 128 {
		return errors.New("iot-role-alias must be 128 characters or fewer")
	}
	for _, ch := range value {
		if !(isASCIIAlnum(ch) || ch == '_' || ch == '=' || ch == ',' || ch == '@' || ch == '-') {
			return errors.New("iot-role-alias contains an unsupported character")
		}
	}
	return nil
}

func validateClientID(thingName, clientID string) error {
	clientID = strings.TrimSpace(clientID)
	if clientID == "" {
		return errors.New("client-id must not be empty")
	}
	if err := validateTopicSegment(clientID, "client-id"); err != nil {
		return err
	}
	if len(clientID) > 128 {
		return errors.New("client-id must be 128 characters or fewer")
	}
	expectedPrefix := defaultClientIDPrefix(thingName)
	if !strings.HasPrefix(clientID, expectedPrefix) {
		return fmt.Errorf("client-id must start with %q", expectedPrefix)
	}
	return nil
}

func defaultClientIDPrefix(thingName string) string {
	return sanitizeClientIDFragment(thingName) + "-daemon-"
}

func defaultClientID(thingName string, pid int) string {
	return fmt.Sprintf("%s%d", defaultClientIDPrefix(thingName), pid)
}

func defaultCloudWatchLogStream(clientID string) string {
	mapped := strings.Map(func(ch rune) rune {
		if ch == ':' || ch == '*' || unicode.IsControl(ch) {
			return '-'
		}
		return ch
	}, clientID)
	return "daemon/" + strings.Trim(mapped, "/")
}

func sanitizeClientIDFragment(thingName string) string {
	var b strings.Builder
	for _, ch := range thingName {
		if isASCIIAlnum(ch) || ch == '-' || ch == '_' {
			b.WriteRune(ch)
		} else {
			b.WriteRune('-')
		}
	}
	sanitized := strings.Trim(b.String(), "-")
	if sanitized == "" {
		sanitized = "unit"
	}
	const suffixReserve = 24
	if len(sanitized) > 128-suffixReserve {
		sanitized = sanitized[:128-suffixReserve]
	}
	return sanitized
}

func normalizeOptional(value string) string {
	return strings.TrimSpace(value)
}

func mapFromEnv(env []string) map[string]string {
	values := make(map[string]string, len(env))
	for _, item := range env {
		key, value, ok := strings.Cut(item, "=")
		if ok {
			values[key] = value
		}
	}
	return values
}

func isASCIIAlnum(ch rune) bool {
	return (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')
}

func defaultVideoChannelName(thingID string) string {
	return thingID + "-board-video"
}

func mustReadDaemonEnvTemplate() string {
	contents, err := os.ReadFile("daemon.env.template")
	if err == nil {
		return string(contents)
	}
	contents, err = os.ReadFile("../../daemon.env.template")
	if err == nil {
		return string(contents)
	}
	return ""
}
