import argparse
import json
import re
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


def _status(message: str) -> None:
    print(f"[INFO] {message}", file=sys.stderr)


def _key(message: str) -> None:
    print(message, file=sys.stderr)


def _wait_for_capture_ready(prompt_fn=input) -> None:
    while True:
        reply = prompt_fn(
            "请在副本微信中登录并打开目标聊天窗口，准备好后按回车，或输入 ready 后回车继续："
        )
        if reply is None:
            reply = ""
        if reply.strip().lower() in {"", "ready"}:
            return
        _status("未识别输入，请直接按回车，或输入 ready 后回车。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export WeChat chat messages and report.")
    parser.add_argument("--chat", help="Chat display name to export.")
    parser.add_argument(
        "--all-chats",
        action="store_true",
        help="Export all discoverable chats into per-session subdirectories.",
    )
    parser.add_argument(
        "--chat-type",
        choices=["contact", "group"],
        help="Optional chat type filter.",
    )
    parser.add_argument("--output", help="Output directory for export artifacts.")
    parser.add_argument(
        "--list-chats",
        action="store_true",
        help="List available chat sessions and exit.",
    )
    parser.add_argument(
        "--documents-root",
        help=(
            "Override WeChat documents root path (defaults to "
            "~/Library/Containers/com.tencent.xinWeChat/Data/Documents)."
        ),
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


def _chat_db_descriptions(session_db_path: Path):
    db_storage_root = session_db_path.parent.parent
    related = [
        (session_db_path, "会话列表、摘要、排序"),
        (db_storage_root / "contact" / "contact.db", "联系人、备注、昵称映射"),
    ]
    related.extend(
        (path, "具体消息内容")
        for path in sorted((db_storage_root / "message").glob("message_[0-9]*.db"))
    )
    return [(path, purpose) for path, purpose in related if path.exists()]


def _print_matched_keys(session_db_path: Path, key_entries) -> None:
    for db_path, purpose in _chat_db_descriptions(session_db_path):
        salt_hex = read_db_salt_hex(db_path)
        try:
            key_entry = match_key_by_salt(key_entries, salt_hex)
        except RuntimeError:
            continue
        _key(f"[KEY] {db_path.name}")
        _key(f"      用途: {purpose}")
        _key(f"      salt: {salt_hex}")
        _key(f"      dk: {key_entry['dk']}")


def _prepare_connection(key_log_path: Path, documents_root: Optional[Path] = None):
    ensure_supported_platform(sys.platform)
    resolved_documents_root = _resolve_documents_root(documents_root)
    app_path = find_signed_wechat_app()
    db_candidates = find_chat_db_candidates(resolved_documents_root)
    if not db_candidates:
        raise RuntimeError(
            f"No WeChat chat database candidates found under {resolved_documents_root}"
        )
    _status("正在启动桌面版微信并等待密钥，请在副本微信中打开目标聊天窗口...")
    prompt_fn = _wait_for_capture_ready if sys.stdin.isatty() else None
    capture_runtime_key_log(app_path, key_log_path, prompt_fn=prompt_fn)
    _status("已捕获密钥，正在匹配聊天数据库...")
    key_entries = parse_key_log(key_log_path)
    db_path = None
    for candidate in db_candidates:
        salt_hex = read_db_salt_hex(candidate)
        try:
            match_key_by_salt(key_entries, salt_hex)
        except RuntimeError:
            continue
        db_path = candidate
        break
    if db_path is None:
        raise RuntimeError(
            "Captured runtime keys did not match any session database candidate. "
            "Make sure the active WeChat account is the one you are trying to export."
        )
    _print_matched_keys(db_path, key_entries)
    _status("正在解密并打开聊天数据库...")
    return open_chat_db(db_path, key_entries)


def _close_if_possible(conn) -> None:
    close = getattr(conn, "close", None)
    if callable(close):
        close()


def _safe_session_dirname(session: dict) -> str:
    chat_name = str(session.get("chat_name", "")).strip() or "chat"
    session_id = str(session.get("session_id", "")).strip() or "unknown"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", chat_name).strip("-") or "chat"
    safe_session_id = re.sub(r"[^A-Za-z0-9._-]+", "-", session_id).strip("-") or "unknown"
    return f"{safe_name}__{safe_session_id}"


def _write_export_artifacts(output_dir: Path, export_data: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "messages.json").write_text(
        json.dumps(export_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    export_messages_csv(export_data["messages"], output_dir / "messages.csv")
    write_report(export_data, output_dir / "report.html")


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
            _status("正在解析聊天消息...")
            session = resolve_chat_session(conn, chat_name=chat_name, chat_type=chat_type)
            messages = normalize_messages(conn, session)
        finally:
            _close_if_possible(conn)

    export_data = {
        "chat": session,
        "messages": messages,
    }
    _status("正在生成导出文件...")
    _write_export_artifacts(output, export_data)


def run_export_all(output_dir, documents_root=None):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    success_root = output / "success"
    failed_root = output / "failed"
    success_root.mkdir(parents=True, exist_ok=True)
    failed_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        key_log_path = Path(temp_dir) / "wechat-keys.log"
        conn = _prepare_connection(key_log_path, documents_root=documents_root)
        try:
            _status("正在读取会话列表...")
            sessions = list_chat_sessions(conn)
            results = []
            for session in sessions:
                session_dirname = _safe_session_dirname(session)
                _status(f"正在导出会话：{session.get('chat_name', session.get('session_id', ''))}")
                try:
                    resolved_session = resolve_chat_session(
                        conn,
                        chat_name=session["chat_name"],
                        chat_type=session["chat_type"],
                    )
                    messages = normalize_messages(conn, resolved_session)
                    export_data = {"chat": resolved_session, "messages": messages}
                    session_output_dir = success_root / session_dirname
                    _write_export_artifacts(session_output_dir, export_data)
                    results.append(
                        {
                            "session_id": resolved_session["session_id"],
                            "chat_name": resolved_session["chat_name"],
                            "chat_type": resolved_session["chat_type"],
                            "status": "success",
                            "output_dir": str(session_output_dir),
                        }
                    )
                except Exception as exc:
                    failed_payload = {
                        "session_id": session["session_id"],
                        "chat_name": session["chat_name"],
                        "chat_type": session["chat_type"],
                        "status": "failed",
                        "error": str(exc),
                    }
                    (failed_root / f"{session_dirname}.json").write_text(
                        json.dumps(failed_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    results.append(failed_payload)
        finally:
            _close_if_possible(conn)

    summary = {
        "success": sum(1 for item in results if item["status"] == "success"),
        "failed": sum(1 for item in results if item["status"] == "failed"),
        "skipped": sum(1 for item in results if item["status"] == "skipped"),
        "total": len(results),
    }
    manifest = {"results": results, "summary": summary}
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_list_chats(documents_root=None):
    with tempfile.TemporaryDirectory() as temp_dir:
        key_log_path = Path(temp_dir) / "wechat-keys.log"
        conn = _prepare_connection(key_log_path, documents_root=documents_root)
        try:
            _status("正在读取会话列表...")
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
    try:
        if args.list_chats:
            run_list_chats(documents_root=args.documents_root)
            return 0

        if args.all_chats:
            if not args.output:
                parser.error("--output is required when --all-chats is used")
            run_export_all(output_dir=args.output, documents_root=args.documents_root)
            return 0

        if not args.chat or not args.output:
            parser.error("--chat and --output are required unless --list-chats or --all-chats is used")

        run_export(
            chat_name=args.chat,
            chat_type=args.chat_type,
            output_dir=args.output,
            documents_root=args.documents_root,
        )
        return 0
    except (RuntimeError, NotImplementedError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
