import csv
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


CSV_FIELDS = [
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


def list_chat_sessions(conn: sqlite3.Connection) -> List[Dict[str, str]]:
    rows = conn.execute(
        """
        SELECT session_id, chat_name, chat_type
        FROM sessions
        ORDER BY lower(chat_name), session_id
        """
    ).fetchall()
    return [
        {
            "session_id": row[0],
            "chat_name": row[1],
            "chat_type": row[2],
        }
        for row in rows
    ]


def resolve_chat_session(
    conn: sqlite3.Connection,
    chat_name: str,
    chat_type: Optional[str] = None,
) -> Dict[str, str]:
    sessions = list_chat_sessions(conn)
    exact_matches = [
        session
        for session in sessions
        if session["chat_name"] == chat_name
        and (chat_type is None or session["chat_type"] == chat_type)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]

    fuzzy_matches = [
        session
        for session in sessions
        if chat_name.lower() in session["chat_name"].lower()
        and (chat_type is None or session["chat_type"] == chat_type)
    ]
    if not fuzzy_matches:
        raise ValueError(f"no matching chat session found for {chat_name!r}")
    if len(fuzzy_matches) > 1:
        raise ValueError(f"multiple chat sessions matched {chat_name!r}")
    return fuzzy_matches[0]


def normalize_messages(
    conn: sqlite3.Connection,
    session: Dict[str, str],
) -> List[Dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            msg_id,
            sender,
            is_outgoing,
            ts,
            raw_type,
            text_content,
            quote_text,
            file_name,
            file_path
        FROM messages
        WHERE session_id = ?
        ORDER BY ts, msg_id
        """,
        (session["session_id"],),
    ).fetchall()

    normalized: List[Dict[str, object]] = []
    for row in rows:
        normalized.append(
            {
                "id": row[0],
                "session_id": session["session_id"],
                "chat_name": session["chat_name"],
                "chat_type": session["chat_type"],
                "sender": row[1],
                "is_outgoing": bool(row[2]),
                "timestamp": row[3],
                "msg_type": row[4],
                "text": row[5] or "",
                "quote_text": row[6] or "",
                "file_name": row[7] or "",
                "file_path": row[8] or "",
            }
        )
    return normalized


def export_messages_csv(messages: List[Dict[str, object]], output_path: Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for message in messages:
            writer.writerow({field: message.get(field, "") for field in CSV_FIELDS})
