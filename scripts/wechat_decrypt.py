import re
from pathlib import Path
from typing import Dict, List, Optional


_KEY_LOG_PATTERN = re.compile(
    r"rounds=(?P<rounds>\S+)\s+salt=(?P<salt>\S+)\s+pw=(?P<pw>\S+)\s+dk=(?P<dk>\S+)"
)


def parse_key_log(log_path: Path) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    with Path(log_path).open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _KEY_LOG_PATTERN.search(line)
            if match:
                entries.append(match.groupdict())
    return entries


def match_key_by_salt(
    entries: List[Dict[str, str]], salt_hex: str
) -> Optional[Dict[str, str]]:
    target = salt_hex.lower()
    for entry in entries:
        if entry.get("salt", "").lower() == target:
            return entry
    return None
