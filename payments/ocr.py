
import re
from datetime import datetime

def clean_text(txt: str) -> str:
    t = txt.replace('\u20b9', '₹')
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\r?\n+', '\n', t)
    return t.strip()

AMOUNT_RE = re.compile(r'(?:₹|INR|Rs\.?)\s*([0-9][0-9,]*\.?[0-9]{0,2})')
UPI_TXN_RE = re.compile(r'(?:UPI|Txn|Transaction)\s*(?:ID|Id|id)\s*[:\-]?\s*([A-Za-z0-9\-]+)')
UTR_RE = re.compile(r'\bUTR[:\s]*([0-9]{8,16})\b')
VPA_RE = re.compile(r'\b([a-z0-9.\-_]+@[a-z]+)\b', re.I)
DATE_RE_1 = re.compile(r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4},?\s+\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))')
DATE_RE_2 = re.compile(r'(\d{1,2}[:.]\d{2}\s*(?:AM|PM|am|pm)\s+on\s+\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})')

def parse_datetime(s: str):
    for fmt in ("%d %b %Y, %I:%M %p", "%d %B %Y, %I:%M %p", "%I:%M %p on %d %b %Y", "%I:%M %p on %d %B %Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def guess_channel(text: str):
    t = text.lower()
    if "phonepe" in t:
        return "PhonePe"
    if "google pay" in t or "gpay" in t or "g pay" in t:
        return "Google Pay"
    if "paytm" in t:
        return "Paytm"
    return "UPI"

def extract(text: str) -> dict:
    t = clean_text(text)
    out = {
        "channel": guess_channel(t),
        "payer_name": None,
        "payee_name": None,
        "payee_vpa": None,
        "bank_name": None,
        "amount_inr": None,
        "currency": "INR",
        "utr": None,
        "upi_txn_id": None,
        "txn_status": None,
        "txn_time": None
    }

    amt = AMOUNT_RE.search(t)
    if amt:
        try:
            out["amount_inr"] = float(amt.group(1).replace(',', ''))
        except Exception:
            pass

    upi = UPI_TXN_RE.search(t)
    if upi:
        out["upi_txn_id"] = upi.group(1).strip()

    utr = UTR_RE.search(t)
    if utr:
        out["utr"] = utr.group(1)

    vpa = VPA_RE.search(t)
    if vpa:
        out["payee_vpa"] = vpa.group(1)

    m = re.search(r'(?:To|Paid to)\s*[:\-]?\s*([A-Za-z][A-Za-z .@&]+)', t)
    if m:
        out["payee_name"] = m.group(1).strip().split('\n')[0][:255]
    m = re.search(r'(?:From)\s*[:\-]?\s*([A-Za-z][A-Za-z .@&]+)', t)
    if m:
        out["payer_name"] = m.group(1).strip().split('\n')[0][:255]

    m = re.search(r'(?:Bank(?:ing)? Name|Debited from|State Bank of India|ICICI|HDFC|Axis|SBI)[^\n]*', t, re.I)
    if m:
        out["bank_name"] = m.group(0).replace('Banking Name', '').replace('Debited from', '').strip(' :-')

    status_match = re.search(r'\b(Completed|Success|Successful|Failed|Pending)\b', t, re.I)
    if status_match:
        out["txn_status"] = status_match.group(1).title()

    dt = None
    m = DATE_RE_1.search(t) or DATE_RE_2.search(t)
    if m:
        dt = parse_datetime(m.group(1))
    out["txn_time"] = dt

    return out
