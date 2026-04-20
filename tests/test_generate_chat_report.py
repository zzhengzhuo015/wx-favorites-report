from pathlib import Path

from scripts.generate_chat_report import generate_html, write_report


def sample_export_data():
    return {
        "chat": {
            "session_id": "s-2",
            "chat_name": "Project Group",
            "chat_type": "group",
        },
        "messages": [
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
        ],
    }


def test_generate_html_embeds_chat_name_message_and_messages_payload():
    html = generate_html(sample_export_data())

    assert "Project Group" in html
    assert "Daily standup at 10" in html
    assert "const MESSAGES =" in html


def test_write_report_creates_file_with_chat_name(tmp_path: Path):
    output_path = tmp_path / "chat-report.html"

    write_report(sample_export_data(), output_path)

    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "Project Group" in html
