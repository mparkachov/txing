package thread

import (
	"context"
	"fmt"
	"net"
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
		return nil, fmt.Errorf("DNS resolver is required")
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
