package thread

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"net"
	"os"
	"strings"
	"time"

	"golang.org/x/net/dns/dnsmessage"
)

type DNSResolver interface {
	LookupPTR(ctx context.Context, name string) ([]string, error)
	LookupSRV(ctx context.Context, name string) ([]SRVRecord, error)
	LookupTXT(ctx context.Context, name string) ([]string, error)
	LookupAAAA(ctx context.Context, name string) ([]net.IP, error)
}

type SRVRecord struct {
	Target string
	Port   uint16
}

type Discoverer struct {
	Resolver DNSResolver
	Domain   string
	NowMS    func() uint64
	NextSeq  func() uint64
}

func (d Discoverer) Discover(ctx context.Context) ([]Endpoint, error) {
	resolver := d.Resolver
	if resolver == nil {
		resolver = NewSystemDNSResolver(2 * time.Second)
	}
	now := NowMS
	if d.NowMS != nil {
		now = d.NowMS
	}
	nextSeq := func() uint64 { return 0 }
	if d.NextSeq != nil {
		nextSeq = d.NextSeq
	}

	serviceFQDN := BuildServiceFQDN(d.Domain)
	instances, err := resolver.LookupPTR(ctx, serviceFQDN)
	if err != nil {
		return nil, err
	}
	endpoints := []Endpoint{}
	for _, instance := range instances {
		txtStrings, err := resolver.LookupTXT(ctx, instance)
		if err != nil {
			continue
		}
		txt := ParseTXT(txtStrings)
		if txt["type"] != DeviceType {
			continue
		}
		srvRecords, err := resolver.LookupSRV(ctx, instance)
		if err != nil {
			continue
		}
		for _, srv := range srvRecords {
			addresses, err := resolver.LookupAAAA(ctx, srv.Target)
			if err != nil || len(addresses) == 0 {
				continue
			}
			if endpoint, ok := NewEndpoint(instance, srv.Target, srv.Port, txt, addresses, now(), nextSeq()); ok {
				endpoints = append(endpoints, endpoint)
			}
		}
	}
	SortEndpoints(endpoints)
	return endpoints, nil
}

type SystemDNSResolver struct {
	Servers []string
	Timeout time.Duration
	Dialer  net.Dialer
}

func NewSystemDNSResolver(timeout time.Duration) *SystemDNSResolver {
	return &SystemDNSResolver{
		Servers: readResolverServers("/etc/resolv.conf"),
		Timeout: timeout,
	}
}

func (r *SystemDNSResolver) LookupPTR(ctx context.Context, name string) ([]string, error) {
	resources, err := r.query(ctx, name, dnsmessage.TypePTR)
	if err != nil {
		return nil, err
	}
	values := []string{}
	for _, resource := range resources {
		body, ok := resource.Body.(*dnsmessage.PTRResource)
		if ok {
			values = append(values, body.PTR.String())
		}
	}
	return values, nil
}

func (r *SystemDNSResolver) LookupSRV(ctx context.Context, name string) ([]SRVRecord, error) {
	resources, err := r.query(ctx, name, dnsmessage.TypeSRV)
	if err != nil {
		return nil, err
	}
	values := []SRVRecord{}
	for _, resource := range resources {
		body, ok := resource.Body.(*dnsmessage.SRVResource)
		if ok {
			values = append(values, SRVRecord{Target: body.Target.String(), Port: body.Port})
		}
	}
	return values, nil
}

func (r *SystemDNSResolver) LookupTXT(ctx context.Context, name string) ([]string, error) {
	resources, err := r.query(ctx, name, dnsmessage.TypeTXT)
	if err != nil {
		return nil, err
	}
	values := []string{}
	for _, resource := range resources {
		body, ok := resource.Body.(*dnsmessage.TXTResource)
		if ok {
			values = append(values, body.TXT...)
		}
	}
	return values, nil
}

