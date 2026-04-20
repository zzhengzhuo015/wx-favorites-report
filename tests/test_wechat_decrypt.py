from pathlib import Path

import pytest

from scripts.wechat_decrypt import match_key_by_salt, parse_key_log


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
