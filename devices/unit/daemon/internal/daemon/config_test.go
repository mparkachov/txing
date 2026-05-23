package daemon

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func testFileEnv() map[string]string {
	return map[string]string{
		"TXING_THING_ID":                "unit-local",
		"AWS_REGION":                    "eu-central-1",
		"TXING_IOT_ENDPOINT":            "example.iot.eu-central-1.amazonaws.com",
		"TXING_IOT_CREDENTIAL_ENDPOINT": "example.credentials.iot.eu-central-1.amazonaws.com",
		"TXING_IOT_ROLE_ALIAS":          "unit-daemon-role-alias",
		"TXING_IOT_CERT_FILE":           "/home/txing/.config/txing/unit-daemon/certificate.pem.crt",
		"TXING_IOT_PRIVATE_KEY_FILE":    "/home/txing/.config/txing/unit-daemon/private.pem.key",
		"TXING_IOT_ROOT_CA_FILE":        "/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem",
	}
}

func runtimeConfigFromArgs(t *testing.T, args ...string) RuntimeConfig {
	t.Helper()
	cli, err := ParseCLI(args)
	if err != nil {
		t.Fatalf("parse cli: %v", err)
	}
	config, err := RuntimeConfigFromSources(cli, map[string]string{}, testFileEnv())
	if err != nil {
		t.Fatalf("runtime config: %v", err)
	}
	return config
}

func TestCLIReportsDaemonBuildVersion(t *testing.T) {
	cli, err := ParseCLI([]string{"--version"})
	if err != nil {
		t.Fatalf("parse cli: %v", err)
	}
	if !cli.ShowVersion {
		t.Fatalf("expected version flag to be set")
	}
	if DaemonVersion == "" || DaemonVersion != packageVersion {
		t.Fatalf("unexpected daemon version %q", DaemonVersion)
	}
}

func TestParseEnvFileWithoutShellExecution(t *testing.T) {
	parsed, err := ParseEnvFileContents(`
		# comment
		TXING_THING_ID=unit-local
		AWS_REGION="eu-central-1"
		TXING_IOT_ROLE_ALIAS='alias-name'
		EMPTY=
	`)
	if err != nil {
		t.Fatalf("parse env file: %v", err)
	}
	if parsed["TXING_THING_ID"] != "unit-local" || parsed["AWS_REGION"] != "eu-central-1" || parsed["TXING_IOT_ROLE_ALIAS"] != "alias-name" || parsed["EMPTY"] != "" {
		t.Fatalf("unexpected parsed env: %#v", parsed)
	}
	if _, err := ParseEnvFileContents("export TXING_THING_ID=unit-local"); err == nil {
		t.Fatalf("expected export syntax to be rejected")
	}
	if _, err := ParseEnvFileContents("$(echo bad)"); err == nil {
		t.Fatalf("expected shell syntax to be rejected")
	}
}

func TestDaemonEnvTemplateContainsForwardRuntimeDefaults(t *testing.T) {
	if DefaultDaemonEnvTemplate == "" {
		t.Fatalf("expected daemon env template to load")
	}
	parsed, err := ParseEnvFileContents(DefaultDaemonEnvTemplate)
	if err != nil {
		t.Fatalf("parse daemon env template: %v", err)
	}
	requireTemplate := func(key, value string) {
		t.Helper()
		if parsed[key] != value {
			t.Fatalf("expected %s=%q, got %q", key, value, parsed[key])
		}
	}
	requireTemplate("TXING_DAEMON_CAPABILITIES", "board,mcp,video")
	requireTemplate("TXING_CAPABILITY_TTL_SECONDS", "150")
	requireTemplate("TXING_HEARTBEAT_SECONDS", "60")
	requireTemplate("TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH", DefaultBoardVideoBridgeSocket)
	requireTemplate("TXING_HARDWARE_WORKER_SOCKET_PATH", DefaultHardwareSocketPath)
	requireTemplate("TXING_HARDWARE_WORKER_TIMEOUT_MS", "700")
	requireTemplate("TXING_KVS_PREFER_IPV6", "true")
	requireTemplate("TXING_KVS_DISABLE_IPV4_TURN", "false")
	requireTemplate("TXING_MOTOR_ENABLED", "true")
	requireTemplate("TXING_MOTOR_PWM_SYSFS_ROOT", "/sys/class/pwm")
	requireTemplate("TXING_MOTOR_WATCHDOG_TIMEOUT_MS", "5000")
	for _, forbidden := range []string{"export TXING_", "export AWS_REGION", "TXING_KVS_MASTER_COMMAND", "TXING_MCP_WEBRTC_SOCKET_PATH", "AWS_DEFAULT_REGION", "TXING_BOARD_VIDEO_REGION", "\nBOARD_DRIVE_", "\nBOARD_VIDEO_"} {
		if strings.Contains(DefaultDaemonEnvTemplate, forbidden) {
			t.Fatalf("template contains forbidden text %q", forbidden)
		}
	}
}