func (r *SystemDNSResolver) LookupAAAA(ctx context.Context, name string) ([]net.IP, error) {
	resources, err := r.query(ctx, name, dnsmessage.TypeAAAA)
	if err != nil {
		return nil, err
	}
	values := []net.IP{}
	for _, resource := range resources {
		body, ok := resource.Body.(*dnsmessage.AAAAResource)
		if ok {
			values = append(values, net.IP(body.AAAA[:]))
		}
	}
	return values, nil
}

func (r *SystemDNSResolver) query(ctx context.Context, name string, qtype dnsmessage.Type) ([]dnsmessage.Resource, error) {
	servers := r.Servers
	if len(servers) == 0 {
		servers = []string{"127.0.0.1:53"}
	}
	timeout := r.Timeout
	if timeout <= 0 {
		timeout = 2 * time.Second
	}

	var lastErr error
	for _, server := range servers {
		query, id, err := buildDNSQuery(name, qtype)
		if err != nil {
			return nil, err
		}
		queryCtx, cancel := context.WithTimeout(ctx, timeout)
		resources, err := r.exchange(queryCtx, server, query, id)
		cancel()
		if err == nil {
			return resources, nil
		}
		lastErr = err
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("no DNS servers configured")
	}
	return nil, lastErr
}

func (r *SystemDNSResolver) exchange(ctx context.Context, server string, query []byte, id uint16) ([]dnsmessage.Resource, error) {
	conn, err := r.Dialer.DialContext(ctx, "udp", server)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(deadline)
	}
	if _, err := conn.Write(query); err != nil {
		return nil, err
	}
	buffer := make([]byte, 4096)
	n, err := conn.Read(buffer)
	if err != nil {
		return nil, err
	}
	var parser dnsmessage.Parser
	header, err := parser.Start(buffer[:n])
	if err != nil {
		return nil, err
	}
	if header.ID != id {
		return nil, fmt.Errorf("DNS response id mismatch")
	}
	if header.RCode != dnsmessage.RCodeSuccess {
		return nil, fmt.Errorf("DNS response code %s", header.RCode)
	}
	if err := parser.SkipAllQuestions(); err != nil {
		return nil, err
	}
	resources, err := parser.AllAnswers()
	if err != nil {
		return nil, err
	}
	return resources, nil
}

func buildDNSQuery(name string, qtype dnsmessage.Type) ([]byte, uint16, error) {
	dnsName, err := dnsmessage.NewName(ensureTrailingDot(name))
	if err != nil {
		return nil, 0, err
	}
	id := randomID()
	builder := dnsmessage.NewBuilder(nil, dnsmessage.Header{
		ID:               id,
		RecursionDesired: true,
	})
	builder.EnableCompression()
	if err := builder.StartQuestions(); err != nil {
		return nil, 0, err
	}
	if err := builder.Question(dnsmessage.Question{
		Name:  dnsName,
		Type:  qtype,
		Class: dnsmessage.ClassINET,
	}); err != nil {
		return nil, 0, err
	}
	payload, err := builder.Finish()
	if err != nil {
		return nil, 0, err
	}
	return payload, id, nil
}

func readResolverServers(path string) []string {
	payload, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	servers := []string{}
	for _, line := range strings.Split(string(payload), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 || fields[0] != "nameserver" {
			continue
		}
		host := fields[1]
		if strings.Contains(host, ":") {
			host = "[" + strings.Trim(host, "[]") + "]"
		}
		servers = append(servers, net.JoinHostPort(strings.Trim(host, "[]"), "53"))
	}
	return servers
}

func ensureTrailingDot(name string) string {
	name = strings.TrimSpace(name)
	if strings.HasSuffix(name, ".") {
		return name
	}
	return name + "."
}

func randomID() uint16 {
	var bytes [2]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return uint16(time.Now().UnixNano())
	}
	return binary.BigEndian.Uint16(bytes[:])
}
