from pathlib import Path
from typing import List, Optional


def ensure_supported_platform(platform_name: str) -> str:
    if platform_name == "darwin":
        return platform_name
    raise RuntimeError("WeChat export helpers currently support macOS only.")


def find_signed_wechat_app() -> Optional[Path]:
    home = Path.home()
    candidates = [
        home / "Desktop" / "WeChat.app",
        home / "Applications" / "WeChat.app",
        Path("/Applications/WeChat.app"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def find_chat_db_candidates(documents_root: Path) -> List[Path]:
    root = Path(documents_root)
    return sorted(path for path in root.rglob("*.db") if path.is_file())
