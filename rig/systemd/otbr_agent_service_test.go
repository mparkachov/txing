package systemd_test

import (
	"os"
	"strings"
	"testing"
)

func TestOTBRAgentServiceTracksForegroundProcessWithBoundedRestart(t *testing.T) {
	unit := readFile(t, "otbr-agent.service")
	unitSection := section(t, unit, "Unit")
	serviceSection := section(t, unit, "Service")

	for _, setting := range []string{
		"ConditionPathExists=/usr/sbin/otbr-agent",
		"Requires=dbus.socket",
		"Wants=network-online.target",
		"After=dbus.socket network-online.target",
		"StartLimitIntervalSec=300",
		"StartLimitBurst=5",
	} {
		assertLine(t, unitSection, setting)
	}
	for _, setting := range []string{
		"Type=simple",
		"EnvironmentFile=-/etc/default/otbr-agent",
		"ExecStart=/usr/sbin/otbr-agent $OTBR_AGENT_OPTS",
		"KillMode=mixed",
		"Restart=on-failure",
		"RestartSec=10",
	} {
		assertLine(t, serviceSection, setting)
	}

	for _, forbidden := range []string{
		"/etc/init.d/otbr-agent",
		"RemainAfterExit",
		"PIDFile=",
		"Restart=always",
		"RestartPreventExitStatus=SIGKILL",
	} {
		if strings.Contains(unit, forbidden) {
			t.Fatalf("otbr-agent.service contains forbidden setting %q", forbidden)
		}
	}
}

func TestThreadConnectivityOnlyWeaklyDependsOnOTBR(t *testing.T) {
	dropIn := readFile(t, "txing-thread-connectivity.service.d/10-otbr-ordering.conf")
	unitSection := section(t, dropIn, "Unit")

	assertLine(t, unitSection, "Wants=otbr-agent.service")
	assertLine(t, unitSection, "After=otbr-agent.service")
	for _, forbidden := range []string{
		"Requires=otbr-agent.service",
		"BindsTo=otbr-agent.service",
		"PartOf=otbr-agent.service",
	} {
		if strings.Contains(dropIn, forbidden) {
			t.Fatalf("Thread connectivity OTBR ordering contains forbidden setting %q", forbidden)
		}
	}
}

func TestRigDocumentationCoversManualOTBRRolloutAndRollback(t *testing.T) {
	docs := readFile(t, "../../docs/components/rig.md")
	for _, required := range []string{
		"## OTBR Process Supervision",
		"/usr/sbin/otbr-agent",
		"/etc/default/otbr-agent",
		"rig/systemd/otbr-agent.service",
		"10-otbr-ordering.conf",
		"systemctl show otbr-agent.service",
		"systemctl kill --kill-whom=main --signal=SIGKILL otbr-agent.service",
		"! systemctl is-active --quiet otbr-agent.service",
		"systemctl reset-failed otbr-agent.service",
		"systemctl disable --now otbr-agent.service",
		"### Rollback",
		"ot-ctl srp server service",
	} {
		if !strings.Contains(docs, required) {
			t.Fatalf("rig documentation is missing %q", required)
		}
	}
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(contents)
}

func section(t *testing.T, contents string, name string) string {
	t.Helper()
	marker := "[" + name + "]"
	start := strings.Index(contents, marker)
	if start < 0 {
		t.Fatalf("missing %s section", marker)
	}
	rest := contents[start+len(marker):]
	if end := strings.Index(rest, "\n["); end >= 0 {
		rest = rest[:end]
	}
	return rest
}

func assertLine(t *testing.T, contents string, expected string) {
	t.Helper()
	for _, line := range strings.Split(contents, "\n") {
		if strings.TrimSpace(line) == expected {
			return
		}
	}
	t.Fatalf("missing setting %q", expected)
}
