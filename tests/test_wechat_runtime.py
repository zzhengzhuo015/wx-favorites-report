from pathlib import Path

import pytest

from scripts.wechat_runtime import (
    ensure_supported_platform,
    find_chat_db_candidates,
    find_signed_wechat_app,
)


def test_ensure_supported_platform_accepts_darwin():
    assert ensure_supported_platform("darwin") == "darwin"


def test_ensure_supported_platform_rejects_linux_with_macos_error():
    with pytest.raises(RuntimeError, match="macOS"):
        ensure_supported_platform("linux")


def test_find_signed_wechat_app_prefers_desktop_app(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    desktop_app = home / "Desktop" / "WeChat.app"
    applications_app = home / "Applications" / "WeChat.app"
    desktop_app.mkdir(parents=True)
    applications_app.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    found = find_signed_wechat_app()

    assert found == desktop_app


def test_find_chat_db_candidates_returns_only_db_files(tmp_path: Path):
    documents_root = tmp_path / "Documents"
    db_a = documents_root / "wx" / "chat_a.db"
    db_b = documents_root / "wx" / "nested" / "chat_b.db"
    ignored_txt = documents_root / "wx" / "notes.txt"
    ignored_no_ext = documents_root / "wx" / "chat"
    db_a.parent.mkdir(parents=True)
    db_b.parent.mkdir(parents=True)
    db_a.write_text("", encoding="utf-8")
    db_b.write_text("", encoding="utf-8")
    ignored_txt.write_text("", encoding="utf-8")
    ignored_no_ext.write_text("", encoding="utf-8")

    candidates = find_chat_db_candidates(documents_root)

    assert candidates == [db_a, db_b]
