from pathlib import Path
from typing import List


def ensure_supported_platform(platform_name: str) -> str:
    if platform_name == "darwin":
        return platform_name
    raise RuntimeError("WeChat export helpers currently support macOS only.")


def find_signed_wechat_app() -> Path:
    app_path = Path.home() / "Desktop" / "WeChat.app"
    if app_path.exists():
        return app_path
    raise RuntimeError(f"Missing signed WeChat app at {app_path}")


def find_chat_db_candidates(documents_root: Path) -> List[Path]:
    root = Path(documents_root)
    return sorted(
        path
        for path in root.glob("xwechat_files/*/db_storage/session/*.db")
        if path.is_file()
    )
