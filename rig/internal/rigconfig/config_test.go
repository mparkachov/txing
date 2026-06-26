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

func writeTestConfigDir(t *testing.T) string {
	t.Helper()
	configDir := t.TempDir()
	env := []byte(`TXING_RIG_ID=rig-001
TXING_TOWN_ID=town-001
AWS_REGION=eu-central-1
TXING_IOT_ENDPOINT=example.iot
TXING_IOT_CREDENTIAL_ENDPOINT=example.credentials.iot
TXING_IOT_ROLE_ALIAS=txing-role
TXING_CLOUDWATCH_LOG_GROUP=txing/town-001/rig-001
`)
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
