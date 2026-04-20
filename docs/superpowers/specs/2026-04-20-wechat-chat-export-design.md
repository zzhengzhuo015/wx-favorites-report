# WeChat Chat Export Design

## Summary

This document specifies a first usable version of chat export built from the same runtime-assisted approach already used for WeChat favorites export in this repository.

The new feature will export a single WeChat 4.x chat session on macOS by guiding the user to open the target conversation, capturing the database key material at runtime, parsing the session's messages, and producing `JSON`, `CSV`, and `HTML` outputs.

## Goals

- Support `macOS + WeChat 4.x` only for the first version
- Export a single contact chat or group chat per run
- Reuse the current repository's Python CLI style and reporting patterns where practical
- Produce three outputs from one run:
  - `messages.json`
  - `messages.csv`
  - `report.html`
- Cover common message categories in the first version:
  - text
  - quote/reply
  - system messages
  - revoke notices
  - image
  - voice
  - video
  - file
- Export media metadata and local identifiers/paths when available, without promising media decryption
- Provide actionable failures when the environment, runtime hook, database access, or session matching fails

## Non-Goals

- Full-account one-click export of all chats
- Windows or Linux support
- Restoring or decrypting all media payloads
- Full fidelity support for every internal WeChat message subtype in the first version
- Replacing the existing favorites export flow

## User Experience

### Primary command

```bash
python3 scripts/export_chat.py \
  --chat "Target Contact Or Group" \
  --output ~/Downloads/wechat-chat-export
```

### Optional helper commands

```bash
python3 scripts/export_chat.py --list-chats
python3 scripts/export_chat.py --chat "Project Group" --chat-type group --output ~/Downloads/wechat-chat-export
```

### Expected runtime flow

1. Validate environment and dependencies.
2. Detect the WeChat runtime/data location for macOS WeChat 4.x.
3. If required, prepare or verify the ad-hoc-signed WeChat copy used for runtime hooking.
4. Start the hook flow and prompt the user to open the target conversation inside WeChat.
5. Capture and match the database key material for the loaded chat database.
6. Open the decrypted or decryptable SQLite database.
7. Resolve the target chat session from user input.
8. Parse messages and normalize them into a stable export schema.
9. Write `messages.json`, `messages.csv`, and `report.html`.

## Scope Constraints

The first version explicitly accepts a semi-automated workflow. The user must:

- already be logged in to WeChat
- run the export command locally on macOS
- open the target chat window during the guided export flow when prompted

This constraint keeps the feature aligned with the proven favorites-export approach and reduces the initial implementation risk around lazy database loading and key availability.

## Architecture

The implementation will be split into focused Python modules so we can validate and evolve each responsibility independently.

### 1. `scripts/export_chat.py`

Top-level CLI entrypoint responsible for orchestration.

Responsibilities:

- parse CLI arguments
- validate required dependencies and environment assumptions
- run the guided export flow
- coordinate runtime capture, database access, parsing, and output generation
- print actionable progress and error messages

### 2. `scripts/wechat_runtime.py`

Runtime and environment integration helpers.

Responsibilities:

- locate macOS WeChat data directories and likely chat database files
- locate or prepare the signed WeChat app copy required for injection
- manage the runtime hook lifecycle
- prompt the user to open the target chat
- collect hook output in a machine-readable form

### 3. `scripts/wechat_decrypt.py`

Database access and key matching logic.

Responsibilities:

- read candidate database salt/header information
- parse captured hook output
- match a runtime-derived key to the target chat database
- expose a unified way to obtain a readable SQLite connection or decrypted temporary database

The exact database-opening technique can reuse the favorites path where compatible, but this module must stay chat-oriented and not couple chat export to favorites-specific naming or assumptions.

### 4. `scripts/parse_chat.py`

Chat-session discovery and message normalization.

Responsibilities:

- list candidate chat sessions for `--list-chats`
- resolve a target session from chat name and optional chat type
- query message tables and related identity/session tables
- normalize raw rows into a stable export structure
- handle unsupported message types without crashing the export

### 5. `scripts/generate_chat_report.py`

HTML report generation.

Responsibilities:

- read normalized message export data
- generate a browseable single-file HTML report
- present the chat as a timeline/message stream rather than a favorites dashboard
- support filtering by sender, type, and time range when feasible without over-complicating the first version

