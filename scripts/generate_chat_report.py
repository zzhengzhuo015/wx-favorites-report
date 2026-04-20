import html
import json
from pathlib import Path


def generate_html(export_data):
    chat = export_data.get("chat", {})
    messages = export_data.get("messages", [])
    chat_name = chat.get("chat_name", "Unknown Chat")
    safe_chat_name = html.escape(chat_name)

    parts = []
    for message in messages:
        sender = html.escape(str(message.get("sender", "")))
        timestamp = html.escape(str(message.get("timestamp", "")))
        content = html.escape(str(message.get("text", "")))
        parts.append(
            "<li>"
            f"<div><strong>{sender}</strong> <span>{timestamp}</span></div>"
            f"<div>{content}</div>"
            "</li>"
        )

    timeline_html = "\n".join(parts) or "<li><div>No messages.</div></li>"
    messages_json = json.dumps(messages, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_chat_name} - Chat Report</title>
  <style>
    body {{ font-family: sans-serif; margin: 2rem; }}
    ul {{ list-style: none; padding: 0; }}
    li {{ border: 1px solid #ddd; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.75rem; }}
    h1 {{ margin-top: 0; }}
  </style>
</head>
<body>
  <h1>{safe_chat_name}</h1>
  <ul>
    {timeline_html}
  </ul>
  <script>
    const MESSAGES = {messages_json};
  </script>
</body>
</html>
"""


def write_report(export_data, output_path):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_html(export_data), encoding="utf-8")
