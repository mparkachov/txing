package daemon

import "fmt"

func BuildCapabilityStateTopic(thingName string) (string, error) {
	if err := validateTopicSegment(thingName, "thing-id"); err != nil {
		return "", err
	}
	return fmt.Sprintf("txings/%s/capability/v2/state", thingName), nil
}

func BuildMCPTopicRoot(thingName string) (string, error) {
	if err := validateTopicSegment(thingName, "thing-id"); err != nil {
		return "", err
	}
	return fmt.Sprintf("txings/%s/mcp", thingName), nil
}

func BuildMCPDescriptorTopic(thingName string) (string, error) {
	root, err := BuildMCPTopicRoot(thingName)
	if err != nil {
		return "", err
	}
	return root + "/descriptor", nil
}

func BuildMCPStatusTopic(thingName string) (string, error) {
	root, err := BuildMCPTopicRoot(thingName)
	if err != nil {
		return "", err
	}
	return root + "/status", nil
}

func BuildVideoTopicRoot(thingName string) (string, error) {
	if err := validateTopicSegment(thingName, "thing-id"); err != nil {
		return "", err
	}
	return fmt.Sprintf("txings/%s/video", thingName), nil
}

func BuildVideoDescriptorTopic(thingName string) (string, error) {
	root, err := BuildVideoTopicRoot(thingName)
	if err != nil {
		return "", err
	}
	return root + "/descriptor", nil
}

func BuildVideoStatusTopic(thingName string) (string, error) {
	root, err := BuildVideoTopicRoot(thingName)
	if err != nil {
		return "", err
	}
	return root + "/status", nil
}

func BuildMCPSessionC2SSubscription(thingName string) (string, error) {
	root, err := BuildMCPTopicRoot(thingName)
	if err != nil {
		return "", err
	}
	return root + "/session/+/c2s", nil
}

func BuildMCPSessionS2CTopic(thingName, sessionID string) (string, error) {
	if err := validateTopicSegment(sessionID, "mcp-session-id"); err != nil {
		return "", err
	}
	root, err := BuildMCPTopicRoot(thingName)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s/session/%s/s2c", root, sessionID), nil
}

func ParseMCPSessionC2STopic(thingName, topic string) (string, bool) {
	root, err := BuildMCPTopicRoot(thingName)
	if err != nil {
		return "", false
	}
	prefix := root + "/session/"
	if len(topic) <= len(prefix)+len("/c2s") || topic[:len(prefix)] != prefix {
		return "", false
	}
	suffix := topic[len(prefix):]
	const tail = "/c2s"
	if len(suffix) <= len(tail) || suffix[len(suffix)-len(tail):] != tail {
		return "", false
	}
	sessionID := suffix[:len(suffix)-len(tail)]
	if err := validateTopicSegment(sessionID, "mcp-session-id"); err != nil {
		return "", false
	}
	return sessionID, true
}

func BuildBoardShadowUpdateTopic(thingName string) (string, error) {
	if err := validateTopicSegment(thingName, "thing-id"); err != nil {
		return "", err
	}
	return fmt.Sprintf("$aws/things/%s/shadow/name/%s/update", thingName, BoardShadowName), nil
}

func BuildMCPShadowUpdateTopic(thingName string) (string, error) {
	if err := validateTopicSegment(thingName, "thing-id"); err != nil {
		return "", err
	}
	return fmt.Sprintf("$aws/things/%s/shadow/name/%s/update", thingName, MCPShadowName), nil
}

func BuildVideoShadowUpdateTopic(thingName string) (string, error) {
	if err := validateTopicSegment(thingName, "thing-id"); err != nil {
		return "", err
	}
	return fmt.Sprintf("$aws/things/%s/shadow/name/%s/update", thingName, VideoShadowName), nil
}
