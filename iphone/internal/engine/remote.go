package engine

// HydraNest: attaching a phone by a fixed address (Tailscale) next to the
// muxer's own mDNS discovery, so it is reachable away from home too.

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"time"

	"github.com/wizier/airvault/internal/ios"
)

const (
	// netmuxd answers AddDevice only after its TCP connect to lockdown, which
	// Linux gives up on after about two minutes.
	remoteAttachTimeout = 150 * time.Second
	resolveTimeout      = 10 * time.Second
	magicDNSServer      = "100.100.100.100:53"
)

var (
	// ErrRemoteUnreachable: no lockdown at the address. iOS only listens on
	// it while the phone is on a Wi-Fi network, any one, with Tailscale on.
	ErrRemoteUnreachable = errors.New("device unreachable at its remote address")
	// ErrRemoteNotAdded: the muxer has no pair record for the phone, or it was
	// found on the network meanwhile.
	ErrRemoteNotAdded = errors.New("muxer did not add the device")
	ErrRemoteResolve  = errors.New("remote address does not resolve")
)

// RemoteAttach is the outcome of one attach attempt.
type RemoteAttach struct {
	// Present: the muxer already listed the phone on the network, so nothing
	// was sent.
	Present bool
	Addr    netip.Addr // the address tried
}

// AttachRemote asks the muxer to reach device at address (an IP or a name
// such as a MagicDNS one) unless it already sees the phone on the network.
func (e *Engine) AttachRemote(ctx context.Context, device DeviceID, address string) (RemoteAttach, error) {
	if err := validateUDID(string(device)); err != nil {
		return RemoteAttach{}, err
	}
	list, cancel := context.WithTimeout(ctx, muxTimeout)
	devices, err := e.mux.Devices(list)
	cancel()
	if err != nil {
		return RemoteAttach{}, failure(ctx, "list devices", err)
	}
	for _, attached := range devices {
		if attached.UDID == string(device) && attached.Connection == ios.ConnectionNetwork {
			return RemoteAttach{Present: true, Addr: attached.Addr}, nil
		}
	}
	addr, err := resolveRemote(ctx, address)
	if err != nil {
		return RemoteAttach{}, err
	}
	attach, cancel := context.WithTimeout(ctx, remoteAttachTimeout)
	defer cancel()
	err = e.mux.AddNetworkDevice(attach, string(device), addr)
	switch {
	case errors.Is(err, ios.ErrNetworkUnreachable):
		err = ErrRemoteUnreachable
	case errors.Is(err, ios.ErrNotAdded):
		err = ErrRemoteNotAdded
	case err != nil:
		err = failure(ctx, "add network device", err)
	}
	return RemoteAttach{Addr: addr}, err
}

// magicDNS asks Tailscale's resolver directly, for when the system one does
// not carry the tailnet's names.
var magicDNS = &net.Resolver{
	PreferGo: true,
	Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
		var dialer net.Dialer
		return dialer.DialContext(ctx, network, magicDNSServer)
	},
}

// resolveRemote turns address into one IP, IPv4 first: netmuxd takes no names.
func resolveRemote(ctx context.Context, address string) (netip.Addr, error) {
	if addr, err := netip.ParseAddr(address); err == nil {
		return addr.Unmap(), nil
	}
	ctx, cancel := context.WithTimeout(ctx, resolveTimeout)
	defer cancel()
	addrs, err := net.DefaultResolver.LookupNetIP(ctx, "ip", address)
	if err != nil || len(addrs) == 0 {
		addrs, err = magicDNS.LookupNetIP(ctx, "ip", address)
	}
	if err == nil && len(addrs) == 0 {
		err = errors.New("no addresses")
	}
	if err != nil {
		return netip.Addr{}, fmt.Errorf("%w: %s: %w", ErrRemoteResolve, address, err)
	}
	for _, addr := range addrs {
		if addr.Unmap().Is4() {
			return addr.Unmap(), nil
		}
	}
	return addrs[0], nil
}
