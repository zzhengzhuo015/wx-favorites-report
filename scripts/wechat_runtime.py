import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import List

from scripts.wechat_decrypt import decrypt_sqlcipher_db, match_key_by_salt
PERMISSION_HINT = (
    "Grant Full Disk Access to Codex or the terminal you are using so it can "
    "read the WeChat container directory."
)

FRIDA_CAPTURE_SCRIPT = textwrap.dedent(
    """
    import sys
    import time
    from pathlib import Path

    try:
        import frida
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "frida Python package is not installed. Run: pip3 install frida frida-tools"
        ) from exc

    log_path = Path(sys.argv[1]).expanduser().resolve()
    app_path = Path(sys.argv[2]).expanduser().resolve()
    wait_seconds = int(sys.argv[3])
    ready_path_arg = sys.argv[4]
    executable = app_path / "Contents" / "MacOS" / "WeChat"
    ready_path = None if ready_path_arg == "-" else Path(ready_path_arg).expanduser().resolve()

    if not executable.is_file():
        raise SystemExit(f"WeChat executable not found at {executable}")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    JS_CODE = '''
    function buf2hex(buffer) {
        var a = new Uint8Array(buffer); var h = '';
        for (var i = 0; i < a.length; i++) h += ('0' + a[i].toString(16)).slice(-2);
        return h;
    }
    var found = false;
    Process.enumerateModules().forEach(function(m) {
        if (found) return;
        m.enumerateExports().forEach(function(exp) {
            if (found) return;
            if (exp.name === "CCKeyDerivationPBKDF") {
                found = true;
                send({type: "status", message: "[*] Hook installed on " + m.name});
                Interceptor.attach(exp.address, {
                    onEnter: function(args) {
                        this.pwLen = args[2].toInt32();
                        this.saltLen = args[4].toInt32();
                        this.rounds = args[6].toInt32();
                        this.pw = args[1];
                        this.salt = args[3];
                        this.dk = args[7];
                        this.dkLen = args[8].toInt32();
                    },
                    onLeave: function(retval) {
                        if (this.pwLen < 4 || this.pwLen > 256) return;
                        if (this.saltLen < 4 || this.saltLen > 64) return;
                        var saltHex = buf2hex(this.salt.readByteArray(this.saltLen));
                        var dkHex = buf2hex(this.dk.readByteArray(this.dkLen));
                        var pwHex = buf2hex(this.pw.readByteArray(this.pwLen));
                        send({
                            type: "pbkdf2",
                            rounds: this.rounds,
                            pw: pwHex,
                            salt: saltHex,
                            dk: dkHex
                        });
                    }
                });
            }
        });
    });
    if (!found) send({type: "error", message: "CCKeyDerivationPBKDF not found"});
    '''

    def on_message(message, data):
        payload = message.get("payload")
        if isinstance(payload, dict):
            kind = payload.get("type")
            if kind == "pbkdf2":
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"rounds={payload['rounds']}\\n"
                        f"pw={payload['pw']}\\n"
                        f"salt={payload['salt']}\\n"
                        f"dk={payload['dk']}\\n\\n"
                    )
            elif kind in {"status", "error"}:
                print(payload.get("message", ""))
        else:
            print(payload if payload is not None else message)

    device = frida.get_local_device()
    pid = device.spawn([str(executable)])
    session = device.attach(pid)
    script = session.create_script(JS_CODE)
    script.on("message", on_message)
    script.load()
    device.resume(pid)
    print("WeChat running. Login -> open target chat -> wait for key capture...")
    deadline = time.time() + wait_seconds
    if ready_path is None:
        time.sleep(wait_seconds)
    else:
        while time.time() < deadline:
            if ready_path.exists():
                time.sleep(1)
                break
            time.sleep(0.25)
    session.detach()
    print(f"Done. Key log saved to {log_path}")
    """
)


