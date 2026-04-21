import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.parse_chat import list_chat_sessions, normalize_messages, resolve_chat_session
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


def _safe_chat_filename_stem(chat_name: str) -> str:
    stem = str(chat_name or "").strip()
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    return stem or "chat"


def _artifact_paths(output_dir: Path, export_data: dict) -> dict:
    chat = export_data.get("chat", {})
    stem = _safe_chat_filename_stem(chat.get("chat_name", ""))
    return {
        "json": output_dir / f"{stem}.json",
    }


def _unique_json_output_path(
    output_dir: Path,
    export_data: dict,
    used_names=None,
) -> Path:
    used_names = used_names if used_names is not None else set()
    base_path = _artifact_paths(output_dir, export_data)["json"]
    stem = base_path.stem
    suffix = base_path.suffix
    candidate = base_path
    counter = 2
    while candidate.name in used_names or candidate.exists():
        candidate = output_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    used_names.add(candidate.name)
    return candidate


def _message_export_type(message: dict) -> int:
    msg_type = str(message.get("msg_type", "") or "")
    if msg_type.startswith("type_"):
        suffix = msg_type.split("_", 1)[1]
        if suffix.isdigit():
            return int(suffix)

    mapping = {
        "text": 0,
        "image": 1,
        "video": 3,
        "file": 4,
        "sticker": 5,
        "app": 7,
        "location": 8,
        "reply": 25,
        "card": 27,
        "system": 80,
        "voice": 34,
        "revoke": 10000,
    }
    return mapping.get(msg_type, 0)


def _message_export_content(message: dict) -> str:
    text = str(message.get("text", "") or "")
    if text:
        return text

    msg_type = str(message.get("msg_type", "") or "")
    quote_text = str(message.get("quote_text", "") or "")
    file_name = str(message.get("file_name", "") or "")
    placeholders = {
        "image": "[图片]",
        "video": "[视频]",
        "voice": "[语音]",
        "location": "[位置]",
        "sticker": "[动画表情]",
        "card": "[名片]",
    }

    if msg_type == "reply" and quote_text:
        return quote_text
    if msg_type == "file" and file_name:
        return f"[文件] {file_name}"
    if msg_type in placeholders:
        return placeholders[msg_type]
    if file_name:
        return file_name
    return ""


def _message_export_timestamp(message: dict):
    value = message.get("timestamp")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _build_chat_record_export(
    export_data: dict,
    *,
    exported_at: Optional[int] = None,
    generator: str = "wx-favorites-report",
) -> dict:
    chat = export_data.get("chat", {})
    messages = export_data.get("messages", [])

    owner_id = str(chat.get("owner_id", "") or "").strip()
    if not owner_id:
        for message in messages:
            if message.get("is_outgoing"):
                owner_id = str(
                    message.get("sender_id")
                    or message.get("sender")
                    or ""
                ).strip()
                if owner_id:
                    break
    if not owner_id:
        owner_id = "self"

    meta = {
        "name": str(chat.get("chat_name", "") or "Unknown Chat"),
        "platform": "wechat",
        "type": str(chat.get("chat_type", "") or "contact"),
        "ownerId": owner_id,
    }
    if meta["type"] == "group":
        meta["groupId"] = str(chat.get("session_id", "") or "")

    members = []
    seen_members = set()
    exported_messages = []
    for message in messages:
        sender_id = str(
            message.get("sender_id")
            or message.get("sender")
            or "unknown"
        )
        account_name = str(message.get("sender") or sender_id)
        msg_type = str(message.get("msg_type", "") or "")
        if msg_type != "system" and sender_id not in seen_members:
            seen_members.add(sender_id)
            members.append(
                {
                    "platformId": sender_id,
                    "accountName": account_name,
                }
            )

        exported_message = {
            "sender": sender_id,
            "accountName": account_name,
            "timestamp": _message_export_timestamp(message),
            "type": _message_export_type(message),
            "content": _message_export_content(message),
            "platformMessageId": str(message.get("id", "") or ""),
        }
        exported_messages.append(exported_message)

    return {
        "chatlab": {
            "version": "0.0.2",
            "exportedAt": int(exported_at if exported_at is not None else time.time()),
            "generator": generator,
        },
        "meta": meta,
        "members": members,
        "messages": exported_messages,
    }


def _write_export_artifacts(output_dir: Path, export_data: dict, output_path: Optional[Path] = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_output_path = output_path or _artifact_paths(output_dir, export_data)["json"]
    json_output_path.write_text(
        json.dumps(_build_chat_record_export(export_data), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _session_export_metadata(conn, session: dict) -> dict:
    resolved = dict(session)
    owner_id = str(getattr(conn, "self_username", "") or "").strip()
    if owner_id and not resolved.get("owner_id"):
        resolved["owner_id"] = owner_id
    return resolved


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
            session = _session_export_metadata(
                conn,
                resolve_chat_session(conn, chat_name=chat_name, chat_type=chat_type),
            )
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

    with tempfile.TemporaryDirectory() as temp_dir:
        key_log_path = Path(temp_dir) / "wechat-keys.log"
        conn = _prepare_connection(key_log_path, documents_root=documents_root)
        try:
            _status("正在读取会话列表...")
            sessions = list_chat_sessions(conn)
            used_names = set()
            for session in sessions:
                _status(f"正在导出会话：{session.get('chat_name', session.get('session_id', ''))}")
                try:
                    resolved_session = _session_export_metadata(
                        conn,
                        resolve_chat_session(
                            conn,
                            chat_name=session["chat_name"],
                            chat_type=session["chat_type"],
                        ),
                    )
                    messages = normalize_messages(conn, resolved_session)
                    export_data = {"chat": resolved_session, "messages": messages}
                    output_path = _unique_json_output_path(output, export_data, used_names=used_names)
                    _write_export_artifacts(output, export_data, output_path=output_path)
                except Exception as exc:
                    _status(
                        "导出失败："
                        f"{session.get('chat_name', session.get('session_id', ''))}: {exc}"
                    )
        finally:
            _close_if_possible(conn)


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
