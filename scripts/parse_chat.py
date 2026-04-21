import csv
import hashlib
import re
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


def _table_exists(conn, table_name: str, schema: str = "main") -> bool:
    query = f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?"
    return conn.execute(query, (table_name,)).fetchone() is not None


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _resolve_display_name(remark: str, nick_name: str, fallback: str) -> str:
    return (remark or "").strip() or (nick_name or "").strip() or fallback


def _list_real_wechat_sessions(conn) -> List[Dict[str, str]]:
    rows = conn.execute(
        """
        SELECT
            s.username AS session_id,
            COALESCE(NULLIF(c.remark, ''), NULLIF(c.nick_name, ''), s.username) AS chat_name,
            CASE
                WHEN s.username LIKE '%@chatroom' OR IFNULL(c.chat_room_type, 0) != 0 THEN 'group'
                ELSE 'contact'
            END AS chat_type
        FROM SessionTable AS s
        LEFT JOIN contact_db.contact AS c
            ON c.username = s.username
        WHERE IFNULL(s.is_hidden, 0) = 0
        ORDER BY lower(chat_name), s.username
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


def _decode_message_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore")
    else:
        text = str(value)
    text = text.replace("\x00", "")
    text = "".join(
        ch
        for ch in text
        if ch in {"\n", "\r", "\t"} or ord(ch) >= 32
    )
    return text.strip()


def _is_incoming_message(source: object) -> bool:
    if isinstance(source, bytes):
        return b"<msgsource>" in source.lower()
    if isinstance(source, str):
        return "<msgsource>" in source.lower()
    return False


def _find_message_schema_and_table(conn, session_id: str) -> Optional[tuple]:
    table_name = f"Msg_{hashlib.md5(session_id.encode('utf-8')).hexdigest()}"
    db_rows = conn.execute("PRAGMA database_list").fetchall()
    for _, schema_name, _ in db_rows:
        if _table_exists(conn, table_name, schema=schema_name):
            return schema_name, table_name
    return None


def _contact_names_by_id(conn) -> Dict[int, str]:
    rows = conn.execute(
        """
        SELECT id, username, IFNULL(remark, ''), IFNULL(nick_name, '')
        FROM contact_db.contact
        """
    ).fetchall()
    return {
        int(row[0]): _resolve_display_name(row[2], row[3], row[1])
        for row in rows
        if row[0] is not None
    }


def _contact_id_by_username(conn) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT id, username
        FROM contact_db.contact
        """
    ).fetchall()
    return {
        str(row[1]): int(row[0])
        for row in rows
        if row[0] is not None and row[1] is not None
    }


def _normalize_real_wechat_messages(
    conn,
    session: Dict[str, str],
) -> List[Dict[str, object]]:
    located = _find_message_schema_and_table(conn, session["session_id"])
    if located is None:
        raise ValueError(
            f"no message table found for chat session {session['session_id']!r}"
        )
    schema_name, table_name = located
    contact_names = _contact_names_by_id(conn)
    contact_ids = _contact_id_by_username(conn)
    self_contact_id = contact_ids.get(getattr(conn, "self_username", ""))
    self_display_name = getattr(conn, "self_display_name", "我")
    query = f"""
        SELECT
            local_id,
            local_type,
            sort_seq,
            real_sender_id,
            create_time,
            status,
            source,
            message_content,
            compress_content
        FROM {_quote_identifier(schema_name)}.{_quote_identifier(table_name)}
        ORDER BY sort_seq, local_id
    """
    rows = conn.execute(query).fetchall()
    normalized: List[Dict[str, object]] = []
    for row in rows:
        local_id, local_type, sort_seq, real_sender_id, create_time, status, source, message_content, compress_content = row
        if local_type == 10000:
            msg_type = "system"
        elif local_type == 1:
            msg_type = "text"
        else:
            msg_type = f"type_{local_type}"
        incoming = _is_incoming_message(source)
        if msg_type == "system":
            sender = "系统"
            is_outgoing = False
        elif session["chat_type"] == "group":
            sender = contact_names.get(real_sender_id, session["chat_name"])
            is_outgoing = (
                self_contact_id is not None and real_sender_id == self_contact_id
            )
        else:
            sender = session["chat_name"] if incoming else self_display_name
            is_outgoing = not incoming
        if msg_type in {"system", "text"}:
            text = _decode_message_text(message_content)
            if not text:
                text = _decode_message_text(compress_content)
        else:
            text = _decode_message_text(compress_content)
            if not text:
                text = f"[未支持的消息类型 {local_type}]"
        normalized.append(
            {
                "id": str(local_id),
                "session_id": session["session_id"],
                "chat_name": session["chat_name"],
                "chat_type": session["chat_type"],
                "sender": sender,
                "is_outgoing": is_outgoing,
                "timestamp": str(create_time),
                "msg_type": msg_type,
                "text": text,
                "quote_text": "",
                "file_name": "",
                "file_path": "",
            }
        )
    return normalized


def list_chat_sessions(conn: sqlite3.Connection) -> List[Dict[str, str]]:
    if _table_exists(conn, "SessionTable") and _table_exists(
        conn, "contact", schema="contact_db"
    ):
        return _list_real_wechat_sessions(conn)
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
    if _table_exists(conn, "SessionTable"):
        return _normalize_real_wechat_messages(conn, session)
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
    serialized_rows: List[Dict[str, object]] = []
    for index, message in enumerate(messages):
        missing_fields = [field for field in CSV_FIELDS if field not in message]
        if missing_fields:
            raise ValueError(
                "missing required CSV fields at row "
                f"{index}: {', '.join(missing_fields)}"
            )
        serialized_rows.append({field: message[field] for field in CSV_FIELDS})

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(serialized_rows)
