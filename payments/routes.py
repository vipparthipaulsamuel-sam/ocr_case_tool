import os
from datetime import datetime
from io import BytesIO

from flask import request, render_template, redirect, url_for, flash, send_file, abort
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from . import payments_bp
from .models import get_db, payments_table  # ✅ no import from app
from .ocr import extract

ALLOWED = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}  # keep images only here

def _db_and_model():
    """Fetch db and Payment lazily to avoid circular imports and table redefinition errors."""
    db = get_db()
    Payment = payments_table(db)  # has __table_args__ = {'extend_existing': True}
    return db, Payment

@payments_bp.route('/upload/<int:case_id>', methods=['POST'])
def upload_case(case_id):
    db, Payment = _db_and_model()

    files = request.files.getlist('files') or []
    if not files:
        f = request.files.get('file')
        if f:
            files = [f]
    if not files:
        flash('Please choose at least one file.', 'warning')
        return redirect(url_for('case_detail', case_id=case_id))

    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED:
            flash(f'Unsupported file type: {f.filename}', 'danger')
            continue

        # OCR (images only)
        img = Image.open(f.stream).convert('RGB')
        text = pytesseract.image_to_string(img, lang='eng')
        meta = extract(text)

        p = Payment(
            case_id=case_id,
            user_id=None,
            channel=meta.get('channel'),
            payer_name=meta.get('payer_name'),
            payee_name=meta.get('payee_name'),
            payee_vpa=meta.get('payee_vpa'),
            bank_name=meta.get('bank_name'),
            amount_inr=meta.get('amount_inr'),
            currency=meta.get('currency', 'INR'),
            utr=meta.get('utr'),
            upi_txn_id=meta.get('upi_txn_id'),
            txn_status=meta.get('txn_status'),
            txn_time=meta.get('txn_time'),
            raw_text=text,
            source_filename=secure_filename(f.filename)
        )
        db.session.add(p)
        saved += 1

    db.session.commit()
    flash(f'Processed {saved} file(s).', 'success')
    return redirect(url_for('case_detail', case_id=case_id))

@payments_bp.route('/edit/<int:payment_id>', methods=['GET', 'POST'])
def edit(payment_id):
    db, Payment = _db_and_model()
    p = Payment.query.get_or_404(payment_id)

    if request.method == 'POST':
        p.bank_name = request.form.get('bank_name') or p.bank_name
        p.utr = request.form.get('utr') or p.utr
        p.upi_txn_id = request.form.get('upi_txn_id') or p.upi_txn_id

        amt = request.form.get('amount_inr')
        if amt:
            try:
                p.amount_inr = float(amt)
            except Exception:
                pass

        p.payer_name = request.form.get('payer_name') or p.payer_name
        p.payee_vpa = request.form.get('payee_vpa') or p.payee_vpa
        p.payee_name = request.form.get('payee_name') or p.payee_name
        p.channel = request.form.get('channel') or p.channel
        p.txn_status = request.form.get('txn_status') or p.txn_status
        p.remarks = request.form.get('remarks') or p.remarks
        p.notes = request.form.get('notes') or p.notes

        date_str = request.form.get('date')
        time_str = request.form.get('time')
        if date_str or time_str:
            try:
                dt_str = (date_str or '') + ' ' + (time_str or '')
                p.txn_time = datetime.strptime(dt_str.strip(), '%Y-%m-%d %H:%M')
            except Exception:
                pass

        db.session.commit()
        flash('Payment updated.', 'success')
        return redirect(url_for('case_detail', case_id=p.case_id))

    return render_template('payments/edit.html', p=p)

@payments_bp.route('/delete/<int:payment_id>', methods=['POST'])
def delete_payment(payment_id):
    db, Payment = _db_and_model()
    p = Payment.query.get_or_404(payment_id)
    case_id = p.case_id
    db.session.delete(p)
    db.session.commit()
    flash('Payment deleted.', 'info')
    return redirect(url_for('case_detail', case_id=case_id))

@payments_bp.route('/export/pdf/case/<int:case_id>')
def export_pdf_case(case_id):
    db, Payment = _db_and_model()
    rows = Payment.query.filter_by(case_id=case_id).order_by(Payment.created_at.asc()).all()
    if not rows:
        abort(404, description='No payments for this case to export.')

    headers = [
        'Sl.NO',
        'Bank Name/ Wallet (Debited)',
        'UTR',
        'UPI reference No',
        'Amount',
        'Date of transaction',
        'Time of transaction',
        'UPI ID From',
        'UPI ID To',
        'Transaction ID',
        'Bank Name (Credited)',
    ]

    data = [headers]
    for i, r in enumerate(rows, start=1):
        row = r.to_row_excel(index=i)
        data.append([
            row.get('Sl.NO', ''),
            row.get('Bank Name/ Wallet (Debited)', ''),
            row.get('UTR', ''),
            row.get('UPI reference No', ''),
            row.get('Amount', ''),
            row.get('Date of transaction', ''),
            row.get('Time of transaction', ''),
            row.get('UPI ID From', ''),
            row.get('UPI ID To', ''),
            row.get('Transaction ID', ''),
            row.get('Bank Name (Credited)', ''),
        ])

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
    styles = getSampleStyleSheet()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
    ]))
    story = [Paragraph(f'Case #{case_id} — Payments Export', styles['Title']), Spacer(1, 8), table]
    doc.build(story)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'case_{case_id}_payments.pdf', mimetype='application/pdf')