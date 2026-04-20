import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.export_chat import build_parser, main, run_export, run_list_chats
from scripts.wechat_runtime import capture_runtime_key_log, open_chat_db


def test_build_parser_accepts_chat_and_output(tmp_path: Path):
    parser = build_parser()

    args = parser.parse_args(
        ["--chat", "Project Group", "--output", str(tmp_path / "out")]
    )

    assert args.chat == "Project Group"
    assert args.output == str(tmp_path / "out")


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
        lambda app_path, log_path: captured_key_log_paths.append(Path(log_path)),
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
    monkeypatch.setattr("scripts.export_chat.capture_runtime_key_log", lambda app_path, log_path: None)
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
    monkeypatch.setattr("scripts.export_chat.capture_runtime_key_log", lambda app_path, log_path: None)
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


def test_main_requires_chat_and_output_unless_list_chats():
    with pytest.raises(SystemExit, match="2"):
        main([])


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


def test_runtime_placeholders_raise_not_implemented(tmp_path: Path):
    db_path = tmp_path / "chat.db"
    db_path.write_bytes(b"\x00" * 32)
    log_path = tmp_path / "wechat-keys.log"

    with pytest.raises(NotImplementedError, match="Task 4 placeholder"):
        capture_runtime_key_log(Path("/Applications/WeChat.app"), log_path)
    with pytest.raises(NotImplementedError, match="Task 4 placeholder"):
        open_chat_db(db_path, key_entry={"dk": "ignored"})