func TestLoadsEnvFileFromConfigDir(t *testing.T) {
	configDir := t.TempDir()
	envFile := filepath.Join(configDir, DefaultEnvFileName)
	if err := os.WriteFile(envFile, []byte("TXING_THING_ID=unit-local\nAWS_REGION=eu-central-1\n"), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	cli, err := ParseCLI(nil)
	if err != nil {
		t.Fatalf("parse cli: %v", err)
	}
	loaded, err := LoadEnvFileForCLI(cli, map[string]string{"TXING_DAEMON_CONFIG_DIR": configDir})
	if err != nil {
		t.Fatalf("load env file: %v", err)
	}
	if loaded.Path != envFile || loaded.Values["TXING_THING_ID"] != "unit-local" {
		t.Fatalf("unexpected loaded env file: %#v", loaded)
	}
}

func TestLoadsEnvFileFromXDGThenHome(t *testing.T) {
	root := t.TempDir()
	xdgEnvFile := filepath.Join(root, "xdg", DefaultConfigSubdir, DefaultEnvFileName)
	homeEnvFile := filepath.Join(root, "home", ".config", DefaultConfigSubdir, DefaultEnvFileName)
	if err := os.MkdirAll(filepath.Dir(xdgEnvFile), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(homeEnvFile), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(xdgEnvFile, []byte("TXING_THING_ID=from-xdg\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(homeEnvFile, []byte("TXING_THING_ID=from-home\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	cli, _ := ParseCLI(nil)
	loaded, err := LoadEnvFileForCLI(cli, map[string]string{
		"XDG_CONFIG_HOME": filepath.Join(root, "xdg"),
		"HOME":            filepath.Join(root, "home"),
	})
	if err != nil {
		t.Fatalf("load xdg env file: %v", err)
	}
	if loaded.Path != xdgEnvFile || loaded.Values["TXING_THING_ID"] != "from-xdg" {
		t.Fatalf("unexpected xdg load: %#v", loaded)
	}
	loaded, err = LoadEnvFileForCLI(cli, map[string]string{"HOME": filepath.Join(root, "home")})
	if err != nil {
		t.Fatalf("load home env file: %v", err)
	}
	if loaded.Path != homeEnvFile || loaded.Values["TXING_THING_ID"] != "from-home" {
		t.Fatalf("unexpected home load: %#v", loaded)
	}
}

func TestColocatedCertPathsDefaultToEnvFileDirectory(t *testing.T) {
	fileEnv := testFileEnv()
	delete(fileEnv, "TXING_IOT_CERT_FILE")
	delete(fileEnv, "TXING_IOT_PRIVATE_KEY_FILE")
	delete(fileEnv, "TXING_IOT_ROOT_CA_FILE")
	cli, err := ParseCLI([]string{"--client-id", "unit-local-daemon-test"})
	if err != nil {
		t.Fatalf("parse cli: %v", err)
	}
	config, err := RuntimeConfigFromSourcesWithEnvFileDir(cli, map[string]string{}, fileEnv, "/home/txing/.config/txing/unit-daemon")
	if err != nil {
		t.Fatalf("runtime config: %v", err)
	}
	if config.IoTCertFile != "/home/txing/.config/txing/unit-daemon/certificate.pem.crt" {
		t.Fatalf("unexpected cert file %q", config.IoTCertFile)
	}
	if config.IoTPrivateKeyFile != "/home/txing/.config/txing/unit-daemon/private.pem.key" {
		t.Fatalf("unexpected private key file %q", config.IoTPrivateKeyFile)
	}
	if config.IoTRootCAFile != "/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem" {
		t.Fatalf("unexpected root CA file %q", config.IoTRootCAFile)
	}
}

func TestConfigPrecedenceIsCLIThenProcessEnvThenEnvFileThenDefaults(t *testing.T) {
	fileEnv := map[string]string{
		"TXING_THING_ID":                "from-file",
		"AWS_REGION":                    "from-file",
		"TXING_IOT_ENDPOINT":            "file.iot.eu-central-1.amazonaws.com",
		"TXING_IOT_CREDENTIAL_ENDPOINT": "file.credentials.iot.eu-central-1.amazonaws.com",
		"TXING_IOT_ROLE_ALIAS":          "file-alias",
		"TXING_IOT_CERT_FILE":           "/file/cert.pem",
		"TXING_IOT_PRIVATE_KEY_FILE":    "/file/private.key",
		"TXING_IOT_ROOT_CA_FILE":        "/file/ca.pem",
		"TXING_HEARTBEAT_SECONDS":       "30",
	}
	processEnv := map[string]string{
		"TXING_THING_ID":     "from-process",
		"TXING_IOT_ENDPOINT": "process.iot.eu-central-1.amazonaws.com",
	}
	ttl := uint64(120)
	cli := CLI{ThingID: "from-cli", ClientID: "from-cli-daemon-test", CapabilityTTLSeconds: &ttl}
	config, err := RuntimeConfigFromSources(cli, processEnv, fileEnv)
	if err != nil {
		t.Fatalf("runtime config: %v", err)
	}
	if config.ThingID != "from-cli" || config.IoTEndpoint != "process.iot.eu-central-1.amazonaws.com" || config.AWSRegion != "from-file" {
		t.Fatalf("precedence mismatch: %#v", config)
	}
	if config.CapabilityTTL != 120*time.Second || config.Heartbeat != 30*time.Second {
		t.Fatalf("duration mismatch: ttl=%s heartbeat=%s", config.CapabilityTTL, config.Heartbeat)
	}
	if config.KVSMasterCommand != DefaultKVSMasterCommand || config.BoardVideoBridgeSocketPath != DefaultBoardVideoBridgeSocket {
		t.Fatalf("default mismatch: %#v", config)
	}
	if config.VideoRegion != "from-file" || config.VideoChannelName != "from-cli-board-video" {
		t.Fatalf("video config mismatch: %#v", config)
	}
	if !reflect.DeepEqual(config.Capabilities, []string{BoardCapability, MCPCapability, VideoCapability}) {
		t.Fatalf("capabilities mismatch: %#v", config.Capabilities)
	}
}

func TestCloudWatchConfigUsesPrecedenceAndDefaults(t *testing.T) {
	fileEnv := testFileEnv()
	fileEnv["TXING_CLOUDWATCH_LOG_GROUP"] = "txing/town-file/rig-file/unit-local"
	fileEnv["TXING_CLOUDWATCH_LOG_STREAM"] = "daemon/file"
	fileEnv["TXING_CLOUDWATCH_LOG_LEVEL"] = "debug"
	fileEnv["TXING_CLOUDWATCH_LOG_RETENTION_DAYS"] = "7"
	retention := int32(30)
	cli := CLI{
		ClientID:                   "unit-local-daemon-test",
		CloudWatchLogGroup:         "txing/town-cli/rig-cli/unit-local",
		CloudWatchLogRetentionDays: &retention,
	}
	config, err := RuntimeConfigFromSources(cli, map[string]string{"TXING_CLOUDWATCH_LOG_STREAM": "daemon/process"}, fileEnv)
	if err != nil {
		t.Fatalf("runtime config: %v", err)
	}
	expected := &CloudWatchLogConfig{
		LogGroup:      "txing/town-cli/rig-cli/unit-local",
		LogStream:     "daemon/process",
		Level:         CloudWatchDebug,
		RetentionDays: 30,
	}
	if !reflect.DeepEqual(config.CloudWatchLogging, expected) {
		t.Fatalf("cloudwatch mismatch: %#v", config.CloudWatchLogging)
	}
}

func TestCLIDefaultsToDeclaredUnitCapabilities(t *testing.T) {
	config := runtimeConfigFromArgs(t)
	if config.ThingID != "unit-local" {
		t.Fatalf("thing id mismatch: %q", config.ThingID)
	}
	if !reflect.DeepEqual(config.Capabilities, []string{BoardCapability, MCPCapability, VideoCapability}) {
		t.Fatalf("capabilities mismatch: %#v", config.Capabilities)
	}
	if config.CapabilityTTL != 150*time.Second || config.Heartbeat != 60*time.Second {
		t.Fatalf("duration mismatch")
	}
	if config.VideoChannelName != "unit-local-board-video" || config.HardwareWorkerSocketPath != DefaultHardwareSocketPath {
		t.Fatalf("default runtime config mismatch: %#v", config)
	}
	if !strings.HasPrefix(config.ClientID, "unit-local-daemon-") {
		t.Fatalf("client id prefix mismatch: %q", config.ClientID)
	}
}

func TestConfigValidationFailures(t *testing.T) {
	cli, _ := ParseCLI(nil)
	if _, err := RuntimeConfigFromSources(cli, map[string]string{}, map[string]string{}); err == nil {
		t.Fatalf("expected missing production connection values to fail")
	}
	if _, err := RuntimeConfigFromSources(CLI{CapabilityTTLSeconds: ptrU64(60), HeartbeatSeconds: ptrU64(60)}, map[string]string{}, testFileEnv()); err == nil {
		t.Fatalf("expected heartbeat >= ttl to fail")
	}
	if _, err := RuntimeConfigFromSources(CLI{Capabilities: []string{"camera"}}, map[string]string{}, testFileEnv()); err == nil {
		t.Fatalf("expected unsupported capability to fail")
	}
	if _, err := RuntimeConfigFromSources(CLI{ClientID: "other-client"}, map[string]string{}, testFileEnv()); err == nil {
		t.Fatalf("expected invalid client id to fail")
	}
	env := testFileEnv()
	env["TXING_IOT_ENDPOINT"] = "https://example.iot.eu-central-1.amazonaws.com:443"
	if _, err := RuntimeConfigFromSources(CLI{}, map[string]string{}, env); err == nil {
		t.Fatalf("expected endpoint with scheme or port to fail")
	}
}

func TestDefaultClientIDSanitizesThingName(t *testing.T) {
	if got := defaultClientID("Unit Local!", 42); got != "Unit-Local-daemon-42" {
		t.Fatalf("default client id mismatch: %q", got)
	}
}

func TestMQTTMTLSUsesDirectTLSPort(t *testing.T) {
	if MQTTPort != 8883 {
		t.Fatalf("unexpected MQTT port: %d", MQTTPort)
	}
}

func ptrU64(value uint64) *uint64 {
	return &value
}
