package thread

import (
	"context"
	"encoding/hex"
	"fmt"
	"net"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

type OTCTLRunner interface {
	Run(ctx context.Context, path string, args ...string) ([]byte, error)
}

type execOTCTLRunner struct{}

func (execOTCTLRunner) Run(ctx context.Context, path string, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, path, args...).CombinedOutput()
}

// OTCTLSRPDiscoverer reads the local OTBR SRP registry through ot-ctl. OTBR
// does not expose its SRP registry as a host DNS service, and mDNS publication
// is deliberately not required for rig-local Thread discovery.
type OTCTLSRPDiscoverer struct {
	Path    string
	Domain  string
	Runner  OTCTLRunner
	Timeout time.Duration
	NowMS   func() uint64
	NextSeq func() uint64
}

func (d OTCTLSRPDiscoverer) Discover(ctx context.Context) ([]Endpoint, error) {
	path := strings.TrimSpace(d.Path)
	if path == "" {
		path = "ot-ctl"
	}
	runner := d.Runner
	if runner == nil {
		runner = execOTCTLRunner{}
	}
	runCtx := ctx
	cancel := func() {}
	if d.Timeout > 0 {
		runCtx, cancel = context.WithTimeout(ctx, d.Timeout)
	}
	defer cancel()
	output, err := runner.Run(runCtx, path, "srp", "server", "service")
	if err != nil {
		return nil, fmt.Errorf("ot-ctl srp server service: %w: %s", err, strings.TrimSpace(string(output)))
	}
	return ParseOTCTLSRPServices(string(output), d.Domain, d.NowMS, d.NextSeq)
}

type otctlSRPService struct {
	instance string
	fields   map[string]string
}

func ParseOTCTLSRPServices(output string, domain string, nowMS func() uint64, nextSeq func() uint64) ([]Endpoint, error) {
	domain = strings.Trim(strings.TrimSpace(domain), ".")
	if domain == "" {
		domain = DefaultDomain
	}
	now := NowMS
	if nowMS != nil {
		now = nowMS
	}
	next := func() uint64 { return 0 }
	if nextSeq != nil {
		next = nextSeq
	}

	expectedSuffix := "." + ServiceName + "." + domain + "."
	services := []otctlSRPService{}
	var current *otctlSRPService
	flush := func() {
		if current == nil {
			return
		}
		services = append(services, *current)
		current = nil
	}

	for _, rawLine := range strings.Split(output, "\n") {
		if strings.HasPrefix(rawLine, " ") || strings.HasPrefix(rawLine, "\t") {
			if current == nil {
				continue
			}
			key, value, ok := strings.Cut(strings.TrimSpace(rawLine), ":")
			if ok {
				current.fields[strings.ToLower(strings.TrimSpace(key))] = strings.TrimSpace(value)
			}
			continue
		}

		line := strings.TrimSpace(rawLine)
		if !strings.HasSuffix(line, ".") || line == "Done" {
			continue
		}
		flush()
		current = &otctlSRPService{instance: line, fields: map[string]string{}}
	}
	flush()

	endpoints := []Endpoint{}
	for _, service := range services {
		if !strings.HasSuffix(service.instance, expectedSuffix) || service.fields["deleted"] == "true" {
			continue
		}
		endpoint, ok, err := otctlServiceEndpoint(service, now(), next())
		if err != nil {
			return nil, err
		}
		if ok {
			endpoints = append(endpoints, endpoint)
		}
	}
	SortEndpoints(endpoints)
	return endpoints, nil
}

func otctlServiceEndpoint(service otctlSRPService, observedAtMS uint64, seq uint64) (Endpoint, bool, error) {
	txt, err := parseOTCTLTXT(service.fields["txt"])
	if err != nil {
		return Endpoint{}, false, fmt.Errorf("parse SRP TXT for %s: %w", service.instance, err)
	}
	if txt["type"] != DeviceType {
		return Endpoint{}, false, nil
	}
	port, err := strconv.ParseUint(service.fields["port"], 10, 16)
	if err != nil || port == 0 {
		return Endpoint{}, false, fmt.Errorf("parse SRP port for %s", service.instance)
	}
	addresses := parseOTCTLAddresses(service.fields["addresses"])
	endpoint, ok := NewEndpoint(service.instance, service.fields["host"], uint16(port), txt, addresses, observedAtMS, seq)
	if !ok {
		return Endpoint{}, false, fmt.Errorf("invalid active SRP service %s", service.instance)
	}
	return endpoint, true, nil
}

func parseOTCTLTXT(value string) (map[string]string, error) {
	txt := map[string]string{}
	value = strings.TrimSpace(value)
	if value == "" || value == "[]" {
		return txt, nil
	}
	if !strings.HasPrefix(value, "[") || !strings.HasSuffix(value, "]") {
		return nil, fmt.Errorf("expected bracketed TXT data")
	}
	entries := strings.Split(strings.TrimSuffix(strings.TrimPrefix(value, "["), "]"), ",")
	for _, entry := range entries {
		key, encoded, ok := strings.Cut(strings.TrimSpace(entry), "=")
		if !ok || strings.TrimSpace(key) == "" {
			return nil, fmt.Errorf("invalid TXT entry %q", entry)
		}
		decoded, err := hex.DecodeString(strings.TrimSpace(encoded))
		if err != nil {
			return nil, fmt.Errorf("decode TXT entry %q: %w", entry, err)
		}
		txt[strings.ToLower(strings.TrimSpace(key))] = string(decoded)
	}
	return txt, nil
}

func parseOTCTLAddresses(value string) []net.IP {
	value = strings.TrimSpace(value)
	value = strings.TrimSuffix(strings.TrimPrefix(value, "["), "]")
	addresses := []net.IP{}
	for _, rawAddress := range strings.Split(value, ",") {
		if address := net.ParseIP(strings.TrimSpace(rawAddress)); address != nil {
			addresses = append(addresses, address)
		}
	}
	return addresses
}
