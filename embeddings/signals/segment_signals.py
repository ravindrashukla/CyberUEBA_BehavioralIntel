"""Behavioral signal serialization for network segment entities.

Each function computes stats from log DataFrames filtered by segment and time window,
then serializes the findings as 3-5 sentence English prose for embedding.
"""

import ipaddress
from datetime import datetime

import pandas as pd


def _segment_network_flows(segment_id: str, logs: dict, window_start, window_end) -> pd.DataFrame:
    """Filter network flows where segment_id matches the given segment within the time window."""
    nw = logs.get("network")
    if nw is None or nw.empty:
        return pd.DataFrame()
    mask = (
        (nw["segment_id"] == segment_id)
        & (nw["timestamp"] >= window_start)
        & (nw["timestamp"] <= window_end)
    )
    return nw.loc[mask]


def _format_bytes(n: int) -> str:
    """Human-readable byte string."""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} bytes"


def volume_signal(segment_id: str, logs: dict, window_start, window_end) -> str:
    """Traffic volume: total flows, bytes in/out, peak vs average, trend."""
    flows = _segment_network_flows(segment_id, logs, window_start, window_end)
    if flows.empty:
        return f"No network traffic recorded for segment {segment_id} in this period."

    total_flows = len(flows)
    total_bytes_in = int(flows["bytes_in"].sum())
    total_bytes_out = int(flows["bytes_out"].sum())

    # Peak vs average hourly volume
    flows_copy = flows.copy()
    flows_copy["hour"] = flows_copy["timestamp"].dt.hour
    hourly = flows_copy.groupby("hour").size()
    peak_hour = int(hourly.idxmax())
    peak_count = int(hourly.max())
    avg_count = float(hourly.mean())

    # Trend: compare first half vs second half
    midpoint = window_start + (window_end - window_start) / 2
    first_half = len(flows[flows["timestamp"] < midpoint])
    second_half = total_flows - first_half
    if first_half > 0:
        trend_pct = ((second_half - first_half) / first_half) * 100
        trend_desc = f"increasing by {trend_pct:.0f}%" if trend_pct > 10 else (
            f"decreasing by {abs(trend_pct):.0f}%" if trend_pct < -10 else "stable"
        )
    else:
        trend_desc = "concentrated in the latter half of the window"

    return (
        f"Segment {segment_id} carried {total_flows:,} flows totaling "
        f"{_format_bytes(total_bytes_in)} inbound and {_format_bytes(total_bytes_out)} outbound. "
        f"Peak activity occurred at hour {peak_hour} with {peak_count:,} flows versus an hourly "
        f"average of {avg_count:.0f}. "
        f"Volume trend is {trend_desc} across the observation window."
    )


def connections_signal(segment_id: str, logs: dict, window_start, window_end) -> str:
    """Connection patterns: unique src/dst pairs, new connections, cross-segment."""
    flows = _segment_network_flows(segment_id, logs, window_start, window_end)
    if flows.empty:
        return f"No connection activity recorded for segment {segment_id} in this period."

    # Unique connection pairs
    pairs = flows[["src_ip", "dst_ip"]].drop_duplicates()
    n_pairs = len(pairs)
    unique_src = flows["src_ip"].nunique()
    unique_dst = flows["dst_ip"].nunique()

    # Cross-segment flows: dst_ip not in the same segment
    # Approximate by checking flows where src segment != dst segment indirectly
    # Use the fact that same-segment devices share the same segment_id
    # Since we filtered by segment_id (which is the source segment), cross-segment means
    # the dst_ip connects to a device outside this segment
    all_network = logs.get("network")
    if all_network is not None and not all_network.empty:
        seg_ips = set(all_network.loc[all_network["segment_id"] == segment_id, "src_ip"].unique())
        cross_segment = flows[~flows["dst_ip"].isin(seg_ips)]
        cross_pct = len(cross_segment) / len(flows) * 100
    else:
        cross_pct = 0.0

    return (
        f"Segment {segment_id} generated {n_pairs:,} unique source-destination pairs from "
        f"{unique_src} source IPs to {unique_dst} destination IPs. "
        f"Approximately {cross_pct:.1f}% of flows were cross-segment or external connections. "
        f"The connection fan-out ratio is {n_pairs / max(unique_src, 1):.1f} destinations per source."
    )


def protocols_signal(segment_id: str, logs: dict, window_start, window_end) -> str:
    """Protocol mix: TCP/UDP/ICMP ratios, port distribution, unusual ports."""
    flows = _segment_network_flows(segment_id, logs, window_start, window_end)
    if flows.empty:
        return f"No protocol activity recorded for segment {segment_id} in this period."

    total = len(flows)
    proto_counts = flows["protocol"].value_counts()
    tcp_pct = proto_counts.get("TCP", 0) / total * 100
    udp_pct = proto_counts.get("UDP", 0) / total * 100
    icmp_pct = proto_counts.get("ICMP", 0) / total * 100

    # Port distribution
    common_ports = {80, 443, 53, 22, 3389, 25, 8080, 8443}
    port_counts = flows["dst_port"].value_counts()
    top_ports = port_counts.head(5).index.tolist()
    unusual_ports = flows[~flows["dst_port"].isin(common_ports)]
    unusual_pct = len(unusual_ports) / total * 100

    top_ports_str = ", ".join(str(p) for p in top_ports)

    return (
        f"Protocol distribution for segment {segment_id}: TCP {tcp_pct:.1f}%, "
        f"UDP {udp_pct:.1f}%, ICMP {icmp_pct:.1f}%. "
        f"Top destination ports are [{top_ports_str}]. "
        f"{unusual_pct:.1f}% of traffic used non-standard ports (outside common services), "
        f"with {port_counts.nunique()} distinct destination ports observed."
    )


