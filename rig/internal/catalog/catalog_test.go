package catalog

import "testing"

func TestReconstructsRedconRulesFromSSMLeafParameters(t *testing.T) {
	record, err := ReconstructTypeRecord([][2]string{
		{"/txing/town/raspi/power/thingType", "power"},
		{"/txing/town/raspi/power/capabilities", "sparkplug,ble,power"},
		{"/txing/town/raspi/power/redconCommandLevels", "4,3"},
		{"/txing/town/raspi/power/redconRules/4", "sparkplug,ble"},
		{"/txing/town/raspi/power/redconRules/3", "sparkplug,ble,power"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if record.ThingType != "power" {
		t.Fatalf("thingType = %s", record.ThingType)
	}
	assertStrings(t, record.Capabilities, []string{"sparkplug", "ble", "power"})
	if len(record.RedconCommandLevels) != 2 || record.RedconCommandLevels[0] != 4 || record.RedconCommandLevels[1] != 3 {
		t.Fatalf("redcon levels = %#v", record.RedconCommandLevels)
	}
	assertStrings(t, record.RedconRules[3], []string{"sparkplug", "ble", "power"})
}

func assertStrings(t *testing.T, got []string, want []string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("len = %d, want %d", len(got), len(want))
	}
	for index := range want {
		if got[index] != want[index] {
			t.Fatalf("got[%d] = %q, want %q", index, got[index], want[index])
		}
	}
}
