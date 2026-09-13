"""CSV target-history cache and JSON computed-solution log."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TARGET_HISTORY_CSV = DATA_DIR / "target_history.csv"
SOLUTIONS_JSON = DATA_DIR / "solutions.json"

_CSV_FIELDS = ["target_id", "timestamp", "lat_deg", "lon_deg", "raw_input"]


@dataclass(frozen=True)
class TargetEntry:
    """A single cached target position report."""

    target_id: str
    timestamp: datetime
    lat_deg: float
    lon_deg: float
    raw_input: str


def append_target_entry(
    entry: TargetEntry, csv_path: Path = TARGET_HISTORY_CSV
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS)
        if is_new_file:
            writer.writeheader()
        writer.writerow(
            {
                "target_id": entry.target_id,
                "timestamp": entry.timestamp.isoformat(),
                "lat_deg": entry.lat_deg,
                "lon_deg": entry.lon_deg,
                "raw_input": entry.raw_input,
            }
        )


def load_target_history(
    target_id: str, csv_path: Path = TARGET_HISTORY_CSV
) -> list[TargetEntry]:
    if not csv_path.exists():
        return []

    entries: list[TargetEntry] = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["target_id"] != target_id:
                continue
            entries.append(
                TargetEntry(
                    target_id=row["target_id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    lat_deg=float(row["lat_deg"]),
                    lon_deg=float(row["lon_deg"]),
                    raw_input=row["raw_input"],
                )
            )
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def append_solution_record(
    record: dict, json_path: Path = SOLUTIONS_JSON
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    if json_path.exists():
        records = json.loads(json_path.read_text(encoding="utf-8") or "[]")
    records.append(record)
    json_path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
