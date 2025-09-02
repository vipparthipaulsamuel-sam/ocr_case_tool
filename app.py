import os
import uuid
import argparse
from datetime import datetime
from pathlib import Path

from payments import payments_bp
from payments.models import payments_table

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# OCR deps
import pytesseract
from PIL import Image

load_dotenv()

# --- Config helpers ---
BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = INSTANCE_DIR / "uploads"
ALLOWED_EXTS = {".jpg", ".jpeg", ".png"}  # extend if needed

def normalize_sqlite_uri(uri: str) -> str:
    """If uri is a SQLite URL with a relative filesystem path (e.g. sqlite:///instance/ocr_case_tool.sqlite),
    convert it to absolute based on BASE_DIR. Otherwise return as-is."""
    if not uri.startswith("sqlite:///"):
        return uri
    path_part = uri[len("sqlite:///"):]
    p = Path(path_part)
    if p.is_absolute():
        return f"sqlite:////{p.as_posix()}"
    abs_path = (BASE_DIR / p).resolve()
    return f"sqlite:////{abs_path.as_posix()}"

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')

    # Default DB is absolute under instance/
    default_db_uri = f"sqlite:////{(INSTANCE_DIR / 'ocr_case_tool.sqlite').as_posix()}"
    db_uri = os.getenv('DATABASE_URL', default_db_uri)
    db_uri = normalize_sqlite_uri(db_uri)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    upload_folder = os.getenv('UPLOAD_FOLDER', str(UPLOAD_DIR))
    uf_path = Path(upload_folder)
    if not uf_path.is_absolute():
        uf_path = (BASE_DIR / uf_path).resolve()
    app.config['UPLOAD_FOLDER'] = str(uf_path)

    # Ensure folders exist
    INSTANCE_DIR.mkdir(exist_ok=True)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)

    # Optional tesseract path
    tcmd = os.getenv('TESSERACT_CMD')
    if tcmd:
        pytesseract.pytesseract.tesseract_cmd = tcmd

    return app

app = create_app()
db = SQLAlchemy(app)

# Build Payment model bound to this db (single source of truth)
Payment = payments_table(db)

# Register Payments OCR blueprint
app.register_blueprint(payments_bp, url_prefix="/payments")

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default="user")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cases = db.relationship("Case", backref="owner", lazy=True)
    uploads = db.relationship("Upload", backref="uploader", lazy=True)
    notes = db.relationship("Note", backref="author", lazy=True)

class Case(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploads = db.relationship("Upload", backref="case", lazy=True, cascade="all, delete-orphan")
    notes = db.relationship("Note", backref="case", lazy=True, cascade="all, delete-orphan")

class Upload(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    mimetype = db.Column(db.String(100))
    size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    ocr_text = db.relationship("OcrText", backref="upload", uselist=False, cascade="all, delete-orphan")

class OcrText(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey('upload.id'), nullable=False, unique=True)
    engine = db.Column(db.String(50), default="tesseract")
    lang = db.Column(db.String(20), default="eng")
    text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    meta_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Helpers ---
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return User.query.get(uid)

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please login first.", "warning")
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u or u.role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

def allowed_file(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTS

def log_action(user_id, action, entity_type=None, entity_id=None, meta=None):
    entry = ActivityLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        meta_json=(meta if isinstance(meta, str) else (None if meta is None else str(meta)))
    )
    db.session.add(entry)
    db.session.commit()

def run_ocr(image_path, lang="eng"):
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip()
    except Exception as e:
        return f"[OCR ERROR] {e}"

# --- Routes ---
@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")

        if not name or not email or not pw:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "warning")
            return redirect(url_for("register"))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(pw, method="pbkdf2:sha256"),
            role="user"
        )
        db.session.add(user)
        db.session.commit()
        log_action(user.id, "register")

        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, pw):
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

        session['user_id'] = user.id
        log_action(user.id, "login")
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    u = current_user()
    session.clear()
    if u:
        log_action(u.id, "logout")
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    if u.role == "admin":
        cases = Case.query.order_by(Case.created_at.desc()).all()
    else:
        cases = Case.query.filter_by(user_id=u.id).order_by(Case.created_at.desc()).all()
    return render_template("dashboard.html", cases=cases, user=u)

@app.route("/case/create", methods=["POST"])
@login_required
def create_case():
    u = current_user()
    name = request.form.get("name", "").strip()
    desc = request.form.get("description", "").strip()
    if not name:
        flash("Case name is required.", "danger")
        return redirect(url_for("dashboard"))
    c = Case(user_id=u.id, name=name, description=desc)
    db.session.add(c)
    db.session.commit()
    log_action(u.id, "case_create", "case", c.id, meta=f"name={name}")
    flash("Case created.", "success")
    return redirect(url_for("case_detail", case_id=c.id))

def can_access_case(u, c: Case):
    if not u:
        return False
    if u.role == "admin":
        return True
    return c.user_id == u.id

@app.route("/case/<int:case_id>")
@login_required
def case_detail(case_id):
    u = current_user()
    c = Case.query.get_or_404(case_id)
    if not can_access_case(u, c):
        abort(403)
    uploads = Upload.query.filter_by(case_id=case_id).order_by(Upload.uploaded_at.desc()).all()
    notes = Note.query.filter_by(case_id=case_id).order_by(Note.created_at.desc()).all()
    payments = Payment.query.filter_by(case_id=case_id).order_by(Payment.created_at.desc()).all()
    return render_template("case_detail.html", case=c, uploads=uploads, notes=notes, payments=payments, user=u)

