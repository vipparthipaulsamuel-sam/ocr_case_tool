# payments/ocr.py

import re
from datetime import datetime

# ----------------------------
# Normalization helpers
# ----------------------------

def clean_text(txt: str) -> str:
    if not txt:
        return ""
    t = txt.replace("\u20b9", "₹")              # unify rupee symbol
    t = t.replace("\xa0", " ")
    t = re.sub(r"[|•·]+", " ", t)               # vertical bars / bullets -> space
    t = re.sub(r"[ \t]+", " ", t)               # collapse spaces
    t = re.sub(r"\r?\n\s*\n+", "\n", t)         # collapse blank lines
    t = t.strip()
    return t

def lines(txt: str):
    return [ln.strip() for ln in (txt or "").splitlines() if ln.strip()]

# ----------------------------
# Regex library
# ----------------------------

AMOUNT_RE = re.compile(r"(?:₹|INR|Rs\.?)\s*([0-9][0-9,]*\.?[0-9]{0,2})")
# Google Pay numeric “UPI transaction ID”
GUPI_ID_RE = re.compile(r"\b(?:UPI\s*transaction\s*ID|UPI\s*Transaction\s*ID)\b[: ]*([0-9]{8,})", re.I)
# PhonePe “Transaction ID” (often alphanumeric starting with T…)
PHONPE_TXN_RE = re.compile(r"\bTransaction\s*ID\b[: ]*([A-Z0-9\-]{10,})", re.I)
# UTR (numeric)
UTR_RE = re.compile(r"\bUTR[: ]*([0-9]{8,})", re.I)
# VPA (UPI handle)
VPA_RE = re.compile(r"\b([a-z0-9._-]+@[a-z]+)\b", re.I)

# Date-time patterns seen on slips
# Google Pay: "24 Aug 2025, 11:28 am"
GPAY_DT_RE = re.compile(
    r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})[, ]+\s*(\d{1,2}[:.]\d{2}\s*(?:AM|PM|am|pm))\b"
)
# PhonePe: "01:56 pm on 23 Aug 2025"
PHONEPE_DT_RE = re.compile(
    r"\b(\d{1,2}[:.]\d{2}\s*(?:AM|PM|am|pm))\s+on\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"
)

# Bank-ish line (captures things like "State Bank of India 5582", "ICICI", "HDFC", etc.)
BANK_LINE_RE = re.compile(
    r"(?:Debited\s*from[: ]*)?((?:State\s+Bank\s+of\s+India|SBI|ICICI|HDFC|Axis|Kotak|Bank\s+of\s+Baroda|Canara|Yes|IDFC|Punjab\s+National|Union\s+Bank)[^\n]{0,30})",
    re.I,
)

# Names
PAID_TO_RE = re.compile(r"\b(Paid\s*to|To)\b[: ]*([A-Z][A-Z .@&]+)", re.I)
FROM_RE = re.compile(r"\bFrom\b[: ]*([A-Z][A-Z .@&]+)", re.I)

STATUS_RE = re.compile(r"\b(Completed|Success|Successful|Failed|Pending|Declined)\b", re.I)

# ----------------------------
# Utilities
# ----------------------------

def _safe_float(s: str):
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None

def _parse_dt(date_part: str, time_part: str):
    # (date, time) -> datetime with multiple formats
    for fmt in (
        "%d %b %Y %I:%M %p",
        "%d %B %Y %I:%M %p",
        "%d %b %Y %H:%M",
        "%d %B %Y %H:%M",
    ):
        try:
            return datetime.strptime(f"{date_part} {time_part}", fmt)
        except Exception:
            continue
    return None

def _parse_phonepe_dt(m):
    # m.group(1) = time, m.group(2) = date
    time_part, date_part = m.group(1), m.group(2)
    for fmt in (
        "%I:%M %p %d %b %Y",
        "%I:%M %p %d %B %Y",
        "%H:%M %d %b %Y",
        "%H:%M %d %B %Y",
    ):
        try:
            return datetime.strptime(f"{time_part} {date_part}", fmt)
        except Exception:
            continue
    return None

