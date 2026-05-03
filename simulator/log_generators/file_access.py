"""File access event generator for UEBA synthetic data."""

import datetime
import numpy as np

from simulator.config import FILE_ACCESS_PER_USER_DAY, WORK_HOURS


FILE_SERVERS = ["//fileserver01", "//fileserver02", "//nas-prod", "//dfs-share"]

DEPARTMENTS_DIRS = [
    "Engineering", "Finance", "HR", "Legal", "IT",
    "Security", "Sales", "Marketing", "Executive", "Research",
]

PROJECT_NAMES = [
    "ProjectAlpha", "Q4_Forecast", "ProductRoadmap", "ComplianceAudit",
    "IncidentResponse", "BudgetReview", "RFP_Response", "TechDebt",
    "CustomerData", "VendorContracts", "MergerDocs", "PatentFilings",
]

FILE_EXTENSIONS = {
    "documents": [".docx", ".xlsx", ".pptx", ".pdf", ".txt", ".csv"],
    "code": [".py", ".js", ".java", ".sql", ".sh", ".yaml"],
    "media": [".png", ".jpg", ".mp4", ".svg"],
    "archives": [".zip", ".tar.gz", ".7z"],
    "data": [".json", ".parquet", ".db", ".bak"],
}

FILE_NAMES = [
    "report", "summary", "analysis", "dashboard", "config",
    "data_export", "meeting_notes", "proposal", "invoice",
    "contract", "policy", "procedure", "template", "backup",
    "credentials", "roster", "schedule", "budget", "forecast",
]


def _file_access_timestamp(current_date, rng):
    """Generate timestamp biased toward work hours (80/20 split)."""
    work_start, work_end = WORK_HOURS
    if rng.random() < 0.80:
        hour = rng.integers(work_start, work_end)
    else:
        hour = rng.choice(list(range(0, work_start)) + list(range(work_end, 24)))
    minute = rng.integers(0, 60)
    second = rng.integers(0, 60)
    return datetime.datetime.combine(current_date, datetime.time(int(hour), int(minute), int(second)))


def _pick_operation(rng):
    """Select operation: read 50%, write 30%, delete 5%, copy 5%, move 5%, permission_change 5%."""
    r = rng.random()
    if r < 0.50:
        return "read"
    elif r < 0.80:
        return "write"
    elif r < 0.85:
        return "delete"
    elif r < 0.90:
        return "copy"
    elif r < 0.95:
        return "move"
    else:
        return "permission_change"


def _pick_classification(rng):
    """Select data classification: public 40%, internal 35%, confidential 20%, restricted 5%."""
    r = rng.random()
    if r < 0.40:
        return "public"
    elif r < 0.75:
        return "internal"
    elif r < 0.95:
        return "confidential"
    else:
        return "restricted"


def _generate_file_path(rng):
    """Generate a realistic file path from network shares or local drives."""
    r = rng.random()

    # Pick file name and extension
    name = rng.choice(FILE_NAMES)
    ext_category = rng.choice(list(FILE_EXTENSIONS.keys()))
    ext = rng.choice(FILE_EXTENSIONS[ext_category])
    filename = f"{name}_{rng.integers(1, 999):03d}{ext}"

    if r < 0.50:
        # Network file share
        server = rng.choice(FILE_SERVERS)
        dept = rng.choice(DEPARTMENTS_DIRS)
        project = rng.choice(PROJECT_NAMES)
        return f"{server}/{dept}/{project}/{filename}"
    elif r < 0.80:
        # Local user documents
        return f"C:\\Users\\user\\Documents\\{rng.choice(PROJECT_NAMES)}\\{filename}"
    elif r < 0.90:
        # Shared project path (Unix-style)
        project = rng.choice(PROJECT_NAMES)
        return f"/shared/projects/{project}/{filename}"
    else:
        # Downloads or temp
        if rng.random() < 0.5:
            return f"C:\\Users\\user\\Downloads\\{filename}"
        return f"C:\\Users\\user\\AppData\\Local\\Temp\\{filename}"


def _generate_file_size(operation, rng):
    """Generate realistic file size in bytes based on operation."""
    if operation == "permission_change":
        return 0
    r = rng.random()
    if r < 0.50:
        return int(rng.integers(1024, 102400))  # 1KB - 100KB
    elif r < 0.80:
        return int(rng.integers(102400, 10485760))  # 100KB - 10MB
    elif r < 0.95:
        return int(rng.integers(10485760, 104857600))  # 10MB - 100MB
    else:
        return int(rng.integers(104857600, 1073741824))  # 100MB - 1GB


def generate_file_access(users_df, current_date, rng) -> list[dict]:
    """Generate file access events for all users on a given date.

    Args:
        users_df: DataFrame with columns [user_id, primary_device_id]
        current_date: date object for event generation
        rng: numpy random Generator for reproducibility

    Returns:
        List of file access event dicts.
    """
    events = []

    for _, user in users_df.iterrows():
        n_events = rng.poisson(FILE_ACCESS_PER_USER_DAY)
        user_id = user["user_id"]
        device_id = user["primary_device_id"]

        for _ in range(n_events):
            ts = _file_access_timestamp(current_date, rng)
            operation = _pick_operation(rng)
            classification = _pick_classification(rng)
            file_path = _generate_file_path(rng)
            file_size = _generate_file_size(operation, rng)

            # 97% success, 3% access denied
            success = bool(rng.random() < 0.97)

            events.append({
                "timestamp": ts,
                "user_id": user_id,
                "file_path": file_path,
                "operation": operation,
                "file_size_bytes": file_size,
                "data_classification": classification,
                "source_device_id": device_id,
                "success": success,
            })

    events.sort(key=lambda e: e["timestamp"])
    return events
