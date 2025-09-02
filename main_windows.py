import os, sys, threading, webbrowser

def _writable_base_dir():
    # Prefer LOCALAPPDATA on Windows, else use HOME
    base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    base = os.path.join(base, "OCRCaseTool")
    inst = os.path.join(base, "instance")
    upld = os.path.join(inst, "uploads")
    os.makedirs(upld, exist_ok=True)
    return base, inst, upld

def _set_runtime_env():
    base, inst, upld = _writable_base_dir()
    # Point SQLAlchemy to a writable sqlite file
    db_path = os.path.join(inst, "ocr_case_tool.sqlite")
    # Use forward slashes for SQLAlchemy URL
    db_url = "sqlite:///" + db_path.replace("\\", "/")
    os.environ["DATABASE_URL"]  = db_url
    os.environ["UPLOAD_FOLDER"] = upld
    # Provide a default secret key if none
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
from app import app, db   # app now uses DATABASE_URL / UPLOAD_FOLDER we set above

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
