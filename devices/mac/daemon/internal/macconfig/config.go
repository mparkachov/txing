// Package macconfig loads the txing-mac-daemon runtime configuration.
// Resolution follows the rig daemon convention (rig/internal/rigconfig):
// process environment values take precedence over daemon.env values from
// the config directory.
package macconfig

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

const DefaultConfigSubdir = ".config/txing/mac-daemon"

type Config struct {
	ConfigDir         string
	ThingID           string
	IPCSocket         string
	InitialRedcon     uint8
	StateInterval     time.Duration
	HeartbeatInterval time.Duration
}

func Load(configDirOverride string) (Config, error) {
	configDir, err := resolveConfigDir(configDirOverride)
	if err != nil {
		return Config{}, err
	}
	values, err := readEnvFile(filepath.Join(configDir, "daemon.env"))
	if err != nil && !os.IsNotExist(err) {
		return Config{}, err
	}
	lookup := func(name string) string {
		if value := strings.TrimSpace(os.Getenv(name)); value != "" {
			return value
		}
		return strings.TrimSpace(values[name])
	}
	cfg := Config{
		ConfigDir:         configDir,
		ThingID:           lookup("TXING_THING_ID"),
		IPCSocket:         firstNonEmpty(lookup("TXING_RIG_IPC_SOCKET"), defaultIPCSocket()),
		InitialRedcon:     4,
		StateInterval:     secondsEnv(lookup("TXING_MAC_STATE_INTERVAL_SECONDS"), 30*time.Second),
		HeartbeatInterval: millisEnv(lookup("TXING_MAC_HEARTBEAT_INTERVAL_MS"), 10*time.Second),
	}
	if raw := lookup("TXING_MAC_INITIAL_REDCON"); raw != "" {
		level, err := strconv.ParseUint(raw, 10, 8)
		if err != nil || level < 1 || level > 4 {
			return Config{}, fmt.Errorf("TXING_MAC_INITIAL_REDCON must be an integer between 1 and 4, got %q", raw)
		}
		cfg.InitialRedcon = uint8(level)
	}
	if strings.TrimSpace(cfg.ThingID) == "" {
		return Config{}, fmt.Errorf("TXING_THING_ID is required (set it in %s or the environment)", filepath.Join(configDir, "daemon.env"))
	}
	if strings.ContainsAny(cfg.ThingID, "/#+") {
		return Config{}, fmt.Errorf("TXING_THING_ID must not contain MQTT topic separators or wildcards")
	}
	if cfg.StateInterval <= 0 || cfg.HeartbeatInterval <= 0 {
		return Config{}, fmt.Errorf("state and heartbeat intervals must be positive")
	}
	return cfg, nil
}

func resolveConfigDir(override string) (string, error) {
	if override != "" {
		return filepath.Abs(override)
	}
	if value := strings.TrimSpace(os.Getenv("TXING_MAC_CONFIG_DIR")); value != "" {
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
		return map[string]string{}, err
	}
	defer file.Close()
	values := map[string]string{}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
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

func secondsEnv(raw string, fallback time.Duration) time.Duration {
	if raw == "" {
		return fallback
	}
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || value <= 0 {
		return fallback
	}
	return time.Duration(value) * time.Second
}

func millisEnv(raw string, fallback time.Duration) time.Duration {
	if raw == "" {
		return fallback
	}
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || value <= 0 {
		return fallback
	}
	return time.Duration(value) * time.Millisecond
}
