package catalog

import "testing"

func TestReconstructsRedconRulesFromSSMLeafParameters(t *testing.T) {
	record, err := ReconstructTypeRecord([][2]string{
		{"/txing/town/raspi/power/thingType", "power"},
		{"/txing/town/raspi/power/capabilities", "sparkplug,ble,power"},
		{"/txing/town/raspi/power/redconCommandLevels", "4,3"},
		{"/txing/town/raspi/power/redconRules/4", "sparkplug,ble"},
		{"/txing/town/raspi/power/redconRules/3", "sparkplug,ble,power"},
		{"/txing/town/raspi/cyberbrick/redconMetricRules/1", "mavlinkArmed"},
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
	assertStrings(t, record.RedconMetricRules[1], []string{"mavlinkArmed"})
}

func TestReconstructsTbotMavlinkArmingRule(t *testing.T) {
	record, err := ReconstructTypeRecord([][2]string{
		{"/txing/town/raspi/tbot/thingType", "tbot"},
		{"/txing/town/raspi/tbot/capabilities", "sparkplug,thread,power,board,mavlink,video"},
		{"/txing/town/raspi/tbot/redconCommandLevels", "4,3,2,1"},
		{"/txing/town/raspi/tbot/redconRules/2", "sparkplug,thread,power,board,mavlink"},
		{"/txing/town/raspi/tbot/redconRules/1", "sparkplug,thread,power,board,mavlink,video"},
		{"/txing/town/raspi/tbot/redconMetricRules/1", "mavlinkArmed"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if record.ThingType != "tbot" {
		t.Fatalf("thingType = %s", record.ThingType)
	}
	assertStrings(t, record.RedconRules[2], []string{"sparkplug", "thread", "power", "board", "mavlink"})
	assertStrings(t, record.RedconMetricRules[1], []string{"mavlinkArmed"})
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
