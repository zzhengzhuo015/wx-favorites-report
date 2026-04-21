import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.export_chat import (
    _build_chat_record_export,
    _wait_for_capture_ready,
    build_parser,
    main,
    run_export,
    run_export_all,
    run_list_chats,
)
from scripts.wechat_runtime import open_chat_db


def test_build_parser_accepts_chat_and_output(tmp_path: Path):
    parser = build_parser()

    args = parser.parse_args(
        ["--chat", "Project Group", "--output", str(tmp_path / "out")]
    )

    assert args.chat == "Project Group"
    assert args.output == str(tmp_path / "out")


def test_build_parser_rejects_invalid_chat_type():
    parser = build_parser()

    with pytest.raises(SystemExit, match="2"):
        parser.parse_args(["--chat-type", "groop"])


def test_wait_for_capture_ready_accepts_enter_and_ready(capsys):
    replies = iter(["later", "ready"])

    _wait_for_capture_ready(prompt_fn=lambda _: next(replies))

    captured = capsys.readouterr()
    assert "未识别输入" in captured.err


def test_build_chat_record_export_matches_external_schema():
    export_data = {
        "chat": {
            "session_id": "room@chatroom",
            "chat_name": "Project Group",
            "chat_type": "group",
        },
        "messages": [
            {
                "id": "m-1",
                "session_id": "room@chatroom",
                "chat_name": "Project Group",
                "chat_type": "group",
                "sender": "Alice",
                "sender_id": "wxid_alice",
                "is_outgoing": False,
                "timestamp": "1776685332",
                "msg_type": "text",
                "text": "Daily standup at 10",
                "quote_text": "",
                "file_name": "",
                "file_path": "",
            },
            {
                "id": "m-2",
                "session_id": "room@chatroom",
                "chat_name": "Project Group",
                "chat_type": "group",
                "sender": "Self User",
                "sender_id": "wxid_self",
                "is_outgoing": True,
                "timestamp": "1776685399",
                "msg_type": "file",
                "text": "",
                "quote_text": "",
                "file_name": "roadmap.pdf",
                "file_path": "/tmp/roadmap.pdf",
            },
        ],
    }

    payload = _build_chat_record_export(
        export_data,
        exported_at=1776240866,
        generator="CipherTalk",
    )

    assert payload == {
        "chatlab": {
            "version": "0.0.2",
            "exportedAt": 1776240866,
            "generator": "CipherTalk",
        },
        "meta": {
            "name": "Project Group",
            "platform": "wechat",
            "type": "group",
            "ownerId": "wxid_self",
            "groupId": "room@chatroom",
        },
        "members": [
            {"platformId": "wxid_alice", "accountName": "Alice"},
            {"platformId": "wxid_self", "accountName": "Self User"},
        ],
        "messages": [
            {
                "sender": "wxid_alice",
                "accountName": "Alice",
                "timestamp": 1776685332,
                "type": 0,
                "content": "Daily standup at 10",
                "platformMessageId": "m-1",
            },
            {
                "sender": "wxid_self",
                "accountName": "Self User",
                "timestamp": 1776685399,
                "type": 4,
                "content": "[文件] roadmap.pdf",
                "platformMessageId": "m-2",
            },
        ],
    }


