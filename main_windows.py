import os, sys, threading, webbrowser
from waitress import serve
from app import app, db, INSTANCE_DIR

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

def _ensure_db():
    """Create instance/ & DB tables if missing."""
    INSTANCE_DIR.mkdir(exist_ok=True)
    from sqlalchemy import inspect
    with app.app_context():
        insp = inspect(db.engine)
        if not insp.get_table_names():
            db.create_all()

def _open_browser():
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    _maybe_point_to_bundled_tesseract()
    _ensure_db()
    threading.Timer(1.0, _open_browser).start()
    serve(app, host="127.0.0.1", port=5000)
