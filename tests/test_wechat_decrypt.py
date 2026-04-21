import sqlite3
from pathlib import Path

from Crypto.Cipher import AES
import pytest

from scripts.wechat_decrypt import decrypt_sqlcipher_db, match_key_by_salt, parse_key_log

PAGE_SIZE = 4096
RESERVE = 80
SQLITE_HEADER = b"SQLite format 3\x00"


def _prepare_sqlcipher_plaintext(path: Path) -> bytes:
    raw = bytearray(path.read_bytes())
    raw[20] = RESERVE
    page_count = len(raw) // PAGE_SIZE
    output = bytearray()
    for page_index in range(page_count):
        page = bytearray(raw[page_index * PAGE_SIZE : (page_index + 1) * PAGE_SIZE])
        page[-RESERVE:] = b"\x00" * RESERVE
        output.extend(page)
    return bytes(output)


def _encrypt_sqlcipher_like(plain_bytes: bytes, output_path: Path, key_hex: str, salt_hex: str):
    key = bytes.fromhex(key_hex)
    salt = bytes.fromhex(salt_hex)
    page_count = len(plain_bytes) // PAGE_SIZE
    encrypted = bytearray()
    for page_index in range(page_count):
        page = plain_bytes[page_index * PAGE_SIZE : (page_index + 1) * PAGE_SIZE]
        iv = bytes([page_index + 1]) * 16
        if page_index == 0:
            ct = AES.new(key, AES.MODE_CBC, iv).encrypt(page[16 : PAGE_SIZE - RESERVE])
            encrypted.extend(salt)
            encrypted.extend(ct)
        else:
            ct = AES.new(key, AES.MODE_CBC, iv).encrypt(page[: PAGE_SIZE - RESERVE])
            encrypted.extend(ct)
        encrypted.extend(iv)
        encrypted.extend(b"\x00" * 64)
    output_path.write_bytes(bytes(encrypted))


def test_parse_key_log_reads_rounds_salt_pw_dk_records(tmp_path: Path):
    log_path = tmp_path / "keys.log"
    log_path.write_text(
        (
            "rounds=64000\n"
            "salt=aaaabbbbccccdddd\n"
            "pw=password1\n"
            "dk=dk001\n"
            "\n"
            "rounds=128000\n"
            "salt=1111222233334444\n"
            "pw=password2\n"
            "dk=dk002\n"
        ),
        encoding="utf-8",
    )

    entries = parse_key_log(log_path)

    assert entries == [
        {
            "rounds": 64000,
            "salt": "aaaabbbbccccdddd",
            "pw": "password1",
            "dk": "dk001",
        },
        {
            "rounds": 128000,
            "salt": "1111222233334444",
            "pw": "password2",
            "dk": "dk002",
        },
    ]


def test_match_key_by_salt_returns_matching_entry():
    entries = [
        {"rounds": 64000, "salt": "aaaabbbb", "pw": "p1", "dk": "d1"},
        {"rounds": 64000, "salt": "ccccdddd", "pw": "p2", "dk": "d2"},
    ]

    matched = match_key_by_salt(entries, "ccccdddd")

    assert matched == {"rounds": 64000, "salt": "ccccdddd", "pw": "p2", "dk": "d2"}


def test_match_key_by_salt_raises_when_no_match():
    entries = [{"rounds": 64000, "salt": "aaaabbbb", "pw": "p1", "dk": "d1"}]

    with pytest.raises(RuntimeError, match="No key entry found for salt"):
        match_key_by_salt(entries, "ffffeeee")


def test_parse_key_log_raises_for_malformed_record_line(tmp_path: Path):
    log_path = tmp_path / "keys.log"
    log_path.write_text(
        (
            "rounds=64000\n"
            "salt=aaaabbbbccccdddd\n"
            "pw=password1\n"
            "bad line\n"
            "dk=dk001\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Malformed key log line"):
        parse_key_log(log_path)


def test_parse_key_log_raises_for_incomplete_record(tmp_path: Path):
    log_path = tmp_path / "keys.log"
    log_path.write_text(
        (
            "rounds=64000\n"
            "salt=aaaabbbbccccdddd\n"
            "pw=password1\n"
            "\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Incomplete key log record"):
        parse_key_log(log_path)


def test_parse_key_log_raises_for_non_integer_rounds(tmp_path: Path):
    log_path = tmp_path / "keys.log"
    log_path.write_text(
        (
            "rounds=not-a-number\n"
            "salt=aaaabbbbccccdddd\n"
            "pw=password1\n"
            "dk=dk001\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Invalid rounds value"):
        parse_key_log(log_path)


def test_decrypt_sqlcipher_db_restores_openable_sqlite_database(tmp_path: Path):
    plain_path = tmp_path / "plain.db"
    encrypted_path = tmp_path / "encrypted.db"
    decrypted_path = tmp_path / "decrypted.db"
    key_hex = "11" * 32
    salt_hex = "22" * 16

    conn = sqlite3.connect(plain_path)
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo(value) VALUES ('hello')")
    conn.commit()
    conn.close()

    plain_bytes = _prepare_sqlcipher_plaintext(plain_path)
    _encrypt_sqlcipher_like(plain_bytes, encrypted_path, key_hex, salt_hex)

    decrypt_sqlcipher_db(encrypted_path, key_hex, decrypted_path)

    assert decrypted_path.read_bytes() == plain_bytes