class DecryptedChatConnection:
    def __init__(
        self,
        conn: sqlite3.Connection,
        tempdir: tempfile.TemporaryDirectory,
        self_username: str,
        self_display_name: str,
    ):
        self._conn = conn
        self._tempdir = tempdir
        self.self_username = self_username
        self.self_display_name = self_display_name

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def close(self):
        self._conn.close()
        self._tempdir.cleanup()


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
    try:
        next(root.iterdir(), None)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"WeChat documents root does not exist: {root}"
        ) from exc
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot access WeChat documents at {root}: {exc}. {PERMISSION_HINT}"
        ) from exc
    return sorted(
        path
        for path in root.glob("xwechat_files/*/db_storage/session/*.db")
        if path.is_file()
    )


def capture_runtime_key_log(
    app_path: Path, log_path: Path, wait_seconds: int = 120, prompt_fn=None
) -> Path:
    app_path = Path(app_path)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ready_signal = log_path.with_suffix(log_path.suffix + ".ready")
    if ready_signal.exists():
        ready_signal.unlink()
    cmd = [
        sys.executable,
        "-c",
        FRIDA_CAPTURE_SCRIPT,
        str(log_path),
        str(app_path),
        str(wait_seconds),
        str(ready_signal if prompt_fn is not None else "-"),
    ]
    if prompt_fn is None:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            prompt_fn()
            ready_signal.write_text("ready\n", encoding="utf-8")
            stdout, stderr = process.communicate()
        finally:
            if ready_signal.exists():
                ready_signal.unlink()
        class Result:
            def __init__(self, returncode, stdout, stderr):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr
        result = Result(process.returncode, stdout, stderr)
    if result.returncode != 0:
        details = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise RuntimeError(f"Frida key capture failed: {details or 'unknown error'}")
    if not log_path.exists():
        raise RuntimeError(
            f"Frida key capture did not produce a key log at {log_path}"
        )
    if not log_path.read_text(encoding="utf-8").strip():
        raise RuntimeError(
            "Frida key capture produced an empty key log. "
            "Make sure WeChat is logged in and the target chat is open during capture."
        )
    return log_path


def read_db_salt_hex(db_path: Path) -> str:
    path = Path(db_path)
    with path.open("rb") as handle:
        salt = handle.read(16)
    if len(salt) != 16:
        raise RuntimeError(f"Database file is too small to contain a salt header: {path}")
    return salt.hex()


def _decrypt_related_db(source_path: Path, key_entries, output_path: Path) -> Path:
    salt_hex = read_db_salt_hex(source_path)
    entry = match_key_by_salt(key_entries, salt_hex)
    return decrypt_sqlcipher_db(source_path, str(entry["dk"]), output_path)


def open_chat_db(db_path: Path, key_entry):
    key_entries = key_entry if isinstance(key_entry, list) else [key_entry]
    source_db_path = Path(db_path)
    db_storage_root = source_db_path.parent.parent
    self_username = source_db_path.parents[2].name
    tempdir = tempfile.TemporaryDirectory(prefix="wechat-chat-db-")
    temp_root = Path(tempdir.name)

    decrypted_session = _decrypt_related_db(
        source_db_path, key_entries, temp_root / "session.db"
    )
    decrypted_contact = _decrypt_related_db(
        db_storage_root / "contact" / "contact.db", key_entries, temp_root / "contact.db"
    )
    message_sources = sorted((db_storage_root / "message").glob("message_[0-9]*.db"))
    if not message_sources:
        raise RuntimeError(f"No message databases found under {db_storage_root / 'message'}")

    conn = sqlite3.connect(decrypted_session)
    try:
        conn.execute(f"ATTACH DATABASE '{decrypted_contact}' AS contact_db")
        for index, message_source in enumerate(message_sources):
            decrypted_message = _decrypt_related_db(
                message_source, key_entries, temp_root / f"message_{index}.db"
            )
            conn.execute(
                f"ATTACH DATABASE '{decrypted_message}' AS message_db_{index}"
            )
        row = conn.execute(
            """
            SELECT COALESCE(NULLIF(remark, ''), NULLIF(nick_name, ''), username)
            FROM contact_db.contact
            WHERE username = ?
            LIMIT 1
            """,
            (self_username,),
        ).fetchone()
        self_display_name = row[0] if row and row[0] else "我"
        return DecryptedChatConnection(conn, tempdir, self_username, self_display_name)
    except Exception:
        conn.close()
        tempdir.cleanup()
        raise
