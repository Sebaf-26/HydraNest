package service

// HydraNest: each phone's remote address, a Tailscale IP or MagicDNS name. The
// muxer is asked to attach the phone there on start, every remoteAttachEvery
// and right after a change, so backups also run away from home. iOS only
// serves lockdown while the phone is on a Wi-Fi network (any one), never on
// cellular alone.
//
// The addresses live in a JSON file of their own, not in the catalog, so the
// database keeps upstream AirVault's schema.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"maps"
	"net/netip"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/wizier/airvault/internal/domain"
	"github.com/wizier/airvault/internal/durable"
	"github.com/wizier/airvault/internal/engine"
)

const remoteAttachEvery = time.Minute

type RemoteState string

const (
	RemoteOff      RemoteState = "off"      // no address
	RemoteWaiting  RemoteState = "waiting"  // not tried yet
	RemoteAttached RemoteState = "attached" // the muxer sees the phone on the network
	RemoteFailed   RemoteState = "failed"
)

// RemoteAccess is one phone's address and the last attach attempt.
type RemoteAccess struct {
	Address string      `json:"address"`
	State   RemoteState `json:"state"`
	// Error is a code, like the API's errors: remote_unreachable, ...
	Error     string     `json:"error,omitempty"`
	IP        string     `json:"ip,omitempty"`
	CheckedAt *time.Time `json:"checkedAt,omitempty"`
}

type remoteRegistry struct {
	path string
	kick chan struct{}

	mu        sync.Mutex
	addresses map[string]string // udid -> address, as stored
	status    map[string]RemoteAccess
}

func loadRemote(path string) (*remoteRegistry, error) {
	r := &remoteRegistry{path: path, kick: make(chan struct{}, 1),
		addresses: map[string]string{}, status: map[string]RemoteAccess{}}
	data, err := os.ReadFile(path)
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return r, nil
	case err != nil:
		return nil, fmt.Errorf("read remote addresses: %w", err)
	}
	if err := json.Unmarshal(data, &r.addresses); err != nil {
		return nil, fmt.Errorf("parse remote addresses %s: %w", path, err)
	}
	return r, nil
}

// save runs with r.mu held.
func (r *remoteRegistry) save() error {
	data, err := json.MarshalIndent(r.addresses, "", "  ")
	if err != nil {
		return err
	}
	if err := durable.WriteFile(r.path, append(data, '\n'), 0o600); err != nil {
		return fmt.Errorf("save remote addresses: %w", err)
	}
	return nil
}

func (r *remoteRegistry) get(udid string) RemoteAccess {
	r.mu.Lock()
	defer r.mu.Unlock()
	address, ok := r.addresses[udid]
	if !ok {
		return RemoteAccess{State: RemoteOff}
	}
	if status, ok := r.status[udid]; ok {
		return status
	}
	return RemoteAccess{Address: address, State: RemoteWaiting}
}

func (r *remoteRegistry) set(udid, address string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	previous, had := r.addresses[udid]
	if address == "" {
		delete(r.addresses, udid)
	} else {
		r.addresses[udid] = address
	}
	if err := r.save(); err != nil {
		if had {
			r.addresses[udid] = previous
		} else {
			delete(r.addresses, udid)
		}
		return err
	}
	delete(r.status, udid)
	select {
	case r.kick <- struct{}{}:
	default:
	}
	return nil
}

func (r *remoteRegistry) snapshot() map[string]string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return maps.Clone(r.addresses)
}

// record keeps an attempt's outcome unless the address changed meanwhile, and
// reports whether the state differs from the last one.
func (r *remoteRegistry) record(udid string, status RemoteAccess) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.addresses[udid] != status.Address {
		return false
	}
	last, ok := r.status[udid]
	r.status[udid] = status
	return !ok || last.State != status.State || last.Error != status.Error || last.IP != status.IP
}

