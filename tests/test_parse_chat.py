import csv
import sqlite3
from pathlib import Path

import pytest

from scripts.parse_chat import (
    export_messages_csv,
    list_chat_sessions,
    normalize_messages,
    resolve_chat_session,
)


def make_fixture_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "chat_fixture.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            chat_name TEXT NOT NULL,
            chat_type TEXT NOT NULL
        );

        CREATE TABLE messages (
            msg_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            is_outgoing INTEGER NOT NULL,
            ts TEXT NOT NULL,
            raw_type TEXT NOT NULL,
            text_content TEXT DEFAULT '',
            quote_text TEXT DEFAULT '',
            file_name TEXT DEFAULT '',
            file_path TEXT DEFAULT ''
        );

        INSERT INTO sessions(session_id, chat_name, chat_type) VALUES
            ('s-1', 'Alice', 'contact'),
            ('s-2', 'Project Group', 'group'),
            ('s-3', 'Project Group Archive', 'group');

        INSERT INTO messages(msg_id, session_id, sender, is_outgoing, ts, raw_type, text_content, quote_text, file_name, file_path) VALUES
            ('m-1', 's-2', 'Alice', 0, '2026-04-20T09:00:00', 'text', 'Daily standup at 10', '', '', ''),
            ('m-2', 's-2', 'Bob', 1, '2026-04-20T09:05:00', 'reply', '收到', 'Daily standup at 10', '', ''),
            ('m-3', 's-2', 'Alice', 0, '2026-04-20T09:06:00', 'file', '', '', 'roadmap.pdf', '/tmp/roadmap.pdf');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_list_chat_sessions_returns_sorted_sessions(tmp_path: Path):
    db_path = make_fixture_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        sessions = list_chat_sessions(conn)

    assert [item["chat_name"] for item in sessions] == [
        "Alice",
        "Project Group",
        "Project Group Archive",
    ]
    assert sessions[1]["chat_type"] == "group"


def test_resolve_chat_session_prefers_exact_match(tmp_path: Path):
    db_path = make_fixture_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        session = resolve_chat_session(
            conn,
            chat_name="Project Group",
            chat_type="group",
        )

    assert session["session_id"] == "s-2"


def test_resolve_chat_session_raises_for_ambiguous_match(tmp_path: Path):
    db_path = make_fixture_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(ValueError, match="multiple chat sessions"):
            resolve_chat_session(conn, chat_name="Project", chat_type="group")


def test_normalize_messages_maps_common_fields(tmp_path: Path):
    db_path = make_fixture_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        session = resolve_chat_session(
            conn,
            chat_name="Project Group",
            chat_type="group",
        )
        messages = normalize_messages(conn, session)

    assert messages[0]["msg_type"] == "text"
    assert messages[1]["quote_text"] == "Daily standup at 10"
    assert messages[2]["file_name"] == "roadmap.pdf"
    assert messages[2]["chat_name"] == "Project Group"


def test_export_messages_csv_writes_expected_header_and_row_values(tmp_path: Path):
    output_path = tmp_path / "messages.csv"
    rows = [
        {
            "id": "m-1",
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
            "sender": "Alice",
            "is_outgoing": False,
            "timestamp": "2026-04-20T09:00:00",
            "msg_type": "text",
            "text": "Daily standup at 10",
            "quote_text": "",
            "file_name": "",
            "file_path": "",
        }
    ]

    export_messages_csv(rows, output_path)

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        loaded = list(reader)

    assert reader.fieldnames == [
        "id",
        "session_id",
        "chat_name",
        "chat_type",
        "sender",
        "is_outgoing",
        "timestamp",
        "msg_type",
        "text",
        "quote_text",
        "file_name",
        "file_path",
    ]
    assert loaded == [
        {
            "id": "m-1",
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
            "sender": "Alice",
            "is_outgoing": "False",
            "timestamp": "2026-04-20T09:00:00",
            "msg_type": "text",
            "text": "Daily standup at 10",
            "quote_text": "",
            "file_name": "",
            "file_path": "",
        }
    ]


def test_export_messages_csv_raises_for_missing_required_field(tmp_path: Path):
    output_path = tmp_path / "messages.csv"
    rows = [
        {
            "id": "m-1",
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
            "sender": "Alice",
            "is_outgoing": False,
            "timestamp": "2026-04-20T09:00:00",
            "msg_type": "text",
            "text": "Daily standup at 10",
            "quote_text": "",
            "file_name": "",
        }
    ]

    with pytest.raises(ValueError, match="missing required CSV fields"):
        export_messages_csv(rows, output_path)
