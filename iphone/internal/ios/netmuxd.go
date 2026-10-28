package ios

// HydraNest: netmuxd's AddDevice extension, for a phone mDNS cannot see (a
// Tailscale address away from home).

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/netip"
)

const netmuxdService = "_apple-mobdev2._tcp.local"

var (
	// ErrNetworkUnreachable: netmuxd could not open lockdown and the heartbeat
	// at the address (the phone is off Wi-Fi, asleep or not on the tailnet).
	ErrNetworkUnreachable = errors.New("muxer could not reach the device")
	// ErrNotAdded: netmuxd closed without an answer, which it does when it has
	// no pair record for the phone or already lists it on the network.
	ErrNotAdded = errors.New("muxer did not add the device")
)

// AddNetworkDevice asks netmuxd to attach udid at addr. netmuxd answers once
// its heartbeat to the phone is up or has failed, so ctx must allow for a TCP
// connect to time out.
func (m Mux) AddNetworkDevice(ctx context.Context, udid string, addr netip.Addr) error {
	var reply struct {
		Result *uint64 `plist:"Result"`
	}
	err := m.exchange(ctx, muxRequest("AddDevice", map[string]any{
		"ConnectionType": string(ConnectionNetwork),
		"ServiceName":    netmuxdService,
		"IPAddress":      addr.Unmap().String(),
		"DeviceID":       udid,
	}), &reply)
	switch {
	case errors.Is(err, io.EOF):
		return ErrNotAdded
	case err != nil:
		return err
	case reply.Result == nil:
		return fmt.Errorf("%w: AddDevice without a Result", ErrProtocol)
	case *reply.Result != 1:
		return ErrNetworkUnreachable
	}
	return nil
}
