# payments/routes.py

import os
import uuid
from datetime import datetime
from io import BytesIO

from flask import (
    request, render_template, redirect, url_for, flash,
    send_file, abort, current_app, send_from_directory
)
from werkzeug.utils import secure_filename
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from . import payments_bp
from .models import get_db, payments_table  # lazy import to avoid circulars
# Optional: uploads_table if you have it
try:
    from .models import uploads_table
except Exception:
    uploads_table = None

from .ocr import extract

# Image-only uploads (no PDFs here)
ALLOWED = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def _db_and_model():
    """Fetch db and Payment lazily to avoid table re-definition issues."""
    db = get_db()
    Payment = payments_table(db)  # has extend_existing=True
    return db, Payment


# ---------- OCR helpers ----------

def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    g = img.convert("L")
    g = ImageEnhance.Contrast(g).enhance(1.6)
    g = g.filter(ImageFilter.SHARPEN)
    return g


def _ocr_image(img: Image.Image, cfg: str = "--oem 3 --psm 6") -> str:
    try:
        return pytesseract.image_to_string(img, lang="eng", config=cfg)
    except Exception:
        return ""


def _log_ocr_result(fname: str, text: str, meta: dict):
    try:
        head = (text or "").strip().replace("\r", " ").replace("\n", " ")[:220]
        print(
            f"[OCR] {fname}  :: "
            f"amount={meta.get('amount_inr')}  utr={meta.get('utr')}  "
            f"upi_id={meta.get('upi_txn_id')}  vpa={meta.get('payee_vpa')}  "
            f"payer={meta.get('payer_name')}  payee={meta.get('payee_name')}  "
            f"bank={meta.get('bank_name')}  status={meta.get('txn_status')}  "
            f"when={meta.get('txn_time')}"
        )
        print(f"[OCR TEXT HEAD] {head}")
    except Exception:
        pass


# ---------- Routes ----------

@payments_bp.route("/upload/<int:case_id>", methods=["POST"])
def upload_case(case_id):
    db, Payment = _db_and_model()

    files = request.files.getlist("files") or []
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        flash("Please choose at least one file.", "warning")
        return redirect(url_for("case_detail", case_id=case_id))

    upload_dir = current_app.config.get("UPLOAD_FOLDER", "") or "."
    os.makedirs(upload_dir, exist_ok=True)

    saved = 0
    for f in files:
        if not f or not f.filename:
            continue

        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED:
            flash(f"Unsupported file type: {f.filename}", "danger")
            continue

        safe_name = secure_filename(f.filename) or "upload"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(upload_dir, unique_name)

        img = Image.open(f.stream).convert("RGB")
        img.save(save_path)

        ocr_img = _preprocess_for_ocr(img)
        text = _ocr_image(ocr_img, cfg="--oem 3 --psm 6")
        if not text or len(text.strip()) < 8:
            alt = _ocr_image(img, cfg="--oem 3 --psm 4")
            if len(alt.strip()) > len(text.strip()):
                text = alt

        meta = extract(text or "")
        _log_ocr_result(safe_name, text, meta)

        p = Payment(
            case_id=case_id,
            user_id=None,
            channel=meta.get("channel"),
            payer_name=meta.get("payer_name"),
            payee_name=meta.get("payee_name"),
            payee_vpa=meta.get("payee_vpa"),
            bank_name=meta.get("bank_name"),
            amount_inr=meta.get("amount_inr"),
            currency=meta.get("currency", "INR"),
            utr=meta.get("utr"),
            upi_txn_id=meta.get("upi_txn_id"),
            txn_status=meta.get("txn_status"),
            txn_time=meta.get("txn_time"),
            raw_text=text or "",
            source_filename=unique_name,
        )
        db.session.add(p)
        saved += 1

    db.session.commit()
    flash(f"Processed {saved} file(s).", "success")
    return redirect(url_for("case_detail", case_id=case_id))


@payments_bp.route("/edit/<int:payment_id>", methods=["GET", "POST"])
def edit(payment_id):
    db, Payment = _db_and_model()
    p = Payment.query.get_or_404(payment_id)

    if request.method == "POST":
        for field in [
            "bank_name", "utr", "upi_txn_id", "payer_name",
            "payee_vpa", "payee_name", "channel",
            "txn_status", "remarks", "notes"
        ]:
            setattr(p, field, (request.form.get(field) or None))

        amt = request.form.get("amount_inr")
        if amt:
            try:
                p.amount_inr = float(amt.replace(",", ""))
            except Exception:
                pass

        date_str = request.form.get("date")
        time_str = request.form.get("time")
        if date_str or time_str:
            try:
                dt_str = ((date_str or "") + " " + (time_str or "")).strip()
                p.txn_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            except Exception:
                pass

        db.session.commit()
        flash("Payment updated.", "success")
        return redirect(url_for("case_detail", case_id=p.case_id))

    return render_template("payments/edit.html", p=p)


@payments_bp.route("/delete/<int:payment_id>", methods=["POST"])
def delete_payment(payment_id):
    db, Payment = _db_and_model()
    p = Payment.query.get_or_404(payment_id)
    case_id = p.case_id
    db.session.delete(p)
    db.session.commit()
    flash("Payment deleted.", "info")
    return redirect(url_for("case_detail", case_id=case_id))


