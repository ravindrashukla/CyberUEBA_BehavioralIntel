"""DNS query log generator for UEBA synthetic data."""

import datetime
import numpy as np

from simulator.config import DNS_QUERIES_PER_DEVICE_DAY, WORK_HOURS


INTERNAL_DOMAINS = [
    "dc01.corp", "dc02.corp", "mail.corp", "intranet.corp",
    "wiki.internal", "git.internal", "ci.internal", "artifactory.internal",
    "ldap.corp", "ntp.corp", "dns.corp", "proxy.corp",
    "hr.internal", "finance.internal", "crm.internal", "erp.internal",
    "siem.corp", "splunk.internal", "vault.corp", "pki.corp",
]

EXTERNAL_DOMAINS = [
    "google.com", "microsoft.com", "github.com", "amazonaws.com",
    "cloudflare.com", "office365.com", "slack.com", "zoom.us",
    "linkedin.com", "stackoverflow.com", "docker.io", "npmjs.org",
    "pypi.org", "ubuntu.com", "redhat.com", "atlassian.net",
    "salesforce.com", "okta.com", "duo.com", "crowdstrike.com",
    "sentinelone.net", "akamai.net", "fastly.net", "cdn.jsdelivr.net",
    "teams.microsoft.com", "outlook.office365.com", "login.microsoftonline.com",
    "api.github.com", "registry.npmjs.org", "s3.amazonaws.com",
]

EXTERNAL_SUBDOMAINS = [
    "www", "api", "mail", "cdn", "static", "auth", "login",
    "app", "docs", "support", "status", "download", "update",
]

DNS_SERVERS = ["10.0.0.10", "10.0.0.11", "10.0.1.10", "8.8.8.8", "1.1.1.1"]


def _dns_timestamp(current_date, rng):
    """Generate timestamp with 3x bias toward work hours."""
    work_start, work_end = WORK_HOURS
    # Work hours get 3x weight: work_hours * 3 vs off_hours * 1
    work_span = work_end - work_start  # 10 hours
    off_span = 24 - work_span  # 14 hours
    work_weight = work_span * 3  # 30
    total_weight = work_weight + off_span  # 44
    work_prob = work_weight / total_weight

    if rng.random() < work_prob:
        hour = rng.integers(work_start, work_end)
    else:
        hour = rng.choice(list(range(0, work_start)) + list(range(work_end, 24)))

    minute = rng.integers(0, 60)
    second = rng.integers(0, 60)
    ms = rng.integers(0, 1000)
    return datetime.datetime.combine(
        current_date, datetime.time(int(hour), int(minute), int(second), int(ms) * 1000)
    )


def _pick_record_type(rng):
    """Select record type: A 60%, AAAA 15%, CNAME 10%, MX 5%, TXT 5%, PTR 5%."""
    r = rng.random()
    if r < 0.60:
        return "A"
    elif r < 0.75:
        return "AAAA"
    elif r < 0.85:
        return "CNAME"
    elif r < 0.90:
        return "MX"
    elif r < 0.95:
        return "TXT"
    else:
        return "PTR"


def _pick_response_code(rng):
    """Select response code: NOERROR 95%, NXDOMAIN 4%, SERVFAIL 1%."""
    r = rng.random()
    if r < 0.95:
        return "NOERROR"
    elif r < 0.99:
        return "NXDOMAIN"
    else:
        return "SERVFAIL"


def _generate_query_name(rng):
    """Generate a realistic DNS query name mixing internal and external."""
    if rng.random() < 0.30:
        return rng.choice(INTERNAL_DOMAINS)
    else:
        domain = rng.choice(EXTERNAL_DOMAINS)
        if rng.random() < 0.60:
            subdomain = rng.choice(EXTERNAL_SUBDOMAINS)
            return f"{subdomain}.{domain}"
        return domain


def _generate_response_ip(record_type, query_name, response_code, rng):
    """Generate a response IP appropriate for the record type."""
    if response_code != "NOERROR":
        return None

    if record_type == "A":
        if ".corp" in query_name or ".internal" in query_name:
            return f"10.{rng.integers(0, 20)}.{rng.integers(1, 255)}.{rng.integers(1, 255)}"
        return f"{rng.integers(1, 224)}.{rng.integers(0, 256)}.{rng.integers(0, 256)}.{rng.integers(1, 255)}"
    elif record_type == "AAAA":
        segments = [f"{rng.integers(0, 65536):04x}" for _ in range(8)]
        return ":".join(segments)
    elif record_type == "CNAME":
        return f"cname-{rng.integers(1, 100)}.cdn.{rng.choice(['cloudflare.com', 'akamai.net', 'fastly.net'])}"
    elif record_type == "MX":
        return f"mx{rng.integers(1, 5)}.{query_name.split('.')[-2]}.com"
    elif record_type == "TXT":
        return "v=spf1 include:_spf.google.com ~all"
    elif record_type == "PTR":
        return f"host-{rng.integers(1, 500)}.example.com"
    return None


def generate_dns_queries(devices_df, segments_df, current_date, rng) -> list[dict]:
    """Generate DNS query log events for all devices on a given date.

    Args:
        devices_df: DataFrame with columns [device_id, device_type, ip_address, segment_id]
        segments_df: DataFrame with columns [segment_id, prefix, adjacent_segments]
        current_date: date object for event generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of DNS query event dicts.
    """
    events = []

    for _, device in devices_df.iterrows():
        n_queries = rng.poisson(DNS_QUERIES_PER_DEVICE_DAY)

        for _ in range(n_queries):
            ts = _dns_timestamp(current_date, rng)
            record_type = _pick_record_type(rng)
            response_code = _pick_response_code(rng)
            query_name = _generate_query_name(rng)
            response_ip = _generate_response_ip(record_type, query_name, response_code, rng)
            ttl = int(rng.choice([60, 300, 600, 1800, 3600, 7200, 86400]))
            server_ip = rng.choice(DNS_SERVERS)

            events.append({
                "timestamp": ts,
                "device_id": device["device_id"],
                "query_name": query_name,
                "record_type": record_type,
                "response_code": response_code,
                "response_ip": response_ip,
                "ttl": ttl if response_code == "NOERROR" else 0,
                "server_ip": server_ip,
            })

    events.sort(key=lambda e: e["timestamp"])
    return events
