import csv
import hashlib
import sqlite3
from pathlib import Path

import pytest

from scripts.parse_chat import (
    _decode_message_text,
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


class ConnectionWrapper:
    def __init__(self, conn: sqlite3.Connection, **attrs):
        self._conn = conn
        for key, value in attrs.items():
            setattr(self, key, value)

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def close(self):
        self._conn.close()


def make_real_wechat_fixture(tmp_path: Path) -> ConnectionWrapper:
    session_db = tmp_path / "session.db"
    contact_db = tmp_path / "contact.db"
    message_db = tmp_path / "message_0.db"

    session_conn = sqlite3.connect(session_db)
    session_conn.executescript(
        """
        CREATE TABLE SessionTable (
            username TEXT PRIMARY KEY,
            type INTEGER,
            unread_count INTEGER,
            unread_first_msg_srv_id INTEGER,
            unread_first_pat_msg_local_id INTEGER,
            unread_first_pat_msg_sort_seq INTEGER,
            is_hidden INTEGER,
            summary TEXT,
            draft TEXT,
            status INTEGER,
            last_timestamp INTEGER,
            sort_timestamp INTEGER,
            last_clear_unread_timestamp INTEGER,
            last_msg_locald_id INTEGER,
            last_msg_type INTEGER,
            last_msg_sub_type INTEGER,
            last_msg_sender TEXT,
            last_sender_display_name TEXT,
            last_msg_ext_type INTEGER
        );

        INSERT INTO SessionTable VALUES
            ('wxid_friend', 0, 0, 0, 0, 0, 0, 'hello', '', 0, 1776685346, 1776685346, 1776685362, 3, 1, 0, '', '', 0);
        """
    )
    session_conn.commit()
    session_conn.close()

    contact_conn = sqlite3.connect(contact_db)
    contact_conn.executescript(
        """
        CREATE TABLE contact (
            id INTEGER PRIMARY KEY,
            username TEXT,
            local_type INTEGER,
            alias TEXT,
            encrypt_username TEXT,
            flag INTEGER,
            delete_flag INTEGER,
            verify_flag INTEGER,
            remark TEXT,
            remark_quan_pin TEXT,
            remark_pin_yin_initial TEXT,
            nick_name TEXT,
            pin_yin_initial TEXT,
            quan_pin TEXT,
            big_head_url TEXT,
            small_head_url TEXT,
            head_img_md5 TEXT,
            chat_room_notify INTEGER,
            is_in_chat_room INTEGER,
            description TEXT,
            extra_buffer BLOB,
            chat_room_type INTEGER
        );

        INSERT INTO contact (
            id, username, local_type, alias, encrypt_username, flag, delete_flag, verify_flag,
            remark, remark_quan_pin, remark_pin_yin_initial, nick_name, pin_yin_initial, quan_pin,
            big_head_url, small_head_url, head_img_md5, chat_room_notify, is_in_chat_room,
            description, extra_buffer, chat_room_type
        ) VALUES
            (1, 'wxid_self', 0, '', '', 0, 0, 0, '', '', '', 'Self User', '', '', '', '', '', 0, 0, '', NULL, 0),
            (2, 'wxid_friend', 0, '', '', 0, 0, 0, '', '', '', 'Sample Contact', '', '', '', '', '', 0, 0, '', NULL, 0);
        """
    )
    contact_conn.commit()
    contact_conn.close()

    table_name = "Msg_" + hashlib.md5("wxid_friend".encode("utf-8")).hexdigest()
    message_conn = sqlite3.connect(message_db)
    message_conn.executescript(
        f"""
        CREATE TABLE {table_name} (
            local_id INTEGER PRIMARY KEY,
            server_id INTEGER,
            local_type INTEGER,
            sort_seq INTEGER,
            real_sender_id INTEGER,
            create_time INTEGER,
            status INTEGER,
            upload_status INTEGER,
            download_status INTEGER,
            server_seq INTEGER,
            origin_source INTEGER,
            source BLOB,
            message_content TEXT,
            compress_content TEXT,
            packed_info_data BLOB,
            WCDB_CT_message_content INTEGER DEFAULT NULL,
            WCDB_CT_source INTEGER DEFAULT NULL
        );

        INSERT INTO {table_name} VALUES
            (1, 11, 10000, 1776685332000, 2, 1776685332, 4, 0, 0, 128, 2, X'00', '以上是打招呼的消息', '', X'080310025800', NULL, NULL),
            (2, 12, 1, 1776685332001, 2, 1776685332, 3, 0, 0, 129, 2, X'3C6D7367736F757263653E', '你好', '', X'080310025800', NULL, NULL),
            (3, 13, 1, 1776685346000, 1, 1776685346, 3, 0, 0, 130, 2, X'00FF', 'hello', '', X'080310025800', NULL, NULL),
            (4, 14, 42, 1776688345000, 2, 1776688345, 3, 0, 0, 177, 2, X'3C6D7367736F757263653E', X'28B52FFD604205C51D00AA4B', '', X'080310025800', NULL, NULL);
        """
    )
    message_conn.commit()
    message_conn.close()

    conn = sqlite3.connect(session_db)
    conn.execute(f"ATTACH DATABASE '{contact_db}' AS contact_db")
    conn.execute(f"ATTACH DATABASE '{message_db}' AS message_db_0")
    return ConnectionWrapper(conn, self_username="wxid_self", self_display_name="Self User")


def make_real_wechat_group_fixture(tmp_path: Path) -> ConnectionWrapper:
    session_db = tmp_path / "session_group.db"
    contact_db = tmp_path / "contact_group.db"
    message_db = tmp_path / "message_group.db"

    session_conn = sqlite3.connect(session_db)
    session_conn.executescript(
        """
        CREATE TABLE SessionTable (
            username TEXT PRIMARY KEY,
            type INTEGER,
            unread_count INTEGER,
            unread_first_msg_srv_id INTEGER,
            unread_first_pat_msg_local_id INTEGER,
            unread_first_pat_msg_sort_seq INTEGER,
            is_hidden INTEGER,
            summary TEXT,
            draft TEXT,
            status INTEGER,
            last_timestamp INTEGER,
            sort_timestamp INTEGER,
            last_clear_unread_timestamp INTEGER,
            last_msg_locald_id INTEGER,
            last_msg_type INTEGER,
            last_msg_sub_type INTEGER,
            last_msg_sender TEXT,
            last_sender_display_name TEXT,
            last_msg_ext_type INTEGER
        );

        INSERT INTO SessionTable VALUES
            ('room@chatroom', 0, 0, 0, 0, 0, 0, '群消息', '', 0, 1776685346, 1776685346, 1776685362, 3, 1, 0, '', '', 0);
        """
    )
    session_conn.commit()
    session_conn.close()

    contact_conn = sqlite3.connect(contact_db)
    contact_conn.executescript(
        """
        CREATE TABLE contact (
            id INTEGER PRIMARY KEY,
            username TEXT,
            local_type INTEGER,
            alias TEXT,
            encrypt_username TEXT,
            flag INTEGER,
            delete_flag INTEGER,
            verify_flag INTEGER,
            remark TEXT,
            remark_quan_pin TEXT,
            remark_pin_yin_initial TEXT,
            nick_name TEXT,
            pin_yin_initial TEXT,
            quan_pin TEXT,
            big_head_url TEXT,
            small_head_url TEXT,
            head_img_md5 TEXT,
            chat_room_notify INTEGER,
            is_in_chat_room INTEGER,
            description TEXT,
            extra_buffer BLOB,
            chat_room_type INTEGER
        );

        INSERT INTO contact VALUES
            (1, 'wxid_self', 0, '', '', 0, 0, 0, '', '', '', 'Shared Name', '', '', '', '', '', 0, 0, '', NULL, 0),
            (2, 'wxid_other', 0, '', '', 0, 0, 0, '', '', '', 'Shared Name', '', '', '', '', '', 0, 0, '', NULL, 0),
            (3, 'room@chatroom', 0, '', '', 0, 0, 0, '', '', '', 'Sample Group', '', '', '', '', '', 0, 0, '', NULL, 1);
        """
    )
    contact_conn.commit()
    contact_conn.close()

    table_name = "Msg_" + hashlib.md5("room@chatroom".encode("utf-8")).hexdigest()
    message_conn = sqlite3.connect(message_db)
    message_conn.executescript(
        f"""
        CREATE TABLE {table_name} (
            local_id INTEGER PRIMARY KEY,
            server_id INTEGER,
            local_type INTEGER,
            sort_seq INTEGER,
            real_sender_id INTEGER,
            create_time INTEGER,
            status INTEGER,
            upload_status INTEGER,
            download_status INTEGER,
            server_seq INTEGER,
            origin_source INTEGER,
            source BLOB,
            message_content TEXT,
            compress_content TEXT,
            packed_info_data BLOB,
            WCDB_CT_message_content INTEGER DEFAULT NULL,
            WCDB_CT_source INTEGER DEFAULT NULL
        );

        INSERT INTO {table_name} VALUES
            (1, 11, 1, 1776685332001, 1, 1776685332, 3, 0, 0, 129, 2, X'00', '我发的', '', X'080310025800', NULL, NULL),
            (2, 12, 1, 1776685346000, 2, 1776685346, 3, 0, 0, 130, 2, X'00', '他发的', '', X'080310025800', NULL, NULL);
        """
    )
    message_conn.commit()
    message_conn.close()

    conn = sqlite3.connect(session_db)
    conn.execute(f"ATTACH DATABASE '{contact_db}' AS contact_db")
    conn.execute(f"ATTACH DATABASE '{message_db}' AS message_db_0")
    return ConnectionWrapper(conn, self_username="wxid_self", self_display_name="Shared Name")


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
    assert not output_path.exists()


def test_export_messages_csv_keeps_existing_file_when_validation_fails(tmp_path: Path):
    output_path = tmp_path / "messages.csv"
    original = "id,session_id\nold,s-0\n"
    output_path.write_text(original, encoding="utf-8")
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
        },
        {
            "id": "m-2",
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
            "sender": "Bob",
            "is_outgoing": True,
            "timestamp": "2026-04-20T09:01:00",
            "msg_type": "text",
            "text": "Ack",
            "quote_text": "",
            "file_name": "",
        },
    ]

    with pytest.raises(ValueError, match="missing required CSV fields"):
        export_messages_csv(rows, output_path)

    assert output_path.read_text(encoding="utf-8") == original


