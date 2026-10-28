package ios

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"testing"
)

func TestAddNetworkDevice(t *testing.T) {
	answers := map[string]func(net.Conn){
		"100.64.0.6": func(conn net.Conn) { _ = writeMux(conn, map[string]any{"Result": uint64(1)}) },
		"100.64.0.7": func(conn net.Conn) { _ = writeMux(conn, map[string]any{"Result": uint64(0)}) },
		"100.64.0.8": func(net.Conn) {}, // netmuxd drops the reply
	}
	mux := startMux(t, func(conn net.Conn, request map[string]any) {
		defer conn.Close()
		want := map[string]any{
			"MessageType":    "AddDevice",
			"ConnectionType": "Network",
			"ServiceName":    "_apple-mobdev2._tcp.local",
			"DeviceID":       "PHONE",
		}
		for key, value := range want {
			if request[key] != value {
				t.Errorf("%s = %v, want %v", key, request[key], value)
			}
		}
		answers[request["IPAddress"].(string)](conn)
	})
	tests := map[string]error{
		"100.64.0.6": nil,
		"100.64.0.7": ErrNetworkUnreachable,
		"100.64.0.8": ErrNotAdded,
	}
	for ip, want := range tests {
		err := mux.AddNetworkDevice(context.Background(), "PHONE", netip.MustParseAddr(ip))
		if !errors.Is(err, want) && err != want {
			t.Errorf("AddNetworkDevice(%s) = %v, want %v", ip, err, want)
		}
	}
}

// netmuxd parses the address as Rust's IpAddr, which takes no IPv4-mapped form.
func TestAddNetworkDeviceSendsPlainIPv4(t *testing.T) {
	mux := startMux(t, func(conn net.Conn, request map[string]any) {
		defer conn.Close()
		if request["IPAddress"] != "100.64.0.6" {
			t.Errorf("IPAddress = %v", request["IPAddress"])
		}
		_ = writeMux(conn, map[string]any{"Result": uint64(1)})
	})
	if err := mux.AddNetworkDevice(context.Background(), "PHONE", netip.MustParseAddr("::ffff:100.64.0.6")); err != nil {
		t.Fatal(err)
	}
}
