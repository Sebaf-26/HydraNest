package service

import (
	"context"
	"errors"
	"net/netip"
	"os"
	"path/filepath"
	"testing"

	"github.com/wizier/airvault/internal/domain"
	"github.com/wizier/airvault/internal/engine"
	"github.com/wizier/airvault/internal/ios/iostest"
	"github.com/wizier/airvault/internal/model"
)

func TestValidRemoteAddress(t *testing.T) {
	for _, address := range []string{"100.64.0.6", "fd7a:115c:a1e0::1", "iphone",
		"iphone.example.ts.net", "iphone.example.ts.net."} {
		if !validRemoteAddress(address) {
			t.Errorf("%q refused", address)
		}
	}
	for _, address := range []string{"http://100.64.0.6", "100.64.0.6:62078", "-bad.ts.net",
		"a..b", "has space", "iphone/171"} {
		if validRemoteAddress(address) {
			t.Errorf("%q accepted", address)
		}
	}
}

// newRemoteService is a stored Service with one registered phone, an engine on
// a fake netmuxd, and remote addresses kept in a temporary file.
func newRemoteService(t *testing.T) (*Service, *iostest.Muxer, *iostest.Device, string) {
	t.Helper()
	svc, _ := newStoredService(t)
	_, identity := iostest.NewPairing(t)
	phone := iostest.NewDevice("PHONE-UDID", identity)
	muxer := iostest.NewMuxer(t)
	eng, err := engine.New(engine.Config{MuxAddress: muxer.Address(), PairingRoot: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	svc.engine = eng
	if err := svc.store.Device.Upsert(t.Context(), &model.Device{UDID: phone.UDID, Name: "iPhone"}); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "hydranest-remote.json")
	if svc.remote, err = loadRemote(path); err != nil {
		t.Fatal(err)
	}
	return svc, muxer, phone, path
}

func TestRemoteAddressAttachesThePhone(t *testing.T) {
	svc, muxer, phone, path := newRemoteService(t)
	ctx := t.Context()

	access, err := svc.SetRemoteAddress(ctx, phone.UDID, " 100.64.0.6 ")
	if err != nil || access.Address != "100.64.0.6" || access.State != RemoteWaiting {
		t.Fatalf("set = %+v, %v", access, err)
	}
	svc.attachRemotes(ctx)
	if access, _ := svc.RemoteAccess(ctx, phone.UDID); access.State != RemoteFailed || access.Error != "remote_unreachable" {
		t.Fatalf("unreachable phone = %+v", access)
	}

	muxer.ReachableAt(phone, netip.MustParseAddr("100.64.0.6"))
	svc.attachRemotes(ctx)
	access, _ = svc.RemoteAccess(ctx, phone.UDID)
	if access.State != RemoteAttached || access.IP != "100.64.0.6" || access.CheckedAt == nil {
		t.Fatalf("reachable phone = %+v", access)
	}
	// The address survives a restart; clearing it removes it from the file.
	reloaded, err := loadRemote(path)
	if err != nil || reloaded.get(phone.UDID).Address != "100.64.0.6" {
		t.Fatalf("reloaded = %+v, %v", reloaded.get(phone.UDID), err)
	}
	if access, err := svc.SetRemoteAddress(ctx, phone.UDID, ""); err != nil || access.State != RemoteOff {
		t.Fatalf("clear = %+v, %v", access, err)
	}
	data, _ := os.ReadFile(path)
	if string(data) != "{}\n" {
		t.Fatalf("file after clear = %q", data)
	}
}

func TestRemoteAddressRefusals(t *testing.T) {
	svc, _, phone, _ := newRemoteService(t)
	ctx := context.Background()
	var invalid *domain.ValidationError
	if _, err := svc.SetRemoteAddress(ctx, phone.UDID, "http://iphone"); !errors.As(err, &invalid) ||
		invalid.Code != "invalid_remote_address" {
		t.Fatalf("bad address: %v", err)
	}
	if _, err := svc.SetRemoteAddress(ctx, "OTHER-UDID", "100.64.0.6"); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown phone: %v", err)
	}
	if _, err := svc.RemoteAccess(ctx, "OTHER-UDID"); !errors.Is(err, domain.ErrNotFound) {
		t.Fatalf("unknown phone access: %v", err)
	}
}
