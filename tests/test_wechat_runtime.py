import sys
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import ANY

import pytest

from scripts.parse_chat import list_chat_sessions, normalize_messages, resolve_chat_session
from scripts.wechat_runtime import (
    capture_runtime_key_log,
    ensure_supported_platform,
    find_chat_db_candidates,
    find_signed_wechat_app,
    open_chat_db,
)


def test_ensure_supported_platform_accepts_darwin():
    assert ensure_supported_platform("darwin") == "darwin"


def test_ensure_supported_platform_rejects_linux_with_macos_error():
    with pytest.raises(RuntimeError, match="macOS"):
        ensure_supported_platform("linux")


def test_find_signed_wechat_app_prefers_desktop_app(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    desktop_app = home / "Desktop" / "WeChat.app"
    executable = desktop_app / "Contents" / "MacOS" / "WeChat"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    codesign_calls = []

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        codesign_calls.append((cmd, capture_output, text, check))
        return FakeResult()

    monkeypatch.setattr("scripts.wechat_runtime.subprocess.run", fake_run)

    found = find_signed_wechat_app()

    assert found == desktop_app
    assert codesign_calls == [
        (
            ["codesign", "--verify", "--deep", "--strict", str(desktop_app)],
            True,
            True,
            False,
        )
    ]


def test_find_signed_wechat_app_raises_when_desktop_app_missing(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(RuntimeError, match="Desktop/WeChat.app"):
        find_signed_wechat_app()


def test_find_signed_wechat_app_raises_when_bundle_structure_is_invalid(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    desktop_app = home / "Desktop" / "WeChat.app"
    desktop_app.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    with pytest.raises(RuntimeError, match="Contents/MacOS/WeChat"):
        find_signed_wechat_app()


def test_find_signed_wechat_app_raises_when_codesign_verification_fails(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    desktop_app = home / "Desktop" / "WeChat.app"
    executable = desktop_app / "Contents" / "MacOS" / "WeChat"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    class FakeResult:
        returncode = 1
        stderr = "code object is not signed at all"

    monkeypatch.setattr(
        "scripts.wechat_runtime.subprocess.run",
        lambda cmd, capture_output, text, check: FakeResult(),
    )

    with pytest.raises(RuntimeError, match="code object is not signed at all"):
        find_signed_wechat_app()


def test_find_chat_db_candidates_returns_only_scoped_session_db_files(tmp_path: Path):
    documents_root = tmp_path / "Documents"
    db_a = documents_root / "xwechat_files" / "user_a" / "db_storage" / "session" / "chat_a.db"
    db_b = documents_root / "xwechat_files" / "user_b" / "db_storage" / "session" / "chat_b.db"
    ignored_other_dir = documents_root / "xwechat_files" / "user_a" / "db_storage" / "other" / "chat_c.db"
    ignored_other_root = documents_root / "other" / "db_storage" / "session" / "chat_d.db"
    ignored_txt = documents_root / "xwechat_files" / "user_a" / "db_storage" / "session" / "notes.txt"
    db_a.parent.mkdir(parents=True)
    db_b.parent.mkdir(parents=True)
    ignored_other_dir.parent.mkdir(parents=True)
    ignored_other_root.parent.mkdir(parents=True)
    db_a.write_text("", encoding="utf-8")
    db_b.write_text("", encoding="utf-8")
    ignored_other_dir.write_text("", encoding="utf-8")
    ignored_other_root.write_text("", encoding="utf-8")
    ignored_txt.write_text("", encoding="utf-8")

    candidates = find_chat_db_candidates(documents_root)

    assert candidates == [db_a, db_b]


def test_find_chat_db_candidates_raises_actionable_error_when_documents_are_unreadable(
    tmp_path: Path, monkeypatch
):
    documents_root = tmp_path / "Documents"
    documents_root.mkdir()

    def fake_iterdir(self):
        raise PermissionError(1, "Operation not permitted", str(self))

    monkeypatch.setattr("scripts.wechat_runtime.Path.iterdir", fake_iterdir)

    with pytest.raises(RuntimeError, match="Full Disk Access"):
        find_chat_db_candidates(documents_root)


def test_find_chat_db_candidates_raises_actionable_error_when_documents_root_is_missing(
    tmp_path: Path,
):
    documents_root = tmp_path / "missing"

    with pytest.raises(RuntimeError, match="does not exist"):
        find_chat_db_candidates(documents_root)


def test_capture_runtime_key_log_runs_frida_subprocess(
    tmp_path: Path, monkeypatch
):
    app_path = tmp_path / "Desktop" / "WeChat.app"
    log_path = tmp_path / "capture" / "wechat-keys.log"
    calls = []

    class FakeResult:
        returncode = 0
        stdout = "capture ok"
        stderr = ""

    def fake_run(cmd, capture_output, text, check):
        calls.append((cmd, capture_output, text, check))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "rounds=256000\npw=0011\nsalt=aabbccdd\ndk=ffeeddcc\n\n",
            encoding="utf-8",
        )
        return FakeResult()

    monkeypatch.setattr("scripts.wechat_runtime.subprocess.run", fake_run)

    returned_path = capture_runtime_key_log(app_path, log_path, wait_seconds=5)

    assert returned_path == log_path
    assert calls == [
        (
            [
                sys.executable,
                "-c",
                ANY,
                str(log_path),
                str(app_path),
                "5",
                "-",
            ],
            True,
            True,
            False,
        )
    ]


def test_capture_runtime_key_log_raises_with_subprocess_details(
    tmp_path: Path, monkeypatch
):
    app_path = tmp_path / "Desktop" / "WeChat.app"
    log_path = tmp_path / "capture" / "wechat-keys.log"

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "frida is not installed"

    monkeypatch.setattr(
        "scripts.wechat_runtime.subprocess.run",
        lambda cmd, capture_output, text, check: FakeResult(),
    )

    with pytest.raises(RuntimeError, match="frida is not installed"):
        capture_runtime_key_log(app_path, log_path, wait_seconds=5)


def test_capture_runtime_key_log_supports_manual_ready_signal(
    tmp_path: Path, monkeypatch
):
    app_path = tmp_path / "Desktop" / "WeChat.app"
    log_path = tmp_path / "capture" / "wechat-keys.log"
    popen_calls = []

    class FakeProcess:
        def __init__(self, cmd):
            self.cmd = cmd
            self.returncode = 0

        def communicate(self):
            ready_signal = Path(self.cmd[6])
            assert ready_signal.exists()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                "rounds=256000\npw=0011\nsalt=aabbccdd\ndk=ffeeddcc\n\n",
                encoding="utf-8",
            )
            return ("capture ok", "")

    def fake_popen(cmd, stdout, stderr, text):
        popen_calls.append((cmd, stdout, stderr, text))
        return FakeProcess(cmd)

    monkeypatch.setattr("scripts.wechat_runtime.subprocess.Popen", fake_popen)

    returned_path = capture_runtime_key_log(
        app_path,
        log_path,
        wait_seconds=5,
        prompt_fn=lambda: None,
    )

    assert returned_path == log_path
    assert popen_calls
    assert popen_calls[0][0][:3] == [sys.executable, "-c", ANY]
    assert popen_calls[0][0][6].endswith(".ready")


def test_open_chat_db_decrypts_and_attaches_related_databases(
    tmp_path: Path, monkeypatch
):
    user_root = tmp_path / "xwechat_files" / "wxid_self" / "db_storage"
    session_db = user_root / "session" / "session.db"
    contact_db = user_root / "contact" / "contact.db"
    message_db = user_root / "message" / "message_0.db"
    for path in [session_db, contact_db, message_db]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"encrypted-placeholder")

    plain_session = tmp_path / "plain_session.db"
    plain_contact = tmp_path / "plain_contact.db"
    plain_message = tmp_path / "plain_message.db"

    conn = sqlite3.connect(plain_session)
    conn.executescript(
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
    conn.commit()
    conn.close()

    conn = sqlite3.connect(plain_contact)
    conn.executescript(
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
            (1, 'wxid_self', 0, '', '', 0, 0, 0, '', '', '', 'Self User', '', '', '', '', '', 0, 0, '', NULL, 0),
            (2, 'wxid_friend', 0, '', '', 0, 0, 0, '', '', '', 'Sample Contact', '', '', '', '', '', 0, 0, '', NULL, 0);
        """
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(plain_message)
    conn.executescript(
        """
        CREATE TABLE Msg_d5616d78f22fe35c632f66cabecfc82d (
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
        INSERT INTO Msg_d5616d78f22fe35c632f66cabecfc82d VALUES
            (1, 11, 1, 1776685332001, 2, 1776685332, 3, 0, 0, 129, 2, X'3C6D7367736F757263653E', '你好', '', X'080310025800', NULL, NULL),
            (2, 12, 1, 1776685346000, 1, 1776685346, 3, 0, 0, 130, 2, X'00FF', 'hello', '', X'080310025800', NULL, NULL);
        """
    )
    conn.commit()
    conn.close()

    salt_map = {
        session_db: "11" * 16,
        contact_db: "22" * 16,
        message_db: "33" * 16,
    }
    source_map = {
        session_db: plain_session,
        contact_db: plain_contact,
        message_db: plain_message,
    }

    monkeypatch.setattr(
        "scripts.wechat_runtime.read_db_salt_hex",
        lambda path: salt_map[Path(path)],
    )
    monkeypatch.setattr(
        "scripts.wechat_runtime.decrypt_sqlcipher_db",
        lambda encrypted_path, key_hex, output_path: shutil.copyfile(
            source_map[Path(encrypted_path)], output_path
        )
        or output_path,
    )

    key_entries = [
        {"rounds": 256000, "salt": salt_map[session_db], "pw": "pw", "dk": "aa" * 32},
        {"rounds": 256000, "salt": salt_map[contact_db], "pw": "pw", "dk": "bb" * 32},
        {"rounds": 256000, "salt": salt_map[message_db], "pw": "pw", "dk": "cc" * 32},
    ]

    chat_conn = open_chat_db(session_db, key_entries)
    try:
        sessions = list_chat_sessions(chat_conn)
        session = resolve_chat_session(chat_conn, "Sample Contact", "contact")
        messages = normalize_messages(chat_conn, session)
    finally:
        chat_conn.close()

    assert sessions == [
        {
            "session_id": "wxid_friend",
            "chat_name": "Sample Contact",
            "chat_type": "contact",
        }
    ]
    assert [m["text"] for m in messages] == ["你好", "hello"]
