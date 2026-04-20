import subprocess
import sqlite3
from pathlib import Path
from typing import List


def ensure_supported_platform(platform_name: str) -> str:
    if platform_name == "darwin":
        return platform_name
    raise RuntimeError("WeChat export helpers currently support macOS only.")


def find_signed_wechat_app() -> Path:
    app_path = Path.home() / "Desktop" / "WeChat.app"
    if not app_path.is_dir():
        raise RuntimeError(f"Missing signed WeChat app at {app_path}")
    expected_executable = app_path / "Contents" / "MacOS" / "WeChat"
    if not expected_executable.is_file():
        raise RuntimeError(
            f"Invalid WeChat app bundle, expected executable at {expected_executable}"
        )
    try:
        result = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(app_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("codesign command not found on this system") from exc
    if result.returncode != 0:
        details = (result.stderr or "").strip() or "codesign verification failed"
        raise RuntimeError(f"WeChat app signature verification failed: {details}")
    return app_path


def find_chat_db_candidates(documents_root: Path) -> List[Path]:
    root = Path(documents_root)
    return sorted(
        path
        for path in root.glob("xwechat_files/*/db_storage/session/*.db")
        if path.is_file()
    )


def capture_runtime_key_log(app_path: Path, log_path: Path) -> Path:
    del app_path
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


def read_db_salt_hex(db_path: Path) -> str:
    path = Path(db_path)
    with path.open("rb") as handle:
        salt = handle.read(16)
    if len(salt) != 16:
        raise RuntimeError(f"Database file is too small to contain a salt header: {path}")
    return salt.hex()


def open_chat_db(db_path: Path, key_entry) -> sqlite3.Connection:
    del key_entry
    return sqlite3.connect(str(db_path))