@app.route("/case/<int:case_id>/note", methods=["POST"])
@login_required
def add_note(case_id):
    u = current_user()
    c = Case.query.get_or_404(case_id)
    if not can_access_case(u, c):
        abort(403)
    content = request.form.get("content", "").strip()
    if not content:
        flash("Note cannot be empty.", "warning")
        return redirect(url_for("case_detail", case_id=case_id))
    n = Note(case_id=case_id, user_id=u.id, content=content)
    db.session.add(n)
    db.session.commit()
    log_action(u.id, "note_add", "case", case_id, meta=f"note_id={n.id}")
    flash("Note added.", "success")
    return redirect(url_for("case_detail", case_id=case_id))

@app.route("/case/<int:case_id>/upload", methods=["POST"])
@login_required
def upload_file(case_id):
    u = current_user()
    c = Case.query.get_or_404(case_id)
    if not can_access_case(u, c):
        abort(403)

    if "file" not in request.files:
        flash("No file part.", "danger")
        return redirect(url_for("case_detail", case_id=case_id))

    f = request.files["file"]
    if f.filename == "":
        flash("No selected file.", "warning")
        return redirect(url_for("case_detail", case_id=case_id))

    if not allowed_file(f.filename):
        flash("Unsupported file type. Use JPG/PNG.", "danger")
        return redirect(url_for("case_detail", case_id=case_id))

    orig_name = secure_filename(f.filename)
    ext = Path(orig_name).suffix.lower()
    new_name = f"{uuid.uuid4().hex}{ext}"
    save_path = Path(app.config['UPLOAD_FOLDER']) / new_name
    save_path.parent.mkdir(parents=True, exist_ok=True)
    f.save(save_path)

    up = Upload(
        case_id=case_id,
        user_id=u.id,
        stored_filename=new_name,
        original_filename=orig_name,
        mimetype=f.mimetype,
        size=save_path.stat().st_size
    )
    db.session.add(up)
    db.session.commit()
    log_action(u.id, "upload", "upload", up.id, meta=f"case_id={case_id}, file={orig_name}")

    # Run OCR immediately
    text = run_ocr(save_path)
    rec = OcrText(upload_id=up.id, text=text)
    db.session.add(rec)
    db.session.commit()
    log_action(u.id, "ocr_extract", "upload", up.id)

    flash("File uploaded and OCR completed.", "success")
    return redirect(url_for("case_detail", case_id=case_id))

@app.route("/upload/<int:upload_id>/image")
@login_required
def serve_upload(upload_id):
    u = current_user()
    up = Upload.query.get_or_404(upload_id)
    c = Case.query.get_or_404(up.case_id)
    if not can_access_case(u, c):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], up.stored_filename)

@app.route("/upload/<int:upload_id>/rerun-ocr", methods=["POST"])
@login_required
def rerun_ocr(upload_id):
    u = current_user()
    up = Upload.query.get_or_404(upload_id)
    c = Case.query.get_or_404(up.case_id)
    if not can_access_case(u, c):
        abort(403)
    image_path = Path(app.config['UPLOAD_FOLDER']) / up.stored_filename
    text = run_ocr(image_path)
    if up.ocr_text:
        up.ocr_text.text = text
    else:
        up.ocr_text = OcrText(upload_id=up.id, text=text)
    db.session.commit()
    log_action(u.id, "ocr_rerun", "upload", up.id)
    flash("OCR re-run completed.", "success")
    return redirect(url_for("case_detail", case_id=up.case_id))

# --- Admin Views ---
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    cases = Case.query.order_by(Case.created_at.desc()).all()
    uploads = Upload.query.order_by(Upload.uploaded_at.desc()).all()
    return render_template("admin.html", users=users, cases=cases, uploads=uploads)

@app.route("/case/<int:case_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_case(case_id):
    case = Case.query.get_or_404(case_id)

    # Delete uploads + OCR texts
    for upload in case.uploads:
        if upload.ocr_text:
            db.session.delete(upload.ocr_text)
        db.session.delete(upload)

    # Delete notes
    for note in case.notes:
        db.session.delete(note)

    # Delete related payments if they exist
    try:
        payments = Payment.query.filter_by(case_id=case.id).all()
        for p in payments:
            db.session.delete(p)
    except Exception as e:
        print("Payments cleanup skipped:", e)

    # Finally delete the case
    db.session.delete(case)
    db.session.commit()
    flash("Case and all related data deleted.", "success")
    return redirect(url_for("admin_dashboard"))

# --- CLI helpers (with app context) ---
def cli_init_db():
    with app.app_context():
        INSTANCE_DIR.mkdir(exist_ok=True)
        Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
        db.create_all()
        print("Database initialized at:", app.config['SQLALCHEMY_DATABASE_URI'])

def cli_create_admin(email, name, password):
    with app.app_context():
        from sqlalchemy import select
        existing = db.session.execute(select(User).filter_by(email=email.lower())).scalar_one_or_none()
        if existing:
            print("User already exists:", email)
            return
        u = User(email=email.lower(), name=name, role="admin",
                 password_hash=generate_password_hash(password, method="pbkdf2:sha256"))
        db.session.add(u)
        db.session.commit()
        print("Admin created:", email)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OCR Case Tool")
    parser.add_argument("command", choices=["run", "init-db", "create-admin"], help="Command to execute.")
    parser.add_argument("--email", help="Admin email for create-admin")
    parser.add_argument("--name", help="Admin name for create-admin")
    parser.add_argument("--password", help="Admin password for create-admin")
    args = parser.parse_args()

    if args.command == "run":
        app.run(debug=True)
    elif args.command == "init-db":
        cli_init_db()
    elif args.command == "create-admin":
        if not (args.email and args.name and args.password):
            print("Usage: python app.py create-admin --email ... --name ... --password ...")
        else:
            cli_create_admin(args.email, args.name, args.password)