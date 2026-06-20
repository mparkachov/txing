package rigconfig

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

const DefaultConfigSubdir = ".config/txing/rig-daemon"

type Config struct {
	ConfigDir               string
	RigID                   string
	TownID                  string
	AWSRegion               string
	IoTEndpoint             string
	IoTCredentialEndpoint   string
	IoTRoleAlias            string
	CertificateFile         string
	PrivateKeyFile          string
	RootCAFile              string
	CloudWatchLogGroup      string
	CloudWatchLogLevel      string
	CloudWatchRetentionDays int32
	IPCSocket               string
	InventoryInterval       time.Duration
	CommandDeadline         time.Duration
	PresenceTimeout         time.Duration
	ReconnectDelay          time.Duration
	ConnectTimeout          time.Duration
	CommandTimeout          time.Duration
	HeartbeatInterval       time.Duration
	MaxBLEConnections       int
	NoBLE                   bool
	ThreadServiceDomain     string
	ThreadDiscoveryInterval time.Duration
	ThreadPollInterval      time.Duration
	ThreadCoAPTimeout       time.Duration
	ThreadHeartbeatInterval time.Duration
	Debug                   bool
}

func Load(configDirOverride string) (Config, error) {
	configDir, err := resolveConfigDir(configDirOverride)
	if err != nil {
		return Config{}, err
	}
	values, err := readEnvFile(filepath.Join(configDir, "daemon.env"))
	if err != nil {
		return Config{}, err
	}
	lookup := func(name string) string {
		if value := strings.TrimSpace(os.Getenv(name)); value != "" {
			return value
		}
		return strings.TrimSpace(values[name])
	}
	cfg := Config{
		ConfigDir:               configDir,
		RigID:                   firstNonEmpty(lookup("TXING_RIG_ID"), lookup("RIG_NAME")),
		TownID:                  firstNonEmpty(lookup("TXING_TOWN_ID"), lookup("SPARKPLUG_GROUP_ID")),
		AWSRegion:               firstNonEmpty(lookup("AWS_REGION"), lookup("TXING_AWS_REGION")),
		IoTEndpoint:             lookup("TXING_IOT_ENDPOINT"),
		IoTCredentialEndpoint:   lookup("TXING_IOT_CREDENTIAL_ENDPOINT"),
		IoTRoleAlias:            lookup("TXING_IOT_ROLE_ALIAS"),
		CertificateFile:         firstNonEmpty(lookup("TXING_IOT_CERT_FILE"), filepath.Join(configDir, "certificate.pem.crt")),
		PrivateKeyFile:          firstNonEmpty(lookup("TXING_IOT_PRIVATE_KEY_FILE"), filepath.Join(configDir, "private.pem.key")),
		RootCAFile:              firstNonEmpty(lookup("TXING_IOT_ROOT_CA_FILE"), filepath.Join(configDir, "AmazonRootCA1.pem")),
		CloudWatchLogGroup:      lookup("TXING_CLOUDWATCH_LOG_GROUP"),
		CloudWatchLogLevel:      firstNonEmpty(lookup("TXING_CLOUDWATCH_LOG_LEVEL"), "info"),
		CloudWatchRetentionDays: int32Env(lookup("TXING_CLOUDWATCH_LOG_RETENTION_DAYS"), 14),
		IPCSocket:               firstNonEmpty(lookup("TXING_RIG_IPC_SOCKET"), defaultIPCSocket()),
		InventoryInterval:       secondsEnv(lookup("TXING_INVENTORY_INTERVAL_SECONDS"), 30*time.Second),
		CommandDeadline:         millisEnv(lookup("TXING_COMMAND_DEADLINE_MS"), 60*time.Second),
		PresenceTimeout:         millisEnv(lookup("TXING_BLE_PRESENCE_TIMEOUT_MS"), 20*time.Second),
		ReconnectDelay:          millisEnv(lookup("TXING_BLE_RECONNECT_DELAY_MS"), 2*time.Second),
		ConnectTimeout:          millisEnv(lookup("TXING_BLE_CONNECT_TIMEOUT_MS"), 8*time.Second),
		CommandTimeout:          millisEnv(lookup("TXING_BLE_COMMAND_TIMEOUT_MS"), 8*time.Second),
		HeartbeatInterval:       millisEnv(lookup("TXING_BLE_HEARTBEAT_INTERVAL_MS"), 10*time.Second),
		MaxBLEConnections:       intEnv(lookup("TXING_BLE_MAX_CONNECTIONS"), 0),
		NoBLE:                   boolEnv(lookup("TXING_BLE_NO_BLE"), false),
		ThreadServiceDomain:     firstNonEmpty(lookup("TXING_THREAD_SERVICE_DOMAIN"), "default.service.arpa"),
		ThreadDiscoveryInterval: millisEnv(lookup("TXING_THREAD_DISCOVERY_INTERVAL_MS"), 10*time.Second),
		ThreadPollInterval:      millisEnv(lookup("TXING_THREAD_POLL_INTERVAL_MS"), 10*time.Second),
		ThreadCoAPTimeout:       millisEnv(lookup("TXING_THREAD_COAP_TIMEOUT_MS"), 8*time.Second),
		ThreadHeartbeatInterval: millisEnv(lookup("TXING_THREAD_HEARTBEAT_INTERVAL_MS"), 10*time.Second),
		Debug:                   boolEnv(lookup("TXING_RIG_DEBUG"), false),
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	required := map[string]string{
		"TXING_RIG_ID":                  c.RigID,
		"TXING_TOWN_ID":                 c.TownID,
		"AWS_REGION":                    c.AWSRegion,
		"TXING_IOT_ENDPOINT":            c.IoTEndpoint,
		"TXING_IOT_CREDENTIAL_ENDPOINT": c.IoTCredentialEndpoint,
		"TXING_IOT_ROLE_ALIAS":          c.IoTRoleAlias,
		"TXING_CLOUDWATCH_LOG_GROUP":    c.CloudWatchLogGroup,
	}
	for name, value := range required {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("missing required config %s", name)
		}
	}
	for name, path := range map[string]string{
		"certificate": c.CertificateFile,
		"private key": c.PrivateKeyFile,
		"root CA":     c.RootCAFile,
	} {
		if _, err := os.Stat(path); err != nil {
			return fmt.Errorf("missing %s file %s: %w", name, path, err)
		}
	}
	return nil
}

func resolveConfigDir(override string) (string, error) {
	if override != "" {
		return filepath.Abs(override)
	}
	if value := strings.TrimSpace(os.Getenv("TXING_RIG_CONFIG_DIR")); value != "" {
		return filepath.Abs(value)
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, DefaultConfigSubdir), nil
}

func readEnvFile(path string) (map[string]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	values := map[string]string{}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		value = strings.Trim(value, `"'`)
		values[key] = value
	}
	return values, scanner.Err()
}

func defaultIPCSocket() string {
	if runtime.GOOS == "darwin" {
		return filepath.Join(os.TempDir(), "txing-rig", "rig-ipc.sock")
	}
	return "/run/txing-rig/rig-ipc.sock"
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func secondsEnv(value string, fallback time.Duration) time.Duration {
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return fallback
	}
	return time.Duration(parsed) * time.Second
}

func millisEnv(value string, fallback time.Duration) time.Duration {
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseUint(value, 10, 64)
	if err != nil {
		return fallback
	}
	return time.Duration(parsed) * time.Millisecond
}

func intEnv(value string, fallback int) int {
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func int32Env(value string, fallback int32) int32 {
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 32)
	if err != nil {
		return fallback
	}
	return int32(parsed)
}

func boolEnv(value string, fallback bool) bool {
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}
