import os
import sys
import threading
import webbrowser
from pathlib import Path


def _writable_base_dir():
    """
    Choose a writable base folder on Windows:
      %LOCALAPPDATA%\OCRCaseTool\instance
    Fallback to ~\OCRCaseTool\instance if LOCALAPPDATA is missing.
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
    app.py picks them up:
      - APP_INSTANCE_DIR       (where app.py will place the sqlite file by default)
      - DATABASE_URL           (explicit SQLAlchemy URL to the sqlite file)
      - UPLOAD_FOLDER          (where uploads should be saved)
      - SECRET_KEY             (fallback secret)
    """
    app_root, inst, upld = _writable_base_dir()

    # Point SQLAlchemy to a writable sqlite file
    db_path = inst / "ocr_case_tool.sqlite"

    # Build a platform-safe sqlite URL (use forward slashes)
    db_url = "sqlite:///" + db_path.as_posix()

    # Export for app.py consumption
    os.environ["APP_INSTANCE_DIR"] = inst.as_posix()
    os.environ["DATABASE_URL"] = db_url
    os.environ["UPLOAD_FOLDER"] = upld.as_posix()
    os.environ.setdefault("SECRET_KEY", "win-bundled-default")


def _maybe_point_to_bundled_tesseract():
    """
    If the EXE contains a local tesseract folder, point pytesseract to it.
    Works with PyInstaller's _MEIPASS extraction dir.
    """
    try:
        import pytesseract  # noqa: WPS433 (import inside function is intentional)
        base = getattr(sys, "_MEIPASS", os.path.abspath("."))
        candidate = os.path.join(base, "tesseract", "tesseract.exe")
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
    except Exception:
        # Non-fatal if not present
        pass


def _open_browser():
    webbrowser.open("http://127.0.0.1:5000")


# ---- Configure env BEFORE importing the app ----
_set_runtime_env()

from waitress import serve  # noqa: E402
from app import app, db     # noqa: E402  (app now uses our env values)


def _ensure_db():
    """
    Create DB tables on first run.
    Using SQLAlchemy inspector to avoid errors if tables already exist.
    """
    from sqlalchemy import inspect  # noqa: WPS433
    with app.app_context():
        insp = inspect(db.engine)
        if not insp.get_table_names():
            db.create_all()


if __name__ == "__main__":
    _maybe_point_to_bundled_tesseract()
    _ensure_db()
    threading.Timer(1.0, _open_browser).start()
    # Bind only to localhost by default
    serve(app, host="127.0.0.1", port=5000)