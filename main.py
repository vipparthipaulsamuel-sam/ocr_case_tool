import os
import sys
import threading
import webbrowser
from pathlib import Path


def _writable_base_dir():
    """
    Ensure a writable base folder:
      %LOCALAPPDATA%\OCRCaseTool\instance\uploads
    Fallback to HOME if LOCALAPPDATA not set.
    """
    base_root = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    app_root = Path(base_root) / "OCRCaseTool"
    inst = app_root / "instance"
    upld = inst / "uploads"

    # Make sure both instance/ and uploads/ exist
    inst.mkdir(parents=True, exist_ok=True)
    upld.mkdir(parents=True, exist_ok=True)

    return app_root, inst, upld


def _set_runtime_env():
    app_root, inst, upld = _writable_base_dir()

    # Point SQLAlchemy to a writable sqlite file
    db_path = inst / "ocr_case_tool.sqlite"

    # If DB file does not exist, create an empty one so SQLite can open it
    if not db_path.exists():
        db_path.touch()

    db_url = "sqlite:///" + db_path.as_posix()

    os.environ["APP_INSTANCE_DIR"] = inst.as_posix()
    os.environ["DATABASE_URL"] = db_url
    os.environ["UPLOAD_FOLDER"] = upld.as_posix()
    os.environ.setdefault("SECRET_KEY", "win-bundled-default")


def _maybe_point_to_bundled_tesseract():
    """If the EXE contains a local tesseract folder, point pytesseract to it."""
    try:
        import pytesseract
        base = getattr(sys, "_MEIPASS", os.path.abspath("."))
        candidate = os.path.join(base, "tesseract", "tesseract.exe")
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
    except Exception:
        pass


def _open_browser():
    webbrowser.open("http://127.0.0.1:5000")


# ---- Configure env BEFORE importing the app ----
_set_runtime_env()

from waitress import serve
from app import app, db


def _ensure_db():
    """Create DB tables if missing."""
    from sqlalchemy import inspect
    with app.app_context():
        insp = inspect(db.engine)
        if not insp.get_table_names():
            db.create_all()


if __name__ == "__main__":
    _maybe_point_to_bundled_tesseract()
    _ensure_db()
    threading.Timer(1.0, _open_browser).start()
    serve(app, host="127.0.0.1", port=5000)