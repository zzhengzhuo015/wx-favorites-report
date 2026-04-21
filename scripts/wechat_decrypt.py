from Crypto.Cipher import AES

from pathlib import Path
from typing import Dict, List

PAGE_SIZE = 4096
RESERVE = 80
SQLITE_HEADER = b"SQLite format 3\x00"


def _parse_record_lines(record_lines: List[str], record_start_line: int) -> Dict[str, object]:
    record: Dict[str, object] = {}
    for offset, line in enumerate(record_lines):
        if "=" not in line:
            line_number = record_start_line + offset
            raise RuntimeError(f"Malformed key log line at {line_number}: {line}")
        key, value = line.split("=", 1)
        record[key.strip()] = value.strip()
    missing = {"rounds", "salt", "pw", "dk"} - set(record.keys())
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise RuntimeError(
            f"Incomplete key log record starting at line {record_start_line}: "
            f"missing {missing_fields}"
        )
    try:
        record["rounds"] = int(str(record["rounds"]))
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid rounds value at line {record_start_line}: {record['rounds']}"
        ) from exc
    return record


def parse_key_log(log_path: Path) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    current_lines: List[str] = []
    record_start_line = 1
    with Path(log_path).open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if line:
                if not current_lines:
                    record_start_line = line_number
                current_lines.append(line)
                continue
            if current_lines:
                parsed = _parse_record_lines(current_lines, record_start_line)
                entries.append(parsed)
                current_lines = []
    if current_lines:
        parsed = _parse_record_lines(current_lines, record_start_line)
        entries.append(parsed)
    return entries


def match_key_by_salt(
    entries: List[Dict[str, object]], salt_hex: str
) -> Dict[str, object]:
    target = salt_hex.lower()
    for entry in entries:
        if entry.get("salt", "").lower() == target:
            return entry
    raise RuntimeError(f"No key entry found for salt: {salt_hex}")


def decrypt_sqlcipher_db(
    encrypted_path: Path,
    key_hex: str,
    output_path: Path,
    page_size: int = PAGE_SIZE,
    reserve: int = RESERVE,
) -> Path:
    encrypted_path = Path(encrypted_path)
    output_path = Path(output_path)
    key = bytes.fromhex(key_hex)
    data = encrypted_path.read_bytes()
    if len(data) % page_size != 0:
        raise RuntimeError(
            f"Encrypted database size is not aligned to page size {page_size}: {encrypted_path}"
        )

    page_count = len(data) // page_size
    plaintext = bytearray()
    for page_index in range(page_count):
        page = data[page_index * page_size : (page_index + 1) * page_size]
        ciphertext = page[16:-reserve] if page_index == 0 else page[:-reserve]
        iv = page[-reserve:-64]
        decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)
        if page_index == 0:
            plaintext.extend(SQLITE_HEADER)
        plaintext.extend(decrypted)
        plaintext.extend(b"\x00" * reserve)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(plaintext))
    return output_path