def test_run_export_writes_only_json(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "export"
    documents_root = tmp_path / "Documents"
    fake_conn = object()
    captured_key_log_paths = []
    session = {
        "session_id": "s-2",
        "chat_name": "Project Group",
        "chat_type": "group",
    }
    messages = [
        {
            "id": "m-1",
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
            "sender": "Alice",
            "sender_id": "wxid_alice",
            "is_outgoing": False,
            "timestamp": "2026-04-20T09:00:00",
            "msg_type": "text",
            "text": "Daily standup at 10",
            "quote_text": "",
            "file_name": "",
            "file_path": "",
        }
    ]

    monkeypatch.setattr("scripts.export_chat.ensure_supported_platform", lambda _: "darwin")
    monkeypatch.setattr(
        "scripts.export_chat.find_signed_wechat_app",
        lambda: Path("/Applications/WeChat.app"),
    )
    monkeypatch.setattr(
        "scripts.export_chat.find_chat_db_candidates",
        lambda root: [Path(root) / "xwechat_files" / "user" / "db_storage" / "session" / "chat.db"],
    )
    monkeypatch.setattr(
        "scripts.export_chat.capture_runtime_key_log",
        lambda app_path, log_path, prompt_fn=None: captured_key_log_paths.append(Path(log_path)),
    )
    monkeypatch.setattr("scripts.export_chat.read_db_salt_hex", lambda _: "aaaabbbbccccdddd")
    monkeypatch.setattr(
        "scripts.export_chat.parse_key_log",
        lambda _: [{"rounds": 64000, "salt": "aaaabbbbccccdddd", "pw": "pw", "dk": "dk"}],
    )
    monkeypatch.setattr(
        "scripts.export_chat.match_key_by_salt",
        lambda entries, salt_hex: {"rounds": 64000, "salt": salt_hex, "pw": "pw", "dk": "dk"},
    )
    monkeypatch.setattr("scripts.export_chat.open_chat_db", lambda db_path, key_entry: fake_conn)
    monkeypatch.setattr("scripts.export_chat.resolve_chat_session", lambda conn, chat_name, chat_type: session)
    monkeypatch.setattr("scripts.export_chat.normalize_messages", lambda conn, resolved: messages)

    run_export(
        chat_name="Project Group",
        chat_type="group",
        output_dir=output_dir,
        documents_root=documents_root,
    )

    json_path = output_dir / "Project Group.json"
    assert json_path.exists()
    assert not (output_dir / "Project Group.csv").exists()
    assert not (output_dir / "Project Group.html").exists()
    assert captured_key_log_paths
    assert captured_key_log_paths[0].parent != output_dir
    assert not (output_dir / "wechat-keys.log").exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["meta"]["groupId"] == "s-2"
    assert payload["meta"]["type"] == "group"
    assert payload["messages"][0]["platformMessageId"] == "m-1"
    assert payload["messages"][0]["accountName"] == "Alice"


def test_run_export_all_names_json_after_chat(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "export-all"
    fake_conn = object()
    sessions = [
        {
            "session_id": "s-group",
            "chat_name": "黑手册目前唯一群🪺🐉",
            "chat_type": "group",
        },
        {
            "session_id": "s-contact",
            "chat_name": "Alice",
            "chat_type": "contact",
        },
    ]

    def resolve_chat_session(conn, chat_name, chat_type):
        return next(
            session
            for session in sessions
            if session["chat_name"] == chat_name and session["chat_type"] == chat_type
        )

    def normalize_messages(conn, session):
        return [
            {
                "id": f"msg-{session['session_id']}",
                "session_id": session["session_id"],
                "chat_name": session["chat_name"],
                "chat_type": session["chat_type"],
                "sender": session["chat_name"],
                "sender_id": session["session_id"],
                "is_outgoing": False,
                "timestamp": "2026-04-20T09:00:00",
                "msg_type": "text",
                "text": "hello",
                "quote_text": "",
                "file_name": "",
                "file_path": "",
            }
        ]

    monkeypatch.setattr("scripts.export_chat._prepare_connection", lambda *args, **kwargs: fake_conn)
    monkeypatch.setattr("scripts.export_chat.list_chat_sessions", lambda conn: sessions)
    monkeypatch.setattr("scripts.export_chat.resolve_chat_session", resolve_chat_session)
    monkeypatch.setattr("scripts.export_chat.normalize_messages", normalize_messages)

    run_export_all(output_dir=output_dir)

    assert (output_dir / "黑手册目前唯一群🪺🐉.json").exists()
    assert (output_dir / "Alice.json").exists()
    assert not (output_dir / "success").exists()
    assert not (output_dir / "failed").exists()
    assert not (output_dir / "manifest.json").exists()
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "Alice.json",
        "黑手册目前唯一群🪺🐉.json",
    ]


def test_run_export_all_deduplicates_duplicate_chat_names(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "export-all"
    fake_conn = object()
    sessions = [
        {
            "session_id": "s-1",
            "chat_name": "Project Group",
            "chat_type": "group",
        },
        {
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
        },
    ]

    def resolve_chat_session(conn, chat_name, chat_type):
        return next(
            session
            for session in sessions
            if session["chat_name"] == chat_name and session["chat_type"] == chat_type
        )

    seen = {"Project Group": 0}

    def resolve_chat_session(conn, chat_name, chat_type):
        seen[chat_name] += 1
        index = seen[chat_name] - 1
        return sessions[index]

    def normalize_messages(conn, session):
        return [
            {
                "id": f"msg-{session['session_id']}",
                "session_id": session["session_id"],
                "chat_name": session["chat_name"],
                "chat_type": session["chat_type"],
                "sender": session["chat_name"],
                "sender_id": session["session_id"],
                "is_outgoing": False,
                "timestamp": "2026-04-20T09:00:00",
                "msg_type": "text",
                "text": session["session_id"],
                "quote_text": "",
                "file_name": "",
                "file_path": "",
            }
        ]

    monkeypatch.setattr("scripts.export_chat._prepare_connection", lambda *args, **kwargs: fake_conn)
    monkeypatch.setattr("scripts.export_chat.list_chat_sessions", lambda conn: sessions)
    monkeypatch.setattr("scripts.export_chat.resolve_chat_session", resolve_chat_session)
    monkeypatch.setattr("scripts.export_chat.normalize_messages", normalize_messages)

    run_export_all(output_dir=output_dir)

    assert (output_dir / "Project Group.json").exists()
    assert (output_dir / "Project Group (2).json").exists()


def test_run_export_prints_progress_updates(tmp_path: Path, monkeypatch, capsys):
    output_dir = tmp_path / "export"
    documents_root = tmp_path / "Documents"
    fake_conn = object()
    session = {
        "session_id": "s-2",
        "chat_name": "Project Group",
        "chat_type": "group",
    }
    messages = [
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

    monkeypatch.setattr("scripts.export_chat.ensure_supported_platform", lambda _: "darwin")
    monkeypatch.setattr(
        "scripts.export_chat.find_signed_wechat_app",
        lambda: Path("/Applications/WeChat.app"),
    )
    monkeypatch.setattr(
        "scripts.export_chat.find_chat_db_candidates",
        lambda root: [Path(root) / "xwechat_files" / "user" / "db_storage" / "session" / "chat.db"],
    )
    monkeypatch.setattr(
        "scripts.export_chat.capture_runtime_key_log",
        lambda app_path, log_path, prompt_fn=None: None,
    )
    monkeypatch.setattr("scripts.export_chat.read_db_salt_hex", lambda _: "aaaabbbbccccdddd")
    monkeypatch.setattr(
        "scripts.export_chat.parse_key_log",
        lambda _: [{"rounds": 64000, "salt": "aaaabbbbccccdddd", "pw": "pw", "dk": "dk"}],
    )
    monkeypatch.setattr(
        "scripts.export_chat.match_key_by_salt",
        lambda entries, salt_hex: {"rounds": 64000, "salt": salt_hex, "pw": "pw", "dk": "dk"},
    )
    monkeypatch.setattr("scripts.export_chat.open_chat_db", lambda db_path, key_entry: fake_conn)
    monkeypatch.setattr("scripts.export_chat.resolve_chat_session", lambda conn, chat_name, chat_type: session)
    monkeypatch.setattr("scripts.export_chat.normalize_messages", lambda conn, resolved: messages)

    run_export(
        chat_name="Project Group",
        chat_type="group",
        output_dir=output_dir,
        documents_root=documents_root,
    )

    captured = capsys.readouterr()
    assert "正在启动桌面版微信并等待密钥" in captured.err
    assert "已捕获密钥，正在匹配聊天数据库" in captured.err
    assert "正在解密并打开聊天数据库" in captured.err
    assert "正在解析聊天消息" in captured.err
    assert "正在生成导出文件" in captured.err


def test_run_export_prints_matched_db_keys_and_usage(tmp_path: Path, monkeypatch, capsys):
    output_dir = tmp_path / "export"
    documents_root = tmp_path / "Documents"
    fake_conn = object()
    session = {
        "session_id": "s-2",
        "chat_name": "Project Group",
        "chat_type": "group",
    }
    messages = [
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
    session_db = (
        documents_root / "xwechat_files" / "user" / "db_storage" / "session" / "session.db"
    )
    contact_db = (
        documents_root / "xwechat_files" / "user" / "db_storage" / "contact" / "contact.db"
    )
    message_db = (
        documents_root / "xwechat_files" / "user" / "db_storage" / "message" / "message_0.db"
    )
    for path in [session_db, contact_db, message_db]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr("scripts.export_chat.ensure_supported_platform", lambda _: "darwin")
    monkeypatch.setattr(
        "scripts.export_chat.find_signed_wechat_app",
        lambda: Path("/Applications/WeChat.app"),
    )
    monkeypatch.setattr(
        "scripts.export_chat.find_chat_db_candidates",
        lambda root: [session_db],
    )
    monkeypatch.setattr(
        "scripts.export_chat.capture_runtime_key_log",
        lambda app_path, log_path, wait_seconds=120, prompt_fn=None: None,
    )
    monkeypatch.setattr(
        "scripts.export_chat.read_db_salt_hex",
        lambda path: {
            session_db: "session-salt",
            contact_db: "contact-salt",
            message_db: "message-salt",
        }[Path(path)],
    )
    monkeypatch.setattr(
        "scripts.export_chat.parse_key_log",
        lambda _: [
            {"rounds": 256000, "salt": "session-salt", "pw": "pw", "dk": "session-dk"},
            {"rounds": 256000, "salt": "contact-salt", "pw": "pw", "dk": "contact-dk"},
            {"rounds": 256000, "salt": "message-salt", "pw": "pw", "dk": "message-dk"},
        ],
    )
    monkeypatch.setattr(
        "scripts.export_chat.match_key_by_salt",
        lambda entries, salt_hex: next(item for item in entries if item["salt"] == salt_hex),
    )
    monkeypatch.setattr("scripts.export_chat.open_chat_db", lambda db_path, key_entry: fake_conn)
    monkeypatch.setattr("scripts.export_chat.resolve_chat_session", lambda conn, chat_name, chat_type: session)
    monkeypatch.setattr("scripts.export_chat.normalize_messages", lambda conn, resolved: messages)

    run_export(
        chat_name="Project Group",
        chat_type="group",
        output_dir=output_dir,
        documents_root=documents_root,
    )

    captured = capsys.readouterr()
    assert "[KEY] session.db" in captured.err
    assert "用途: 会话列表、摘要、排序" in captured.err
    assert "salt: session-salt" in captured.err
    assert "dk: session-dk" in captured.err
    assert "[KEY] contact.db" in captured.err
    assert "用途: 联系人、备注、昵称映射" in captured.err
    assert "[KEY] message_0.db" in captured.err
    assert "用途: 具体消息内容" in captured.err


def test_run_list_chats_prints_sessions(tmp_path: Path, monkeypatch, capsys):
    documents_root = tmp_path / "Documents"
    fake_conn = object()
    sessions = [
        {"session_id": "s-1", "chat_name": "Alice", "chat_type": "contact"},
        {"session_id": "s-2", "chat_name": "Project Group", "chat_type": "group"},
    ]

    monkeypatch.setattr("scripts.export_chat.ensure_supported_platform", lambda _: "darwin")
    monkeypatch.setattr(
        "scripts.export_chat.find_signed_wechat_app",
        lambda: Path("/Applications/WeChat.app"),
    )
    monkeypatch.setattr(
        "scripts.export_chat.find_chat_db_candidates",
        lambda root: [Path(root) / "xwechat_files" / "user" / "db_storage" / "session" / "chat.db"],
    )
    monkeypatch.setattr(
        "scripts.export_chat.capture_runtime_key_log",
        lambda app_path, log_path, prompt_fn=None: None,
    )
    monkeypatch.setattr("scripts.export_chat.read_db_salt_hex", lambda _: "aaaabbbbccccdddd")
    monkeypatch.setattr(
        "scripts.export_chat.parse_key_log",
        lambda _: [{"rounds": 64000, "salt": "aaaabbbbccccdddd", "pw": "pw", "dk": "dk"}],
    )
    monkeypatch.setattr(
        "scripts.export_chat.match_key_by_salt",
        lambda entries, salt_hex: {"rounds": 64000, "salt": salt_hex, "pw": "pw", "dk": "dk"},
    )
    monkeypatch.setattr("scripts.export_chat.open_chat_db", lambda db_path, key_entry: fake_conn)
    monkeypatch.setattr("scripts.export_chat.list_chat_sessions", lambda conn: sessions)

    run_list_chats(documents_root=documents_root)

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "contact\tAlice\ts-1",
        "group\tProject Group\ts-2",
    ]


def test_run_list_chats_uses_wechat_container_documents_root_by_default(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "home"
    expected_documents_root = (
        home / "Library" / "Containers" / "com.tencent.xinWeChat" / "Data" / "Documents"
    )
    fake_conn = object()
    seen_roots = []

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("scripts.export_chat.ensure_supported_platform", lambda _: "darwin")
    monkeypatch.setattr(
        "scripts.export_chat.find_signed_wechat_app",
        lambda: Path("/Applications/WeChat.app"),
    )
    monkeypatch.setattr(
        "scripts.export_chat.find_chat_db_candidates",
        lambda root: seen_roots.append(Path(root))
        or [expected_documents_root / "xwechat_files" / "user" / "db_storage" / "session" / "chat.db"],
    )
    monkeypatch.setattr(
        "scripts.export_chat.capture_runtime_key_log",
        lambda app_path, log_path, prompt_fn=None: None,
    )
    monkeypatch.setattr("scripts.export_chat.read_db_salt_hex", lambda _: "aaaabbbbccccdddd")
    monkeypatch.setattr(
        "scripts.export_chat.parse_key_log",
        lambda _: [{"rounds": 64000, "salt": "aaaabbbbccccdddd", "pw": "pw", "dk": "dk"}],
    )
    monkeypatch.setattr(
        "scripts.export_chat.match_key_by_salt",
        lambda entries, salt_hex: {"rounds": 64000, "salt": salt_hex, "pw": "pw", "dk": "dk"},
    )
    monkeypatch.setattr("scripts.export_chat.open_chat_db", lambda db_path, key_entry: fake_conn)
    monkeypatch.setattr("scripts.export_chat.list_chat_sessions", lambda conn: [])

    run_list_chats()

    assert seen_roots == [expected_documents_root]


def test_run_list_chats_chooses_db_candidate_matching_captured_salt(
    tmp_path: Path, monkeypatch, capsys
):
    documents_root = tmp_path / "Documents"
    fake_conn = object()
    db_a = documents_root / "xwechat_files" / "stale" / "db_storage" / "session" / "session.db"
    db_b = documents_root / "xwechat_files" / "active" / "db_storage" / "session" / "session.db"

    monkeypatch.setattr("scripts.export_chat.ensure_supported_platform", lambda _: "darwin")
    monkeypatch.setattr(
        "scripts.export_chat.find_signed_wechat_app",
        lambda: Path("/Applications/WeChat.app"),
    )
    monkeypatch.setattr(
        "scripts.export_chat.find_chat_db_candidates",
        lambda root: [db_a, db_b],
    )
    monkeypatch.setattr(
        "scripts.export_chat.capture_runtime_key_log",
        lambda app_path, log_path, prompt_fn=None: None,
    )
    monkeypatch.setattr(
        "scripts.export_chat.read_db_salt_hex",
        lambda path: {
            db_a: "aaaa",
            db_b: "bbbb",
        }[Path(path)],
    )
    monkeypatch.setattr(
        "scripts.export_chat.parse_key_log",
        lambda _: [{"rounds": 256000, "salt": "bbbb", "pw": "pw", "dk": "dk"}],
    )
    monkeypatch.setattr(
        "scripts.export_chat.open_chat_db",
        lambda db_path, key_entries: fake_conn if Path(db_path) == db_b else (_ for _ in ()).throw(RuntimeError("wrong db selected")),
    )
    monkeypatch.setattr(
        "scripts.export_chat.list_chat_sessions",
        lambda conn: [{"session_id": "s-1", "chat_name": "Alice", "chat_type": "contact"}],
    )

    run_list_chats(documents_root=documents_root)

    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["contact\tAlice\ts-1"]


def test_main_requires_chat_and_output_unless_list_chats():
    with pytest.raises(SystemExit, match="2"):
        main([])


def test_main_prints_runtime_error_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(
        "scripts.export_chat.run_list_chats",
        lambda documents_root=None: (_ for _ in ()).throw(RuntimeError("permission denied")),
    )

    exit_code = main(["--list-chats"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "[ERROR] permission denied" in captured.err


def test_script_entrypoint_help_runs_from_repo_root():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/export_chat.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--chat" in result.stdout
    assert "--output" in result.stdout


def test_open_chat_db_raises_when_key_entries_do_not_match_db_salt(tmp_path: Path):
    db_path = tmp_path / "chat.db"
    db_path.write_bytes(b"\x00" * 32)

    with pytest.raises(RuntimeError, match="No key entry found for salt"):
        open_chat_db(db_path, key_entry={"dk": "ignored"})