## Data Flow

```text
export_chat.py
  -> validate environment
  -> locate runtime + database candidates
  -> capture runtime key material
  -> match key to target database
  -> obtain readable SQLite access
  -> resolve target session
  -> parse and normalize messages
  -> write JSON
  -> write CSV
  -> generate HTML report
```

## Export Schema

The normalized message model should remain stable even if internal WeChat structures vary. The first version will export a schema shaped like:

```json
{
  "id": "msg-123",
  "session_id": "session-1",
  "chat_name": "Project Group",
  "chat_type": "group",
  "sender": "Alice",
  "is_outgoing": false,
  "timestamp": "2026-04-20T11:23:00",
  "msg_type": "text",
  "text": "hello",
  "quote_text": "",
  "file_name": "",
  "file_path": "",
  "raw": {}
}
```

Notes:

- `raw` preserves important original fields for debugging and future parser expansion.
- Media messages should populate file-related metadata when available.
- Unsupported or partially supported types should still emit a row with best-effort metadata and a clear `msg_type`.

## Session Resolution

The first version must support these selection patterns:

- exact or fuzzy chat name match through `--chat`
- optional narrowing with `--chat-type contact|group`
- listing discoverable sessions with `--list-chats`

If multiple sessions match, the CLI must fail clearly and tell the user how to disambiguate.

## Error Handling

Failures should be grouped by layer and always include a practical next step.

### Environment failures

Examples:

- unsupported OS
- missing `frida` or `pycryptodome`
- missing WeChat data directory

Response style:

- state what is missing
- print the exact dependency or path expected
- explain the next action to try

### Runtime capture failures

Examples:

- hook did not attach
- user did not open the target conversation
- no key material matched the candidate chat database

Response style:

- explain that the relevant database or key was not observed
- tell the user to confirm login state and reopen the target chat during the capture window

### Data/parse failures

Examples:

- no matching chat session found
- multiple sessions matched
- unexpected schema in the chat tables
- unsupported message subtype

Response style:

- fail hard for target-session lookup problems
- degrade gracefully for unsupported individual message types

### Output failures

Examples:

- output directory not writable
- CSV or HTML write failure

Response style:

- identify which output path failed
- stop before claiming success

## Testing Strategy

The implementation should use layered verification.

### Unit tests

Focus areas:

- session matching logic
- message-type normalization
- CSV row generation
- HTML report data shaping

These tests should not require a live WeChat process.

### Fixture-based parser tests

Use sanitized or synthetic chat fixtures to verify:

- target-session selection
- parsing of common message types
- export schema stability

If real database fixtures are not safe to store, build minimal SQLite fixtures that mimic the relevant schema.

### Manual acceptance tests

Run in a real `macOS + WeChat 4.x` environment and verify:

- one contact chat export
- one group chat export
- successful creation of `messages.json`, `messages.csv`, and `report.html`

## Risks And Mitigations

### Risk: chat database layout differs from favorites assumptions

Mitigation:

- keep chat parsing and chat database access in separate modules
- discover actual schema before hard-coding parser assumptions

### Risk: chat database key loading timing differs by session state

Mitigation:

- keep the first version interactive
- explicitly prompt the user to open the target chat during capture

### Risk: same-name chat ambiguity

Mitigation:

- support `--chat-type`
- provide `--list-chats`
- fail with a clear disambiguation message

### Risk: unsupported message types block export

Mitigation:

- degrade to best-effort rows for individual messages
- preserve original fields in `raw`

## Implementation Order

1. Identify real chat database locations and queryable schema in the local macOS WeChat 4.x environment.
2. Build test fixtures and parser expectations around the discovered schema.
3. Add the new chat parsing and session-resolution modules.
4. Add JSON/CSV export.
5. Add HTML report generation.
6. Add the top-level guided CLI that connects runtime capture, database access, and exports.

## Open Assumptions

These assumptions are intentionally explicit so implementation can validate them early:

- WeChat 4.x chat databases are accessible through a runtime-assisted key capture flow similar enough to the existing favorites approach to be reused conceptually.
- The user can manually open the target conversation during export.
- A first version that exports media metadata rather than decrypted media is acceptable.

If any of these assumptions fail during implementation, the work should stop long enough to revise the plan rather than silently widening scope.