def threats_signal(segment_id: str, logs: dict, window_start, window_end) -> str:
    """Threat indicators: auth failures from this segment, high-risk endpoint events, DNS anomalies."""
    # Auth failures originating from devices in this segment
    auth = logs.get("auth")
    network = logs.get("network")
    endpoint = logs.get("endpoint")
    dns = logs.get("dns")

    # Get device IDs in this segment from network flows
    seg_devices = set()
    if network is not None and not network.empty:
        seg_devices = set(
            network.loc[network["segment_id"] == segment_id, "device_id"].unique()
        )

    parts = []

    # Auth failures
    if auth is not None and not auth.empty and seg_devices:
        auth_window = auth[
            (auth["timestamp"] >= window_start)
            & (auth["timestamp"] <= window_end)
            & (auth["device_id"].isin(seg_devices))
        ]
        failures = auth_window[auth_window["success"] == False]
        n_failures = len(failures)
        n_total_auth = len(auth_window)
        if n_total_auth > 0:
            parts.append(
                f"{n_failures} authentication failures out of {n_total_auth:,} attempts "
                f"({n_failures / n_total_auth * 100:.1f}% failure rate)"
            )
        else:
            parts.append("no authentication events from segment devices")
    else:
        parts.append("no authentication data available for segment devices")

    # High-risk endpoint events
    if endpoint is not None and not endpoint.empty and seg_devices:
        ep_window = endpoint[
            (endpoint["timestamp"] >= window_start)
            & (endpoint["timestamp"] <= window_end)
            & (endpoint["device_id"].isin(seg_devices))
        ]
        high_risk = ep_window[ep_window["risk_score"] >= 50]
        parts.append(f"{len(high_risk)} high-risk endpoint events (score >= 50)")
    else:
        parts.append("no endpoint telemetry available")

    # DNS anomalies
    if dns is not None and not dns.empty and seg_devices:
        dns_window = dns[
            (dns["timestamp"] >= window_start)
            & (dns["timestamp"] <= window_end)
            & (dns["device_id"].isin(seg_devices))
        ]
        nxdomain = dns_window[dns_window["response_code"] == "NXDOMAIN"]
        servfail = dns_window[dns_window["response_code"] == "SERVFAIL"]
        parts.append(
            f"{len(nxdomain)} NXDOMAIN and {len(servfail)} SERVFAIL DNS responses"
        )
    else:
        parts.append("no DNS data available")

    return (
        f"Threat indicators for segment {segment_id}: {parts[0]}. "
        f"Endpoint analysis shows {parts[1]}. "
        f"DNS anomaly count: {parts[2]}."
    )


def exposure_signal(segment_id: str, logs: dict, window_start, window_end) -> str:
    """Exposure: external connections, DMZ interaction, access policy violations."""
    flows = _segment_network_flows(segment_id, logs, window_start, window_end)
    if flows.empty:
        return f"No exposure data recorded for segment {segment_id} in this period."

    total = len(flows)

    # External connections: dst_ip starts with non-RFC1918 ranges
    def _is_external(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
            return not addr.is_private
        except (ValueError, TypeError):
            return False

    external_mask = flows["dst_ip"].apply(_is_external)
    n_external = int(external_mask.sum())
    external_pct = n_external / total * 100

    unique_external_dst = flows.loc[external_mask, "dst_ip"].nunique()

    # Auth failures (access policy violations) from segment devices
    auth = logs.get("auth")
    network = logs.get("network")
    seg_devices = set()
    if network is not None and not network.empty:
        seg_devices = set(
            network.loc[network["segment_id"] == segment_id, "device_id"].unique()
        )

    policy_violations = 0
    if auth is not None and not auth.empty and seg_devices:
        auth_window = auth[
            (auth["timestamp"] >= window_start)
            & (auth["timestamp"] <= window_end)
            & (auth["device_id"].isin(seg_devices))
            & (auth["success"] == False)
        ]
        policy_violations = len(auth_window)

    return (
        f"Segment {segment_id} exposure: {n_external:,} external connections ({external_pct:.1f}% "
        f"of total traffic) reaching {unique_external_dst} unique external destinations. "
        f"{policy_violations} access policy violations (failed authentications) were recorded "
        f"from devices in this segment. "
        f"External communication volume is "
        f"{'elevated' if external_pct > 20 else 'moderate' if external_pct > 10 else 'low'} "
        f"relative to internal traffic."
    )
