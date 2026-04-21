import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.export_chat import (
    _wait_for_capture_ready,
    build_parser,
    main,
    run_export,
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


def test_run_export_writes_json_csv_and_html(tmp_path: Path, monkeypatch):
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

    json_path = output_dir / "messages.json"
    csv_path = output_dir / "messages.csv"
    html_path = output_dir / "report.html"

    assert json_path.exists()
    assert csv_path.exists()
    assert html_path.exists()
    assert captured_key_log_paths
    assert captured_key_log_paths[0].parent != output_dir
    assert not (output_dir / "wechat-keys.log").exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["chat"]["session_id"] == "s-2"
    assert payload["messages"][0]["id"] == "m-1"


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
