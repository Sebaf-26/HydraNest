package engine

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"testing"

	"github.com/wizier/airvault/internal/ios"
)

func TestAttachRemote(t *testing.T) {
	p := newTestPhone(t) // on USB only
	tailscale := netip.MustParseAddr("100.64.0.6")
	ctx := context.Background()

	if _, err := p.engine.AttachRemote(ctx, p.udid, "100.64.0.6"); !errors.Is(err, ErrRemoteUnreachable) {
		t.Fatalf("unreachable phone: %v", err)
	}

	p.muxer.ReachableAt(p.phone, tailscale)
	got, err := p.engine.AttachRemote(ctx, p.udid, "100.64.0.6")
	if err != nil || got.Present || got.Addr != tailscale {
		t.Fatalf("first attach = %+v, %v", got, err)
	}
	attached := 0
	devices, _ := p.engine.mux.Devices(ctx)
	for _, device := range devices {
		if device.UDID == string(p.udid) && device.Connection == ios.ConnectionNetwork {
			attached++
		}
	}
	if attached != 1 {
		t.Fatalf("network attachments = %d, want 1", attached)
	}

	// Already on the network: nothing more is sent.
	adds := p.muxer.AddDevices()
	if got, err := p.engine.AttachRemote(ctx, p.udid, "100.64.0.6"); err != nil || !got.Present {
		t.Fatalf("second attach = %+v, %v", got, err)
	}
	if p.muxer.AddDevices() != adds {
		t.Fatal("AddDevice sent for a phone already on the network")
	}
}

func TestAttachRemoteRejectsBadInput(t *testing.T) {
	p := newTestPhone(t)
	// No Tailscale here: MagicDNS must fail at once, not time out.
	saved := magicDNS
	magicDNS = &net.Resolver{PreferGo: true, Dial: func(context.Context, string, string) (net.Conn, error) {
		return nil, errors.New("no MagicDNS")
	}}
	t.Cleanup(func() { magicDNS = saved })
	if _, err := p.engine.AttachRemote(context.Background(), "../etc", "100.64.0.6"); err == nil {
		t.Fatal("invalid udid accepted")
	}
	if _, err := p.engine.AttachRemote(context.Background(), p.udid, "no-such-host.invalid"); !errors.Is(err, ErrRemoteResolve) {
		t.Fatalf("unresolvable name: %v", err)
	}
}

func TestResolveRemote(t *testing.T) {
	tests := map[string]string{
		"100.64.0.6":        "100.64.0.6",
		"::ffff:100.64.0.6": "100.64.0.6",
		"fd7a:115c:a1e0::1": "fd7a:115c:a1e0::1",
		"localhost":         "127.0.0.1",
	}
	for address, want := range tests {
		got, err := resolveRemote(context.Background(), address)
		if err != nil || got.String() != want {
			t.Errorf("resolveRemote(%q) = %v, %v; want %s", address, got, err, want)
		}
	}
}
