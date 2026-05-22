package catalog

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

type TypeCatalogDevice struct {
	ThingType           string
	Capabilities        []string
	RedconCommandLevels []uint8
	RedconRules         map[uint8][]string
}

func (d TypeCatalogDevice) ToInventoryDevice(thingName string) protocol.InventoryDevice {
	return d.ToInventoryDeviceWithCapabilities(thingName, append([]string(nil), d.Capabilities...))
}

func (d TypeCatalogDevice) ToInventoryDeviceWithCapabilities(thingName string, capabilities []string) protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           thingName,
		ThingType:           d.ThingType,
		Capabilities:        capabilities,
		RedconCommandLevels: append([]uint8(nil), d.RedconCommandLevels...),
		RedconRules:         cloneRules(d.RedconRules),
	}
}

func ReconstructTypeRecord(parameters [][2]string) (TypeCatalogDevice, error) {
	var record TypeCatalogDevice
	record.RedconRules = map[uint8][]string{}
	for _, parameter := range parameters {
		name := parameter[0]
		value := parameter[1]
		parts := strings.Split(name, "/")
		leaf := ""
		if len(parts) > 0 {
			leaf = parts[len(parts)-1]
		}
		switch leaf {
		case "thingType":
			record.ThingType = value
		case "capabilities":
			items, err := ParseStringList(value)
			if err != nil {
				return TypeCatalogDevice{}, err
			}
			record.Capabilities = items
		case "redconCommandLevels":
			levels, err := parseRedconLevels(value)
			if err != nil {
				return TypeCatalogDevice{}, err
			}
			record.RedconCommandLevels = levels
		default:
			before, after, ok := strings.Cut(name, "/redconRules/")
			_ = before
			if !ok {
				continue
			}
			levelText := strings.Split(after, "/")[0]
			level, err := parseRedconLevel(levelText)
			if err != nil {
				return TypeCatalogDevice{}, err
			}
			items, err := ParseStringList(value)
			if err != nil {
				return TypeCatalogDevice{}, err
			}
			record.RedconRules[level] = items
		}
	}
	if err := ValidateTypeRecord(record); err != nil {
		return TypeCatalogDevice{}, err
	}
	return record, nil
}

func ValidateTypeRecord(record TypeCatalogDevice) error {
	if strings.TrimSpace(record.ThingType) == "" {
		return fmt.Errorf("thingType must not be empty")
	}
	if !contains(record.Capabilities, "sparkplug") {
		return fmt.Errorf("capabilities must include sparkplug")
	}
	capabilitySet := map[string]struct{}{}
	for _, capability := range record.Capabilities {
		capabilitySet[capability] = struct{}{}
	}
	for _, level := range record.RedconCommandLevels {
		if err := protocol.ValidateRedcon(level, "redconCommandLevels"); err != nil {
			return err
		}
	}
	for level, capabilities := range record.RedconRules {
		if err := protocol.ValidateRedcon(level, "redconRules"); err != nil {
			return err
		}
		if len(capabilities) == 0 {
			return fmt.Errorf("redconRules.%d must not be empty", level)
		}
		for _, capability := range capabilities {
			if _, ok := capabilitySet[capability]; !ok {
				return fmt.Errorf("redconRules.%d references unknown capability %s", level, capability)
			}
		}
	}
	return nil
}

func ParseStringList(value string) ([]string, error) {
	if strings.TrimSpace(value) == "" {
		return []string{}, nil
	}
	raw := strings.Split(value, ",")
	items := make([]string, 0, len(raw))
	for _, item := range raw {
		text := strings.TrimSpace(item)
		if text == "" {
			return nil, fmt.Errorf("list leaf contains an empty item")
		}
		items = append(items, text)
	}
	return items, nil
}

func parseRedconLevels(value string) ([]uint8, error) {
	items, err := ParseStringList(value)
	if err != nil {
		return nil, err
	}
	levels := make([]uint8, 0, len(items))
	for _, item := range items {
		level, err := parseRedconLevel(item)
		if err != nil {
			return nil, err
		}
		levels = append(levels, level)
	}
	return levels, nil
}

func parseRedconLevel(value string) (uint8, error) {
	parsed, err := strconv.ParseUint(value, 10, 8)
	if err != nil {
		return 0, err
	}
	level := uint8(parsed)
	if err := protocol.ValidateRedcon(level, "redcon"); err != nil {
		return 0, err
	}
	return level, nil
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func cloneRules(input map[uint8][]string) map[uint8][]string {
	output := make(map[uint8][]string, len(input))
	for key, value := range input {
		output[key] = append([]string(nil), value...)
	}
	return output
}
