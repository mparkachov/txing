package rigconfig

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoadDefaultsThreadCoAPTimeoutForSleepyEndDevices(t *testing.T) {
	t.Setenv("TXING_THREAD_COAP_TIMEOUT_MS", "")
	configDir := writeTestConfigDir(t)

	cfg, err := Load(configDir)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ThreadCoAPTimeout != 12*time.Second {
		t.Fatalf("ThreadCoAPTimeout = %s, want 12s", cfg.ThreadCoAPTimeout)
	}
}

func TestLoadDefaultsInventoryIntervalToFiveMinutes(t *testing.T) {
	t.Setenv("TXING_INVENTORY_INTERVAL_SECONDS", "")
	configDir := writeTestConfigDir(t)

	cfg, err := Load(configDir)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.InventoryInterval != 300*time.Second {
		t.Fatalf("InventoryInterval = %s, want 300s", cfg.InventoryInterval)
	}
}

func TestLoadDefaultsToManagerOnlyDaemonEnablement(t *testing.T) {
	configDir := writeTestConfigDir(t)

	cfg, err := Load(configDir)
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.SparkplugManagerEnabled {
		t.Fatal("SparkplugManagerEnabled = false, want true")
	}
	if cfg.BLEConnectivityEnabled {
		t.Fatal("BLEConnectivityEnabled = true, want false")
	}
	if cfg.ThreadConnectivityEnabled {
		t.Fatal("ThreadConnectivityEnabled = true, want false")
	}
	if cfg.BLENoRadio {
		t.Fatal("BLENoRadio = true, want false")
	}
}

func TestLoadDaemonEnablementAndBleNoRadioFromEnvFile(t *testing.T) {
	configDir := writeTestConfigDir(t, `TXING_SPARKPLUG_MANAGER_ENABLED=false
TXING_BLE_CONNECTIVITY_ENABLED=true
TXING_THREAD_CONNECTIVITY_ENABLED=true
TXING_BLE_NO_RADIO=true
`)

	cfg, err := Load(configDir)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SparkplugManagerEnabled {
		t.Fatal("SparkplugManagerEnabled = true, want false")
	}
	if !cfg.BLEConnectivityEnabled {
		t.Fatal("BLEConnectivityEnabled = false, want true")
	}
	if !cfg.ThreadConnectivityEnabled {
		t.Fatal("ThreadConnectivityEnabled = false, want true")
	}
	if !cfg.BLENoRadio {
		t.Fatal("BLENoRadio = false, want true")
	}
}

func writeTestConfigDir(t *testing.T, extraEnv ...string) string {
	t.Helper()
	extra := ""
	if len(extraEnv) > 0 {
		extra = extraEnv[0]
	}
	configDir := t.TempDir()
	env := []byte(`TXING_RIG_ID=rig-001
TXING_TOWN_ID=town-001
AWS_REGION=eu-central-1
TXING_IOT_ENDPOINT=example.iot
TXING_IOT_CREDENTIAL_ENDPOINT=example.credentials.iot
TXING_IOT_ROLE_ALIAS=txing-role
TXING_CLOUDWATCH_LOG_GROUP=txing/town-001/rig-001
` + extra)
	if err := os.WriteFile(filepath.Join(configDir, "daemon.env"), env, 0o600); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"certificate.pem.crt", "private.pem.key", "AmazonRootCA1.pem"} {
		if err := os.WriteFile(filepath.Join(configDir, name), []byte("test"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return configDir
}
