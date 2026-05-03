"""Network flow record generator for UEBA synthetic data."""

import datetime
import numpy as np


def _flow_timestamp(current_date, rng):
    """Generate uniformly distributed timestamp across the day."""
    seconds = rng.integers(0, 86400)
    return datetime.datetime.combine(current_date, datetime.time.min) + datetime.timedelta(seconds=int(seconds))


def _pick_protocol(rng):
    """Select protocol: TCP 70%, UDP 25%, ICMP 5%."""
    r = rng.random()
    if r < 0.70:
        return "TCP"
    elif r < 0.95:
        return "UDP"
    else:
        return "ICMP"


def _pick_dst_port(protocol, rng):
    """Select destination port based on protocol and common distribution."""
    if protocol == "ICMP":
        return 0
    r = rng.random()
    if r < 0.40:
        return 443
    elif r < 0.55:
        return 80
    elif r < 0.65:
        return 53
    elif r < 0.70:
        return 22
    elif r < 0.73:
        return 3389
    else:
        return int(rng.integers(1024, 65535))


def _pick_bytes(rng):
    """Generate byte counts: small 60%, medium 30%, large 10%."""
    r = rng.random()
    if r < 0.60:
        total = rng.integers(100, 10240)
    elif r < 0.90:
        total = rng.integers(10240, 1048576)
    else:
        total = rng.integers(1048576, 104857600)
    split = rng.uniform(0.2, 0.8)
    return int(total * split), int(total * (1 - split))


def _pick_duration(port, rng):
    """Generate flow duration in ms. Long-lived for certain services."""
    if port in (22, 3389, 5900):
        return int(rng.integers(5000, 1800000))
    return int(rng.integers(50, 30000))


def _generate_segment_ip(segment_prefix, rng):
    """Generate IP within a /24 segment prefix like '10.1.5'."""
    return f"{segment_prefix}.{rng.integers(1, 255)}"


def _pick_tcp_flags(protocol, rng):
    """Generate realistic TCP flags string."""
    if protocol != "TCP":
        return None
    flag_combos = ["SYN", "SYN-ACK", "ACK", "PSH-ACK", "FIN-ACK", "RST"]
    weights = [0.15, 0.15, 0.30, 0.25, 0.10, 0.05]
    return rng.choice(flag_combos, p=weights)


EXTERNAL_SERVICES = [
    "13.107.42.14", "52.96.108.2", "104.18.32.7",       # Microsoft/CDN
    "172.217.14.99", "142.250.80.46",                     # Google
    "54.239.28.85", "52.94.236.248",                      # AWS
    "151.101.1.69", "151.101.65.69",                      # Fastly CDN
    "204.79.197.200", "40.126.32.140",                    # Azure AD
]


def generate_network_flows(devices_df, segments_df, current_date, rng) -> list[dict]:
    """Generate network flow records for all devices on a given date.

    Args:
        devices_df: DataFrame with columns [device_id, device_type, ip_address, segment_id]
        segments_df: DataFrame with columns [segment_id, prefix, adjacent_segments]
        current_date: date object for flow generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of flow dicts.
    """
    flows = []
    segment_map = segments_df.set_index("segment_id").to_dict("index")

    # Build list of all internal IPs by segment for internal traffic targets
    segment_ips = {}
    for _, dev in devices_df.iterrows():
        seg = dev["segment_id"]
        segment_ips.setdefault(seg, []).append(dev["ip_address"])

    for _, device in devices_df.iterrows():
        device_type = device["device_type"]
        n_flows = rng.poisson(500 if device_type == "server" else 200)

        seg_id = device["segment_id"]
        seg_info = segment_map.get(seg_id, {})
        adjacent = seg_info.get("adjacent_segments", [])

        for _ in range(n_flows):
            ts = _flow_timestamp(current_date, rng)
            protocol = _pick_protocol(rng)
            dst_port = _pick_dst_port(protocol, rng)
            src_port = int(rng.integers(1024, 65535))
            bytes_in, bytes_out = _pick_bytes(rng)
            duration_ms = _pick_duration(dst_port, rng)
            tcp_flags = _pick_tcp_flags(protocol, rng)

            # Internal vs external traffic
            if rng.random() < 0.85:
                # Internal: same segment or adjacent
                if adjacent and rng.random() < 0.3:
                    target_seg = rng.choice(adjacent)
                else:
                    target_seg = seg_id
                target_ips = segment_ips.get(target_seg, [])
                if target_ips:
                    dst_ip = rng.choice(target_ips)
                else:
                    prefix = segment_map.get(target_seg, {}).get("prefix", "10.0.0")
                    dst_ip = _generate_segment_ip(prefix, rng)
            else:
                dst_ip = rng.choice(EXTERNAL_SERVICES)

            flows.append({
                "timestamp": ts,
                "src_ip": device["ip_address"],
                "dst_ip": dst_ip,
                "src_port": src_port,
                "dst_port": dst_port,
                "protocol": protocol,
                "bytes_in": bytes_in,
                "bytes_out": bytes_out,
                "duration_ms": duration_ms,
                "tcp_flags": tcp_flags,
                "device_id": device["device_id"],
                "segment_id": seg_id,
            })

    flows.sort(key=lambda f: f["timestamp"])
    return flows
