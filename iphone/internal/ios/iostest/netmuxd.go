package iostest

// HydraNest: netmuxd's AddDevice extension.

import (
	"net/netip"

	"github.com/wizier/airvault/internal/ios"
)

type reachable struct {
	device *Device
	addr   netip.Addr
}

// ReachableAt makes AddDevice for device at addr attach it over the network,
// as netmuxd does once its heartbeat to the phone is up.
func (m *Muxer) ReachableAt(device *Device, addr netip.Addr) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.reachable == nil {
		m.reachable = map[string]reachable{}
	}
	m.reachable[device.UDID] = reachable{device, addr}
}

// AddDevices counts the AddDevice requests served.
func (m *Muxer) AddDevices() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.adds
}

// addDevice runs with m.mu held. Like netmuxd it answers Result 1 or 0, and
// nothing for a phone it already lists on the network.
func (m *Muxer) addDevice(request map[string]any) map[string]any {
	m.adds++
	udid, _ := request["DeviceID"].(string)
	for _, entry := range m.attached {
		if entry.device.UDID == udid && entry.connection == ios.ConnectionNetwork {
			return nil
		}
	}
	addr, _ := netip.ParseAddr(request["IPAddress"].(string))
	target, ok := m.reachable[udid]
	if !ok || target.addr != addr {
		return map[string]any{"Result": uint64(0)}
	}
	m.nextID++
	m.attached[m.nextID] = attachment{target.device, ios.ConnectionNetwork}
	m.announce("Attached", m.nextID)
	return map[string]any{"Result": uint64(1)}
}
