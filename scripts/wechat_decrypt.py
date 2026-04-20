from pathlib import Path
from typing import Dict, List


def _parse_record_lines(record_lines: List[str]) -> Dict[str, object]:
    record: Dict[str, object] = {}
    for line in record_lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        record[key.strip()] = value.strip()
    if "rounds" in record:
        record["rounds"] = int(str(record["rounds"]))
    return record


def parse_key_log(log_path: Path) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    current_lines: List[str] = []
    with Path(log_path).open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line:
                current_lines.append(line)
                continue
            if current_lines:
                parsed = _parse_record_lines(current_lines)
                if {"rounds", "salt", "pw", "dk"}.issubset(parsed):
                    entries.append(parsed)
                current_lines = []
    if current_lines:
        parsed = _parse_record_lines(current_lines)
        if {"rounds", "salt", "pw", "dk"}.issubset(parsed):
            entries.append(parsed)
    return entries


def match_key_by_salt(
    entries: List[Dict[str, object]], salt_hex: str
) -> Dict[str, object]:
    target = salt_hex.lower()
    for entry in entries:
        if entry.get("salt", "").lower() == target:
            return entry
    raise ValueError(f"No key entry found for salt: {salt_hex}")