def guess_channel(t: str):
    tl = t.lower()
    if "phonepe" in tl or "transaction successful" in tl and "phonepe" in tl:
        return "PhonePe"
    if "google pay" in tl or "gpay" in tl or "g pay" in tl:
        return "GPay"
    if "paytm" in tl:
        return "Paytm"
    return "UPI"

# ----------------------------
# Main extractor
# ----------------------------

def extract(text: str) -> dict:
    t = clean_text(text)
    ln = lines(t)

    out = {
        "channel": guess_channel(t),
        "payer_name": None,          # From
        "payee_name": None,          # To / Paid to
        "payee_vpa": None,
        "bank_name": None,           # debited account / bank line
        "amount_inr": None,
        "currency": "INR",
        "utr": None,
        "upi_txn_id": None,          # can be numeric (GPay) or alnum (PhonePe)
        "txn_status": None,
        "txn_time": None,
    }

    # -------- Amount ----------
    m_amt = AMOUNT_RE.search(t)
    if m_amt:
        out["amount_inr"] = _safe_float(m_amt.group(1))

    # -------- UPI Txn ID (two popular styles) ----------
    m_txn = GUPI_ID_RE.search(t) or PHONPE_TXN_RE.search(t)
    if m_txn:
        out["upi_txn_id"] = m_txn.group(1).strip()

    # -------- UTR ----------
    m_utr = UTR_RE.search(t)
    if m_utr:
        out["utr"] = m_utr.group(1).strip()

    # -------- VPA ----------
    # Prefer a VPA that appears near "Sent to", "To:", "Paid to"
    vpa_near = None
    for i, s in enumerate(ln):
        if re.search(r"\b(Sent to|To|Paid to)\b", s, re.I):
            # look current + next two lines for a VPA
            slab = " ".join(ln[i:i+3])
            m = VPA_RE.search(slab)
            if m:
                vpa_near = m.group(1).lower()
                break
    if not vpa_near:
        m_any_vpa = VPA_RE.search(t)
        if m_any_vpa:
            vpa_near = m_any_vpa.group(1).lower()
    out["payee_vpa"] = vpa_near

    # -------- Names (Paid to / To / From) ----------
    # Try explicit “Paid to …” first (PhonePe)
    m_paid = PAID_TO_RE.search(t)
    if m_paid:
        out["payee_name"] = m_paid.group(2).strip().replace("  ", " ")

    # Then Google Pay "To <NAME>" line (top of slip)
    if not out["payee_name"]:
        for s in ln[:6]:  # first few lines usually contain "To NAME"
            m = re.search(r"^\bTo\b\s+([A-Z][A-Z .@&]+)$", s, re.I)
            if m:
                out["payee_name"] = m.group(1).strip()
                break

    # "From ..." line (GPay bottom or PhonePe)
    m_from = FROM_RE.search(t)
    if m_from:
        out["payer_name"] = m_from.group(1).strip()

    # -------- Bank line (Debited from / SBI 5582 etc.) ----------
    # Prefer explicit "Debited from ..." (PhonePe)
    for s in ln:
        if re.search(r"\bDebited\s*from\b", s, re.I):
            # Keep masked suffix, e.g., XXXXXX1125 or bank+last4
            out["bank_name"] = s.split("Debited from", 1)[-1].strip(": -")
            break

    # If not found, try a bank-name line like "State Bank of India 5582"
    if not out["bank_name"]:
        m_bank = BANK_LINE_RE.search(t)
        if m_bank:
            out["bank_name"] = m_bank.group(1).strip()

    # -------- Status ----------
    m_status = STATUS_RE.search(t)
    if m_status:
        word = m_status.group(1).lower()
        if word.startswith("success"):
            out["txn_status"] = "Successful"
        else:
            out["txn_status"] = word.title()

    # -------- Date & Time ----------
    # Google Pay pattern
    m_dt = GPAY_DT_RE.search(t)
    if m_dt:
        date_part, time_part = m_dt.group(1), m_dt.group(2)
        out["txn_time"] = _parse_dt(date_part, time_part)
    else:
        # PhonePe pattern
        m2 = PHONEPE_DT_RE.search(t)
        if m2:
            out["txn_time"] = _parse_phonepe_dt(m2)

    return out