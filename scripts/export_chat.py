import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.generate_chat_report import write_report
from scripts.parse_chat import (
    export_messages_csv,
    list_chat_sessions,
    normalize_messages,
    resolve_chat_session,
)
from scripts.wechat_decrypt import match_key_by_salt, parse_key_log
from scripts.wechat_runtime import (
    capture_runtime_key_log,
    ensure_supported_platform,
    find_chat_db_candidates,
    find_signed_wechat_app,
    open_chat_db,
    read_db_salt_hex,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export WeChat chat messages and report.")
    parser.add_argument("--chat", help="Chat display name to export.")
    parser.add_argument("--chat-type", help="Optional chat type filter, e.g. contact/group.")
    parser.add_argument("--output", help="Output directory for export artifacts.")
    parser.add_argument(
        "--list-chats",
        action="store_true",
        help="List available chat sessions and exit.",
    )
    parser.add_argument(
        "--documents-root",
        help="Override WeChat documents root path (defaults to ~/Documents).",
    )
    return parser


def _resolve_documents_root(documents_root: Optional[Path] = None) -> Path:
    if documents_root is None:
        return (
            Path.home()
            / "Library"
            / "Containers"
            / "com.tencent.xinWeChat"
            / "Data"
            / "Documents"
        )
    return Path(documents_root)


def _prepare_connection(key_log_path: Path, documents_root: Optional[Path] = None):
    ensure_supported_platform(sys.platform)
    resolved_documents_root = _resolve_documents_root(documents_root)
    app_path = find_signed_wechat_app()
    db_candidates = find_chat_db_candidates(resolved_documents_root)
    if not db_candidates:
        raise RuntimeError(
            f"No WeChat chat database candidates found under {resolved_documents_root}"
        )
    db_path = db_candidates[0]
    capture_runtime_key_log(app_path, key_log_path)
    salt_hex = read_db_salt_hex(db_path)
    key_entries = parse_key_log(key_log_path)
    key_entry = match_key_by_salt(key_entries, salt_hex)
    return open_chat_db(db_path, key_entry)


def _close_if_possible(conn) -> None:
    close = getattr(conn, "close", None)
    if callable(close):
        close()


def run_export(
    chat_name,
    chat_type,
    output_dir,
    documents_root=None,
):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        key_log_path = Path(temp_dir) / "wechat-keys.log"
        conn = _prepare_connection(key_log_path, documents_root=documents_root)
        try:
            session = resolve_chat_session(conn, chat_name=chat_name, chat_type=chat_type)
            messages = normalize_messages(conn, session)
        finally:
            _close_if_possible(conn)

    export_data = {
        "chat": session,
        "messages": messages,
    }
    (output / "messages.json").write_text(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    export_messages_csv(messages, output / "messages.csv")
    write_report(export_data, output / "report.html")


def run_list_chats(documents_root=None):
    with tempfile.TemporaryDirectory() as temp_dir:
        key_log_path = Path(temp_dir) / "wechat-keys.log"
        conn = _prepare_connection(key_log_path, documents_root=documents_root)
        try:
            sessions = list_chat_sessions(conn)
        finally:
            _close_if_possible(conn)

    for session in sessions:
        print(
            f"{session.get('chat_type', '')}\t"
            f"{session.get('chat_name', '')}\t"
            f"{session.get('session_id', '')}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_chats:
        run_list_chats(documents_root=args.documents_root)
        return 0

    if not args.chat or not args.output:
        parser.error("--chat and --output are required unless --list-chats is used")

    run_export(
        chat_name=args.chat,
        chat_type=args.chat_type,
        output_dir=args.output,
        documents_root=args.documents_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