def test_list_chat_sessions_supports_real_wechat_schema(tmp_path: Path):
    conn = make_real_wechat_fixture(tmp_path)
    try:
        sessions = list_chat_sessions(conn)
    finally:
        conn.close()

    assert sessions == [
        {
            "session_id": "wxid_friend",
            "chat_name": "Sample Contact",
            "chat_type": "contact",
        }
    ]


def test_normalize_messages_supports_real_wechat_schema(tmp_path: Path):
    conn = make_real_wechat_fixture(tmp_path)
    try:
        session = resolve_chat_session(conn, chat_name="Sample Contact", chat_type="contact")
        messages = normalize_messages(conn, session)
    finally:
        conn.close()

    assert [message["msg_type"] for message in messages] == ["system", "text", "text", "type_42"]
    assert messages[0]["sender"] == "系统"
    assert messages[1]["sender"] == "Sample Contact"
    assert messages[1]["is_outgoing"] is False
    assert messages[2]["sender"] == "Self User"
    assert messages[2]["is_outgoing"] is True
    assert messages[2]["text"] == "hello"
    assert messages[3]["sender"] == "Sample Contact"
    assert messages[3]["is_outgoing"] is False
    assert messages[3]["text"] == "[未支持的消息类型 42]"


def test_decode_message_text_preserves_leading_emoji_and_punctuation():
    assert _decode_message_text("🙂hello") == "🙂hello"
    assert _decode_message_text("+123") == "+123"
    assert _decode_message_text("@ping") == "@ping"


def test_normalize_messages_supports_real_wechat_group_schema_with_duplicate_names(
    tmp_path: Path,
):
    conn = make_real_wechat_group_fixture(tmp_path)
    try:
        session = resolve_chat_session(conn, chat_name="Sample Group", chat_type="group")
        messages = normalize_messages(conn, session)
    finally:
        conn.close()

    assert [message["sender"] for message in messages] == ["Shared Name", "Shared Name"]
    assert [message["is_outgoing"] for message in messages] == [True, False]
    assert [message["text"] for message in messages] == ["我发的", "他发的"]