// StartRemote loads the addresses at path and keeps the phones attached.
func (s *Service) StartRemote(ctx context.Context, path string) error {
	remote, err := loadRemote(path)
	if err != nil {
		return err
	}
	s.remote = remote
	s.wg.Go(func() {
		for {
			s.attachRemotes(ctx)
			select {
			case <-ctx.Done():
				return
			case <-remote.kick:
			case <-time.After(remoteAttachEvery):
			}
		}
	})
	return nil
}

// attachRemotes tries every registered phone with an address, in parallel: one
// unreachable phone holds its attempt for minutes.
func (s *Service) attachRemotes(ctx context.Context) {
	addresses := s.remote.snapshot()
	if len(addresses) == 0 {
		return
	}
	devices, err := s.store.Device.List(ctx)
	if err != nil {
		slog.Warn("remote: list devices", "error", err)
		return
	}
	var wg sync.WaitGroup
	for _, device := range devices {
		address, ok := addresses[device.UDID]
		if !ok {
			continue
		}
		wg.Go(func() {
			result, err := s.engine.AttachRemote(ctx, engine.DeviceID(device.UDID), address)
			if ctx.Err() != nil {
				return
			}
			now := time.Now().UTC()
			status := RemoteAccess{Address: address, State: RemoteAttached, CheckedAt: &now}
			if result.Addr.IsValid() {
				status.IP = result.Addr.String()
			}
			if err != nil {
				status.State, status.Error = RemoteFailed, remoteErrorCode(err)
			}
			if !s.remote.record(device.UDID, status) {
				return
			}
			switch {
			case err != nil:
				slog.Info("remote: phone not attached", "udid", device.UDID, "address", address, "error", err)
			case result.Present:
				slog.Info("remote: phone on the network", "udid", device.UDID, "ip", status.IP)
			default:
				slog.Info("remote: phone attached", "udid", device.UDID, "address", address, "ip", status.IP)
			}
			s.bus.Emit(deviceUpdated(device.UDID))
		})
	}
	wg.Wait()
}

func remoteErrorCode(err error) string {
	switch {
	case errors.Is(err, engine.ErrRemoteUnreachable):
		return "remote_unreachable"
	case errors.Is(err, engine.ErrRemoteNotAdded):
		return "remote_not_added"
	case errors.Is(err, engine.ErrRemoteResolve):
		return "remote_resolve_failed"
	}
	return "remote_muxer_failed"
}

// RemoteAccess is off for a phone without an address.
func (s *Service) RemoteAccess(ctx context.Context, udid string) (RemoteAccess, error) {
	if _, err := s.store.Device.GetByUDID(ctx, udid); err != nil {
		return RemoteAccess{}, err
	}
	return s.remote.get(udid), nil
}

// SetRemoteAddress stores address (an IP or host name; empty removes it) and
// tries it right away.
func (s *Service) SetRemoteAddress(ctx context.Context, udid, address string) (RemoteAccess, error) {
	address = strings.TrimSpace(address)
	if address != "" && !validRemoteAddress(address) {
		return RemoteAccess{}, &domain.ValidationError{Code: "invalid_remote_address",
			Message: "remote address must be an IP address or a host name"}
	}
	if _, err := s.store.Device.GetByUDID(ctx, udid); err != nil {
		return RemoteAccess{}, err
	}
	if err := s.remote.set(udid, address); err != nil {
		return RemoteAccess{}, err
	}
	s.bus.Emit(deviceUpdated(udid))
	return s.remote.get(udid), nil
}

// validRemoteAddress takes an IP or a DNS name such as iphone.example.ts.net.
func validRemoteAddress(address string) bool {
	if _, err := netip.ParseAddr(address); err == nil {
		return true
	}
	name := strings.TrimSuffix(address, ".")
	if name == "" || len(name) > 253 {
		return false
	}
	for label := range strings.SplitSeq(name, ".") {
		if label == "" || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' ||
			strings.ContainsFunc(label, notHostChar) {
			return false
		}
	}
	return true
}

func notHostChar(c rune) bool {
	return (c < 'a' || c > 'z') && (c < 'A' || c > 'Z') && (c < '0' || c > '9') && c != '-'
}
