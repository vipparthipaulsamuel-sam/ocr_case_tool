import os
import sys
import threading
import webbrowser
from pathlib import Path


def _writable_base_dir():
    """
    Choose a writable base folder on Windows:
      %LOCALAPPDATA%\\OCRCaseTool\\instance
    Fallback to ~\\OCRCaseTool\\instance if LOCALAPPDATA is missing.
    Also ensure an 'uploads' subfolder exists.
    """
    base_root = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    app_root = Path(base_root) / "OCRCaseTool"
    inst = app_root / "instance"
    upld = inst / "uploads"
    upld.mkdir(parents=True, exist_ok=True)
    return app_root, inst, upld


def _set_runtime_env():
    """
    Set environment variables BEFORE importing the Flask app so that
    app.py picks them up.
    """
    app_root, inst, upld = _writable_base_dir()

    # Point SQLAlchemy to a writable sqlite file
    db_path = inst / "ocr_case_tool.sqlite"

    # Platform-safe sqlite URL (use forward slashes)
    db_url = "sqlite:///" + db_path.as_posix()

    # Export for app.py consumption
    os.environ["APP_INSTANCE_DIR"] = inst.as_posix()
    os.environ["DATABASE_URL"] = db_url
    os.environ["UPLOAD_FOLDER"] = upld.as_posix()
    os.environ.setdefault("SECRET_KEY", "win-bundled-default")

    # Defaults for admin bootstrap (override via system env if desired)
    os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "test123")
    os.environ.setdefault("BOOTSTRAP_ADMIN_NAME", "Admin")

    # Ensure sqlite file exists (avoids "unable to open database file" on first connect)
    if not db_path.exists():
        inst.mkdir(parents=True, exist_ok=True)
        db_path.touch()


def _maybe_point_to_tesseract():
    """
    Try to point pytesseract to a usable binary:
    1. Bundled copy (inside PyInstaller _MEIPASS)
    2. System-wide install (Program Files / Program Files (x86))
    """
    try:
        import pytesseract
        base = getattr(sys, "_MEIPASS", os.path.abspath("."))
        bundled = os.path.join(base, "tesseract", "tesseract.exe")
        candidates = [
            bundled,
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                pytesseract.pytesseract.tesseract_cmd = c
                print(f"[INFO] Using Tesseract at {c}")
                return
        print("[WARN] Tesseract not found. OCR will not work until installed.")
    except Exception as e:
        print(f"[WARN] Could not configure Tesseract: {e}")


def _open_browser():
    webbrowser.open("http://127.0.0.1:5000")


# ---- Configure env BEFORE importing the app ----
_set_runtime_env()

from waitress import serve  # noqa: E402
from app import app, db, bootstrap_admin_if_needed  # noqa: E402  (app now uses our env values)


def _ensure_db():
    """
    Create DB tables on first run, then ensure an admin exists.
    """
    from sqlalchemy import inspect  # import inside to avoid PyInstaller surprises
    with app.app_context():
        insp = inspect(db.engine)
        if not insp.get_table_names():
            db.create_all()
        # Make sure an admin account exists
        bootstrap_admin_if_needed()


if __name__ == "__main__":
    _maybe_point_to_tesseract()
    _ensure_db()
    threading.Timer(1.0, _open_browser).start()
    # Bind only to localhost by default
    serve(app, host="127.0.0.1", port=5000)