@payments_bp.route("/export/pdf/case/<int:case_id>")
def export_pdf_case(case_id):
    db, Payment = _db_and_model()
    rows = (
        Payment.query
        .filter_by(case_id=case_id)
        .order_by(Payment.created_at.asc(), Payment.id.asc())
        .all()
    )
    if not rows:
        abort(404, description="No payments for this case to export.")

    upload_dir = current_app.config.get("UPLOAD_FOLDER", "") or "."
    image_paths = []
    for r in rows:
        fname = (r.source_filename or "").strip()
        if not fname:
            continue
        path = fname if os.path.isabs(fname) else os.path.join(upload_dir, fname)
        if os.path.exists(path):
            image_paths.append(path)

    if not image_paths:
        abort(404, description="No payment screenshots available to export.")

    buf = BytesIO()
    page_w, page_h = A4
    margin = 36
    c = canvas.Canvas(buf, pagesize=A4)

    for idx, img_path in enumerate(image_paths, start=1):
        try:
            ir = ImageReader(img_path)
            iw, ih = ir.getSize()
        except Exception:
            continue

        max_w = page_w - 2 * margin
        max_h = page_h - 2 * margin
        scale = min(max_w / float(iw), max_h / float(ih))
        draw_w = iw * scale
        draw_h = ih * scale
        x = (page_w - draw_w) / 2.0
        y = (page_h - draw_h) / 2.0

        c.drawImage(ir, x, y, width=draw_w, height=draw_h, preserveAspectRatio=True, anchor="c")
        label = f"{idx}"
        c.setFont("Helvetica-Bold", 12)
        c.drawString(page_w - margin - 12 * len(label), page_h - margin + 6, label)
        c.setFont("Helvetica", 8)
        c.drawCentredString(page_w / 2.0, margin / 2.0, os.path.basename(img_path))
        c.showPage()

    c.save()
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"case_{case_id}_payment_screenshots.pdf",
        mimetype="application/pdf",
    )


# Serve the original uploaded payment screenshot by filename (for preview in mapper)
@payments_bp.route("/uploads/<path:filename>")
def serve_upload_file(filename):
    upload_dir = current_app.config.get("UPLOAD_FOLDER", "") or "."
    return send_from_directory(upload_dir, filename)


# ======== NEW: Make PDF (single combined from arbitrary images) ========

@payments_bp.route("/make_pdf/<int:case_id>", methods=["POST"])
def make_pdf(case_id):
    files = request.files.getlist("pdf_files") or []
    if not files:
        flash("Please select at least one image.", "warning")
        return redirect(url_for("case_detail", case_id=case_id))

    imgs = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED:
            continue
        try:
            im = Image.open(f.stream).convert("RGB")
            imgs.append(im)
        except Exception:
            continue

    if not imgs:
        flash("No valid images to merge.", "danger")
        return redirect(url_for("case_detail", case_id=case_id))

    buf = BytesIO()
    first, rest = imgs[0], imgs[1:]
    first.save(buf, format="PDF", save_all=True, append_images=rest)
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"case_{case_id}_evidence.pdf",
        mimetype="application/pdf",
    )


# ======== NEW: Uploads edit/delete (if uploads_table is available) ========

@payments_bp.route("/uploads/edit/<int:upload_id>", methods=["GET", "POST"])
def edit_upload(upload_id):
    if uploads_table is None:
        flash("Upload editing is not configured.", "warning")
        return redirect(request.referrer or url_for("dashboard"))

    db = get_db()
    Upload = uploads_table(db)
    up = Upload.query.get_or_404(upload_id)

    if request.method == "POST":
        new_text = request.form.get("ocr_text", "")
        if hasattr(up, "ocr_text") and up.ocr_text:
            up.ocr_text.text = new_text
        elif hasattr(up, "ocr_text_text"):
            up.ocr_text_text = new_text
        else:
            setattr(up, "raw_text", new_text)
        db.session.commit()
        flash("Upload updated.", "success")
        return redirect(url_for("case_detail", case_id=up.case_id))

    return render_template("uploads/edit.html", up=up)


@payments_bp.route("/uploads/delete/<int:upload_id>", methods=["POST"])
def delete_upload(upload_id):
    if uploads_table is None:
        flash("Upload deletion is not configured.", "warning")
        return redirect(request.referrer or url_for("dashboard"))

    db = get_db()
    Upload = uploads_table(db)
    up = Upload.query.get_or_404(upload_id)
    case_id = up.case_id

    # If you also want to remove the stored file, uncomment:
    # try:
    #     upload_dir = current_app.config.get("UPLOAD_FOLDER", "") or "."
    #     if up.stored_filename:
    #         path = os.path.join(upload_dir, up.stored_filename)
    #         if os.path.exists(path): os.remove(path)
    # except Exception:
    #     pass

    db.session.delete(up)
    db.session.commit()
    flash("Upload deleted.", "info")
    return redirect(url_for("case_detail", case_id=case_id))