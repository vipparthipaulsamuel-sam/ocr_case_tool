from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask import current_app
import re

def get_db() -> SQLAlchemy:
    return current_app.extensions["sqlalchemy"]

def now_utc():
    return datetime.utcnow()

def payments_table(db):
    class Payment(db.Model):
        __tablename__ = "payments"
        __table_args__ = {"extend_existing": True}

        id = db.Column(db.Integer, primary_key=True)
        user_id = db.Column(db.Integer, nullable=True, index=True)
        case_id = db.Column(db.Integer, nullable=True, index=True)

        channel = db.Column(db.String(50))
        payer_name = db.Column(db.String(255))
        payee_name = db.Column(db.String(255))
        payee_vpa = db.Column(db.String(255))
        bank_name = db.Column(db.String(255))
        amount_inr = db.Column(db.Numeric(12, 2))
        currency = db.Column(db.String(10), default="INR")
        utr = db.Column(db.String(64), index=True)
        upi_txn_id = db.Column(db.String(64), index=True)
        txn_status = db.Column(db.String(50))
        txn_time = db.Column(db.DateTime)
        raw_text = db.Column(db.Text)
        source_filename = db.Column(db.String(255))
        created_at = db.Column(db.DateTime, default=now_utc)

        remarks = db.Column(db.String(255))
        notes = db.Column(db.Text)

        # ---------- helpers for UI/Export ----------
        _VPA_RE = re.compile(r"\b[\w\.\-]+@[\w]+\b", re.I)

        @property
        def txn_date_str(self):
            return self.txn_time.strftime("%Y-%m-%d") if self.txn_time else ""

        @property
        def txn_time_str(self):
            return self.txn_time.strftime("%H:%M") if self.txn_time else ""

        @property
        def payer_vpa_guess(self):
            """
            Best-effort: first VPA in raw_text that's different from payee_vpa.
            """
            if not self.raw_text:
                return ""
            for m in self._VPA_RE.finditer(self.raw_text):
                v = m.group(0).lower()
                if self.payee_vpa and v == (self.payee_vpa or "").lower():
                    continue
                return v
            return ""

        def to_row(self):
            return {
                "Channel": self.channel or "",
                "Payer Name": self.payer_name or "",
                "Payee Name": self.payee_name or "",
                "Payee VPA": self.payee_vpa or "",
                "Bank": self.bank_name or "",
                "Amount (INR)": f"{self.amount_inr:.2f}" if self.amount_inr is not None else "",
                "Currency": self.currency or "INR",
                "UTR": self.utr or "",
                "UPI Transaction ID": self.upi_txn_id or "",
                "Status": self.txn_status or "",
                "Transaction Time": self.txn_time.isoformat(sep=" ") if self.txn_time else "",
                "Source File": self.source_filename or "",
                "Remarks": self.remarks or "",
                "Notes": (self.notes or "")[:500],
                "OCR Text": (self.raw_text or "")[:4000],
            }

        def to_row_excel(self, index=None):
            date_str = self.txn_time.strftime("%d-%m-%Y") if self.txn_time else ""
            time_str = self.txn_time.strftime("%I:%M %p") if self.txn_time else ""
            return {
                "Sl.NO": index if index is not None else "",
                "Bank Name/ Wallet (Debited)": self.bank_name or "",
                "UTR": self.utr or "",
                "UPI reference No": self.upi_txn_id or "",
                "Amount": f"{self.amount_inr:.2f}" if self.amount_inr is not None else "",
                "Date of transaction": date_str,
                "Time of transaction": time_str,
                "UPI ID From": self.payer_vpa_guess,  # better than payer_name for Excel column
                "UPI ID To": self.payee_vpa or "",
                "Transaction ID": self.upi_txn_id or "",
                "Bank Name (Credited)": self.payee_name or "",
            }

    return Payment