
# Payments OCR Add-on (Blueprint)

This folder adds **payment screenshot ingestion** + **table mapping** + **CSV/PDF export** to your Flask case tool.

## What it does
- `/payments/upload` — upload one or more screenshots (Google Pay, PhonePe, Paytm receipts).
- OCR runs with `pytesseract` and parses: amount, date/time, payee, VPA, UTR, UPI Txn ID, bank, status.
- Rows are saved into a new SQLAlchemy table `payments`.
- `/payments/` — list of parsed rows.
- `/payments/export/pdf` and `/payments/export/csv` — one-click exports.

## Install
1. Copy `payments/` folder into your project root (same level as `app.py`).
2. Ensure dependencies are present:
   - `pytesseract`, `Pillow`, `reportlab`, `pandas`
   - System: Tesseract OCR installed (`tesseract --version`).
3. **Wire the blueprint** in your `app.py` (after app + db are created):
   ```python
   from payments import payments_bp
   app.register_blueprint(payments_bp, url_prefix='/payments')
   ```
4. Make sure your base template has Bootstrap or adapt the HTML to your styling.
5. Start the app and visit `/payments/`.

## Notes
- The OCR regex is tuned for common Google Pay / PhonePe receipts. Add more patterns in `payments/ocr.py` as needed.
- `payments.models.payments_table` builds the model at runtime and calls `db.create_all()` so it does not break existing migrations.
- You can add relations (e.g., `case_id`) by setting those fields when creating `Payment` rows.
