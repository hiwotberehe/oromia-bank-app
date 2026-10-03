"""
Oromia Bank - Real-Time Transaction System (Internship Prototype)
Built with Streamlit + SQLite.
"""
import glob
import hashlib
import io
import json
import os
import random
import secrets
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from fpdf import FPDF

from i18n import LANGS, TR

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
DB_PATH = "oromia_bank.db"
LOGO = os.path.join("assets", "logo.png")
GREEN = "#8DC63F"
BLUE = "#4B55A3"
SESSION_TIMEOUT_SEC = 600  # auto logout after 10 minutes of inactivity
OTP_VALID_SEC = 300
MAX_PIN_ATTEMPTS = 3

BILLERS = {
    "Ethiopian Electric Utility": ("Bill Payment", "Meter / contract number"),
    "Addis Ababa Water & Sewerage": ("Bill Payment", "Customer number"),
    "Ethio Telecom - Airtime": ("Airtime", "Phone number"),
    "Ethio Telecom - Internet / Data": ("Bill Payment", "Phone number"),
    "School Fees": ("Bill Payment", "Student ID"),
}

DEFAULT_SETTINGS = {
    "fee_free_limit": "1000",      # transfers up to this amount are free
    "fee_flat": "2.00",            # flat fee above the free limit
    "per_txn_limit": "200000",     # maximum amount per transaction
    "fraud_amount": "50000",       # flag transactions at or above this amount
    "new_ben_amount": "20000",     # flag large first-time transfers to a new receiver
    "velocity_count": "3",         # flag when sender already made this many txns...
    "velocity_minutes": "5",       # ...within this many minutes
    "dup_seconds": "20",           # block identical transfers within this window
    "low_balance": "500",          # low balance alert threshold
    "interbank_fee": "5.00",       # fee for transfers to other banks / mobile money
}

TRANSFER_TYPES = ("Transfer", "QR Payment")  # money moves to another customer of this bank

EXTERNAL_BANKS = [
    "Commercial Bank of Ethiopia", "Awash Bank", "Dashen Bank", "Bank of Abyssinia", "Wegagen Bank",
    "Nib International Bank", "Cooperative Bank of Oromia", "Hibret Bank", "Zemen Bank", "Abay Bank",
    "Telebirr (mobile money)", "M-Birr (mobile money)",
]

st.set_page_config(
    page_title="Oromia Bank | Digital Banking",
    page_icon=LOGO if os.path.exists(LOGO) else "🏦",
    layout="wide",
)

st.markdown(
    f"""
<style>
[data-testid="stSidebar"] {{ background:#fff; border-right:4px solid {GREEN}; }}
h1, h2, h3 {{ color:{BLUE}; }}
div.stButton > button, div.stDownloadButton > button,
div[data-testid="stFormSubmitButton"] > button {{
    background:{BLUE}; color:#fff; border:0; border-radius:8px; font-weight:600;
}}
div.stButton > button:hover, div.stDownloadButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover {{ background:{GREEN}; color:#fff; }}
.balance-card {{
    background:{BLUE}; color:#fff; padding:26px 28px; border-radius:14px;
    border-bottom:6px solid {GREEN};
}}
.balance-card .label {{ font-size:0.95rem; opacity:.85; }}
.balance-card .amount {{ font-size:2.4rem; font-weight:700; line-height:1.2; }}
.balance-card .acc {{ font-size:0.95rem; opacity:.9; margin-top:6px; }}
.sms-box {{
    background:#fff; border-left:5px solid {GREEN}; padding:10px 14px;
    border-radius:6px; margin-bottom:8px; font-size:0.93rem;
}}
.sms-box small {{ color:#6b7280; }}
</style>
""",
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------
# Database helpers
# ----------------------------------------------------------------------------
ET = timezone(timedelta(hours=3))  # Ethiopia time


def now_et():
    return datetime.now(ET).replace(tzinfo=None)


def ts_now():
    return now_et().strftime("%Y-%m-%d %H:%M:%S")


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def execute(sql, params=()):
    c = conn()
    try:
        c.execute(sql, params)
        c.commit()
    finally:
        c.close()


def fetch_one(sql, params=()):
    c = conn()
    try:
        return c.execute(sql, params).fetchone()
    finally:
        c.close()


def df(sql, params=()):
    c = conn()
    try:
        return pd.read_sql_query(sql, c, params=params)
    finally:
        c.close()


def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 100_000).hex()


def new_salt():
    return secrets.token_hex(8)


def money(x):
    return f"{float(x):,.2f} ETB"


def tr(key, **kw):
    """Translate a UI text into the language chosen by the user."""
    d = TR.get(key)
    if not d:
        return key
    text = d.get(st.session_state.get("lang", "en")) or d["en"]
    return text.format(**kw) if kw else text


def gen_ref(prefix="ORB"):
    return f"{prefix}{now_et().strftime('%y%m%d%H%M%S')}{random.randint(100, 999)}"


def init_db():
    c = conn()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            account_no TEXT PRIMARY KEY, name TEXT, phone TEXT, email TEXT,
            pin_hash TEXT, salt TEXT, role TEXT DEFAULT 'customer',
            balance REAL DEFAULT 0, status TEXT DEFAULT 'Active',
            daily_limit REAL DEFAULT 100000, failed_attempts INTEGER DEFAULT 0,
            created TEXT, savings REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE, ts TEXT,
            from_acc TEXT, to_acc TEXT, amount REAL, fee REAL, type TEXT,
            status TEXT, note TEXT, flag TEXT);
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, account_no TEXT,
            channel TEXT, message TEXT, seen INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT,
            action TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS beneficiaries(
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, account_no TEXT,
            nickname TEXT, UNIQUE(owner, account_no));
        CREATE TABLE IF NOT EXISTS blacklist(
            account_no TEXT PRIMARY KEY, reason TEXT, added TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS scheduled(
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, ttype TEXT, target TEXT,
            amount REAL, note TEXT, frequency TEXT, next_run TEXT, status TEXT,
            last_result TEXT, runs INTEGER DEFAULT 0, created TEXT);
        CREATE TABLE IF NOT EXISTS devices(
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_no TEXT, fingerprint TEXT,
            label TEXT, first_seen TEXT, last_seen TEXT);
        CREATE TABLE IF NOT EXISTS api_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, system TEXT, endpoint TEXT,
            request TEXT, response TEXT, status TEXT);
        """
    )
    # upgrade databases created by an earlier version of the app
    for table, col, ddl in [("users", "savings", "REAL DEFAULT 0"), ("notifications", "seen", "INTEGER DEFAULT 0")]:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    for k, v in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    c.commit()
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(c)
    c.close()


def seed(c):
    """Create demo admin, demo customers and some sample history."""
    people = [
        ("1000000001", "Bank Administrator", "0911000001", "admin@oromiabank.demo", "9999", "admin", 0),
        ("1000000101", "Abebe Kebede", "0911000101", "abebe@example.com", "1234", "customer", 50000),
        ("1000000102", "Chaltu Tadesse", "0911000102", "chaltu@example.com", "1234", "customer", 75000),
        ("1000000103", "Dawit Alemu", "0911000103", "dawit@example.com", "1234", "customer", 20000),
        ("1000000104", "Hirut Bekele", "0911000104", "hirut@example.com", "1234", "customer", 120000),
    ]
    for acc, name, phone, email, pin, role, bal in people:
        salt = new_salt()
        c.execute(
            "INSERT INTO users(account_no,name,phone,email,pin_hash,salt,role,balance,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (acc, name, phone, email, hash_pin(pin, salt), salt, role, bal, ts_now()),
        )
    rnd = random.Random(7)
    custs = [p[0] for p in people if p[5] == "customer"]
    for i in range(40):
        a, b = rnd.sample(custs, 2)
        amt = rnd.choice([150, 300, 500, 800, 1200, 2500, 4000, 7500, 15000])
        when = now_et() - timedelta(days=rnd.randint(0, 6), hours=rnd.randint(0, 10), minutes=rnd.randint(0, 59))
        fee = 2.0 if amt > 1000 else 0.0
        c.execute(
            "INSERT INTO transactions(ref,ts,from_acc,to_acc,amount,fee,type,status,note,flag) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (f"ORBDEMO{i:04d}", when.strftime("%Y-%m-%d %H:%M:%S"), a, b, amt, fee, "Transfer", "Completed", "Sample data", ""),
        )
    c.execute("UPDATE users SET savings=10000 WHERE role='customer'")
    c.commit()


def get_setting(key):
    r = fetch_one("SELECT value FROM settings WHERE key=?", (key,))
    return float(r["value"]) if r else float(DEFAULT_SETTINGS[key])


def set_setting(key, value):
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))


def fetch_user(acc):
    return fetch_one("SELECT * FROM users WHERE account_no=?", (acc,))


def audit(actor, action, detail=""):
    execute("INSERT INTO audit(ts,actor,action,detail) VALUES(?,?,?,?)", (ts_now(), actor, action, detail))


def notify(acc, message, channel="SMS"):
    execute(
        "INSERT INTO notifications(ts,account_no,channel,message) VALUES(?,?,?,?)",
        (ts_now(), acc, channel, message),
    )


def compute_fee(amount, ttype="Transfer"):
    if ttype == "Other Bank":
        return get_setting("interbank_fee")
    return get_setting("fee_flat") if amount > get_setting("fee_free_limit") else 0.0


def spent_today(acc):
    today = now_et().strftime("%Y-%m-%d")
    r = fetch_one(
        "SELECT COALESCE(SUM(amount),0) s FROM transactions WHERE from_acc=? AND status='Completed' "
        "AND type IN ('Transfer','QR Payment','Bill Payment','Airtime','Other Bank') AND substr(ts,1,10)=?",
        (acc, today),
    )
    return float(r["s"])


# ----------------------------------------------------------------------------
# Core: real-time transaction engine
# ----------------------------------------------------------------------------
def process_transaction(sender, receiver, amount, note="", ttype="Transfer"):
    """Validate and process a transaction atomically.
    Returns (success, message, ref)."""
    amount = round(float(amount), 2)
    ref = gen_ref()
    ts = ts_now()

    def failed(reason):
        execute(
            "INSERT INTO transactions(ref,ts,from_acc,to_acc,amount,fee,type,status,note,flag) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ref, ts, sender, receiver, amount, 0, ttype, "Failed", reason, ""),
        )
        notify(sender, f"Your {ttype.lower()} of {money(amount)} failed: {reason}")
        return False, reason, None

    if amount <= 0:
        return False, "Amount must be greater than zero.", None
    if amount > get_setting("per_txn_limit"):
        return failed(f"Amount is above the per-transaction limit of {money(get_setting('per_txn_limit'))}.")

    fee = compute_fee(amount, ttype)
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")  # lock the DB so two transactions can't double-spend
        s = c.execute("SELECT * FROM users WHERE account_no=?", (sender,)).fetchone()
        if s is None or s["status"] != "Active":
            c.rollback()
            return failed("Your account is not active.")

        is_transfer = ttype in TRANSFER_TYPES
        r = None
        if is_transfer:
            r = c.execute("SELECT * FROM users WHERE account_no=?", (receiver,)).fetchone()
            if r is None or r["role"] != "customer":
                c.rollback()
                return failed("Receiver account was not found.")
            if r["account_no"] == s["account_no"]:
                c.rollback()
                return failed("You cannot send money to your own account.")
            if r["status"] != "Active":
                c.rollback()
                return failed("Receiver account is not active.")
            bl = c.execute(
                "SELECT 1 FROM blacklist WHERE account_no IN (?,?)", (receiver, sender)
            ).fetchone()
            if bl:
                c.rollback()
                return failed("Transaction blocked: an account involved is blacklisted.")

        if s["balance"] < amount + fee:
            c.rollback()
            return failed("Insufficient balance (amount plus fee).")

        today = now_et().strftime("%Y-%m-%d")
        spent = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE from_acc=? AND status='Completed' "
            "AND type IN ('Transfer','QR Payment','Bill Payment','Airtime','Other Bank') AND substr(ts,1,10)=?",
            (sender, today),
        ).fetchone()[0]
        if spent + amount > s["daily_limit"]:
            left = max(s["daily_limit"] - spent, 0)
            c.rollback()
            return failed(f"Daily limit exceeded. You can still send {money(left)} today.")

        since = (now_et() - timedelta(seconds=int(get_setting("dup_seconds")))).strftime("%Y-%m-%d %H:%M:%S")
        dup = c.execute(
            "SELECT 1 FROM transactions WHERE from_acc=? AND to_acc=? AND amount=? AND status='Completed' AND ts>=?",
            (sender, receiver, amount, since),
        ).fetchone()
        if dup:
            c.rollback()
            return failed("Duplicate transaction blocked. Wait a few seconds before repeating it.")

        # ---- fraud rules (transaction still completes, but is flagged) ----
        flags = []
        if amount >= get_setting("fraud_amount"):
            flags.append("High amount")
        vsince = (now_et() - timedelta(minutes=int(get_setting("velocity_minutes")))).strftime("%Y-%m-%d %H:%M:%S")
        recent = c.execute(
            "SELECT COUNT(*) FROM transactions WHERE from_acc=? AND status='Completed' AND ts>=?",
            (sender, vsince),
        ).fetchone()[0]
        if recent >= get_setting("velocity_count"):
            flags.append("Too many transactions in a short time")
        if is_transfer:
            prev = c.execute(
                "SELECT COUNT(*) FROM transactions WHERE from_acc=? AND to_acc=? AND type IN ('Transfer','QR Payment') AND status='Completed'",
                (sender, receiver),
            ).fetchone()[0]
            if prev == 0 and amount >= get_setting("new_ben_amount"):
                flags.append("Large transfer to a new receiver")
        flag = "; ".join(flags)

        # ---- move the money ----
        c.execute("UPDATE users SET balance = balance - ? WHERE account_no=?", (amount + fee, sender))
        if is_transfer:
            c.execute("UPDATE users SET balance = balance + ? WHERE account_no=?", (amount, receiver))
        c.execute(
            "INSERT INTO transactions(ref,ts,from_acc,to_acc,amount,fee,type,status,note,flag) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ref, ts, sender, receiver, amount, fee, ttype, "Completed", note, flag),
        )
        c.commit()
        new_bal = s["balance"] - amount - fee
    except Exception as e:  # any unexpected error: undo everything
        c.rollback()
        return failed(f"System error, nothing was deducted: {e}")
    finally:
        c.close()

    # ---- notifications and audit (after commit) ----
    if is_transfer:
        notify(sender, f"Dear {s['name']}, you sent {money(amount)} to {r['name']} ({receiver}). Fee {money(fee)}. Balance {money(new_bal)}. Ref {ref}.")
        notify(receiver, f"Dear {r['name']}, you received {money(amount)} from {s['name']} ({sender}). Ref {ref}.")
    else:
        notify(sender, f"Dear {s['name']}, payment of {money(amount)} to {receiver} was successful. Balance {money(new_bal)}. Ref {ref}.")
    if new_bal < get_setting("low_balance"):
        notify(sender, f"Low balance alert: your balance is {money(new_bal)}.")
    if flag:
        notify(sender, f"Security notice: transaction {ref} was flagged for review ({flag}).", "Email")
    audit(sender, f"{ttype} completed", f"{ref} {money(amount)} to {receiver}" + (f" FLAG: {flag}" if flag else ""))
    label = {"Other Bank": "Transfer to another bank", "QR Payment": "QR payment"}.get(ttype, ttype)
    return True, f"{label} of {money(amount)} completed successfully.", ref


def reverse_transaction(ref, admin, reason):
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        t = c.execute("SELECT * FROM transactions WHERE ref=?", (ref,)).fetchone()
        if not t or t["status"] != "Completed" or t["type"] not in TRANSFER_TYPES:
            c.rollback()
            return False, "Only completed transfers can be reversed."
        r = c.execute("SELECT balance FROM users WHERE account_no=?", (t["to_acc"],)).fetchone()
        if r["balance"] < t["amount"]:
            c.rollback()
            return False, "Receiver no longer has enough balance to reverse this transfer."
        c.execute("UPDATE users SET balance=balance-? WHERE account_no=?", (t["amount"], t["to_acc"]))
        c.execute("UPDATE users SET balance=balance+? WHERE account_no=?", (t["amount"] + t["fee"], t["from_acc"]))
        c.execute("UPDATE transactions SET status='Reversed' WHERE ref=?", (ref,))
        c.execute(
            "INSERT INTO transactions(ref,ts,from_acc,to_acc,amount,fee,type,status,note,flag) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (gen_ref("REV"), ts_now(), t["to_acc"], t["from_acc"], t["amount"], 0, "Reversal", "Completed",
             f"Reversal of {ref}: {reason}", ""),
        )
        c.commit()
    except Exception as e:
        c.rollback()
        return False, f"Reversal failed: {e}"
    finally:
        c.close()
    notify(t["from_acc"], f"Transaction {ref} of {money(t['amount'])} was reversed. Amount and fee returned to your account.")
    notify(t["to_acc"], f"Transaction {ref} of {money(t['amount'])} was reversed by the bank.")
    audit(admin, "Transaction reversed", f"{ref}: {reason}")
    return True, f"Transaction {ref} reversed."


# ----------------------------------------------------------------------------
# Security: PIN, OTP, receipts
# ----------------------------------------------------------------------------
def check_pin(acc, pin):
    """Verify PIN, count failures and lock the account after too many attempts."""
    u = fetch_user(acc)
    if not u:
        return False, "Invalid account number or PIN."
    if u["status"] != "Active":
        return False, "This account is locked. Please contact your branch or the bank admin."
    if hash_pin(pin, u["salt"]) == u["pin_hash"]:
        execute("UPDATE users SET failed_attempts=0 WHERE account_no=?", (acc,))
        return True, ""
    attempts = u["failed_attempts"] + 1
    if attempts >= MAX_PIN_ATTEMPTS:
        execute("UPDATE users SET failed_attempts=?, status='Locked' WHERE account_no=?", (attempts, acc))
        audit(acc, "Account locked", "Too many wrong PIN attempts")
        notify(acc, "Your account was locked after too many wrong PIN attempts.")
        return False, "Too many wrong attempts. Your account is now locked."
    execute("UPDATE users SET failed_attempts=? WHERE account_no=?", (attempts, acc))
    return False, f"Invalid account number or PIN. {MAX_PIN_ATTEMPTS - attempts} attempt(s) left."


def make_receipt(ref):
    t = fetch_one("SELECT * FROM transactions WHERE ref=?", (ref,))
    if not t:
        return None
    s = fetch_user(t["from_acc"])
    r = fetch_user(t["to_acc"])

    def clean(x):
        return str(x).encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF()
    pdf.add_page()
    if os.path.exists(LOGO):
        pdf.image(LOGO, x=10, y=10, w=70)
    pdf.set_y(48)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(75, 85, 163)
    pdf.cell(0, 12, "Transaction Receipt", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(141, 198, 63)
    pdf.set_line_width(0.8)
    pdf.line(10, 62, 200, 62)
    pdf.ln(8)
    rows = [
        ("Reference", t["ref"]),
        ("Date and time", t["ts"]),
        ("Type", t["type"]),
        ("From", f"{s['name']} ({t['from_acc']})" if s else t["from_acc"]),
        ("To", f"{r['name']} ({t['to_acc']})" if r else t["to_acc"]),
        ("Amount", money(t["amount"])),
        ("Fee", money(t["fee"])),
        ("Total debited", money(t["amount"] + t["fee"])),
        ("Status", t["status"]),
        ("Note", t["note"] or "-"),
    ]
    pdf.set_text_color(31, 36, 51)
    for k, v in rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(50, 9, clean(k))
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 9, clean(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 6, "Generated by the Oromia Bank digital banking prototype.", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def to_excel(frame):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        frame.to_excel(w, index=False, sheet_name="Report")
    return buf.getvalue()


# ----------------------------------------------------------------------------
# Login (account + PIN, then OTP)
# ----------------------------------------------------------------------------
def logout(msg=None):
    lang = st.session_state.get("lang")
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    if lang:
        st.session_state["lang"] = lang
    if msg:
        st.session_state["logout_msg"] = msg
    st.rerun()


def lang_selector(key):
    names = list(LANGS.keys())
    cur = next((i for i, v in enumerate(LANGS.values()) if v == st.session_state.get("lang", "en")), 0)
    sel = st.selectbox("Language / ቋንቋ / Afaan", names, index=cur, key=key)
    st.session_state["lang"] = LANGS[sel]


def login_page():
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        if os.path.exists(LOGO):
            st.image(LOGO, width="stretch")
        lang_selector("lang_login")
        st.markdown(f"<h3 style='text-align:center;margin-top:0'>{tr('portal')}</h3>", unsafe_allow_html=True)
        if st.session_state.get("logout_msg"):
            st.warning(st.session_state.pop("logout_msg"))

        pending = st.session_state.get("pending_acc")
        if not pending:
            with st.form("login_form"):
                acc = st.text_input(tr("acc_no"))
                pin = st.text_input(tr("pin"), type="password", max_chars=6)
                go = st.form_submit_button(tr("continue"), width="stretch")
            if go:
                ok, msg = check_pin(acc.strip(), pin)
                if ok:
                    st.session_state.pending_acc = acc.strip()
                    st.session_state.otp = f"{random.randint(0, 999999):06d}"
                    st.session_state.otp_time = time.time()
                    st.rerun()
                else:
                    st.error(msg)
            with st.expander(tr("demo_accounts")):
                st.markdown(
                    "| Role | Account | PIN |\n|---|---|---|\n"
                    "| Customer | 1000000101 | 1234 |\n| Customer | 1000000102 | 1234 |\n"
                    "| Customer | 1000000103 | 1234 |\n| Customer | 1000000104 | 1234 |\n"
                    "| Bank admin | 1000000001 | 9999 |"
                )
        else:
            u = fetch_user(pending)
            st.info(tr("otp_sent", p=u["phone"][-4:]))
            st.caption(f"Demo mode (no real SMS gateway): your code is **{st.session_state.otp}**")
            with st.form("otp_form"):
                code = st.text_input(tr("enter_code"), max_chars=6)
                c1, c2 = st.columns(2)
                verify = c1.form_submit_button(tr("verify"), width="stretch")
                back = c2.form_submit_button(tr("back"), width="stretch")
            if back:
                for k in ("pending_acc", "otp", "otp_time"):
                    st.session_state.pop(k, None)
                st.rerun()
            if verify:
                if time.time() - st.session_state.otp_time > OTP_VALID_SEC:
                    st.error("The code expired. Go back and sign in again.")
                elif code.strip() != st.session_state.otp:
                    st.error("Wrong code. Check the code and try again.")
                else:
                    st.session_state.acc = pending
                    st.session_state.role = u["role"]
                    st.session_state.last_active = time.time()
                    st.session_state.form_n = 0
                    for k in ("pending_acc", "otp", "otp_time"):
                        st.session_state.pop(k, None)
                    register_device(pending)
                    audit(pending, "Login", "Signed in with PIN and OTP")
                    st.rerun()


def me():
    return fetch_user(st.session_state.acc)


# ----------------------------------------------------------------------------
# Customer pages
# ----------------------------------------------------------------------------
def history_frame(acc):
    return df(
        "SELECT ts AS Time, ref AS Reference, type AS Type, "
        "CASE WHEN from_acc=? THEN 'Debit' ELSE 'Credit' END AS Direction, "
        "from_acc AS 'From', to_acc AS 'To', amount AS Amount, fee AS Fee, status AS Status, note AS Note "
        "FROM transactions WHERE from_acc=? OR to_acc=? ORDER BY id DESC",
        (acc, acc, acc),
    )


def page_dashboard():
    u = me()
    st.header(f"{tr('welcome')}, {u['name'].split()[0]}")
    st.markdown(
        f"""<div class="balance-card"><div class="label">{tr('avail_balance')}</div>
        <div class="amount">{money(u['balance'])}</div>
        <div class="acc">{tr('account')} {u['account_no']} &nbsp;|&nbsp; {tr('savings_balance')}: {money(u['savings'])}</div></div>""",
        unsafe_allow_html=True,
    )
    st.write("")
    spent = spent_today(u["account_no"])
    limit = float(u["daily_limit"])
    c1, c2, c3 = st.columns(3)
    c1.metric(tr("spent_today"), money(spent))
    c2.metric(tr("daily_limit"), money(limit))
    c3.metric(tr("remaining_today"), money(max(limit - spent, 0)))
    st.progress(min(spent / limit, 1.0) if limit else 0.0)
    st.subheader(tr("recent"))
    h = history_frame(u["account_no"]).head(6)
    if h.empty:
        st.info("No transactions yet. Use Send money to make your first transfer.")
    else:
        st.dataframe(h.drop(columns=["Note"]), width="stretch", hide_index=True)


def show_last_receipt():
    ref = st.session_state.get("last_ref")
    if not ref:
        return
    st.success(st.session_state.get("last_msg", "Done."))
    pdf = make_receipt(ref)
    c1, c2 = st.columns([1, 1])
    if pdf:
        c1.download_button(tr("dl_receipt"), pdf, file_name=f"receipt_{ref}.pdf", mime="application/pdf")
    if c2.button(tr("another")):
        st.session_state.pop("last_ref", None)
        st.session_state.form_n += 1
        st.rerun()
    st.stop()


def page_transfer():
    u = me()
    n = st.session_state.form_n
    st.header(tr("m_send"))
    show_last_receipt()
    st.caption(f"Balance: {money(u['balance'])}")

    bens = df("SELECT account_no, nickname FROM beneficiaries WHERE owner=?", (u["account_no"],))
    manual = "Enter an account number"
    options = [manual] + [f"{r.nickname} - {r.account_no}" for r in bens.itertuples()]
    choice = st.selectbox(tr("send_to"), options, key=f"to_{n}")
    receiver = st.text_input(tr("receiver_acc"), key=f"racc_{n}").strip() if choice == manual else choice.split(" - ")[-1]

    valid_receiver = False
    if receiver:
        r = fetch_user(receiver)
        if r and r["role"] == "customer" and receiver != u["account_no"]:
            st.success(f"Account holder: {r['name']}")
            valid_receiver = True
        else:
            st.warning("No customer account found with this number.")

    amount = st.number_input(tr("amount"), min_value=0.0, step=100.0, format="%.2f", key=f"amt_{n}")
    note = st.text_input(tr("note_opt"), max_chars=60, key=f"note_{n}")
    fee = compute_fee(amount)
    st.caption(f"Fee: {money(fee)}   |   Total to be debited: {money(amount + fee)}")
    pin = st.text_input(tr("confirm_pin"), type="password", max_chars=6, key=f"pin_{n}")
    save_ben = False
    if choice == manual and valid_receiver:
        save_ben = st.checkbox("Save this receiver for next time", key=f"save_{n}")

    if st.button(tr("send_btn")):
        if not valid_receiver:
            st.error("Enter a valid receiver account number.")
        elif amount <= 0:
            st.error("Enter an amount greater than zero.")
        else:
            ok, msg = check_pin(u["account_no"], pin)
            if not ok:
                st.error(msg)
                if "locked" in msg.lower():
                    time.sleep(1.5)
                    logout("Your account was locked. Please contact your branch.")
            else:
                ok, msg, ref = process_transaction(u["account_no"], receiver, amount, note, "Transfer")
                if ok:
                    if save_ben:
                        execute(
                            "INSERT OR IGNORE INTO beneficiaries(owner,account_no,nickname) VALUES(?,?,?)",
                            (u["account_no"], receiver, fetch_user(receiver)["name"]),
                        )
                    st.session_state.last_ref = ref
                    st.session_state.last_msg = f"{msg} Reference: {ref}"
                    st.rerun()
                else:
                    st.error(msg)


def page_bills():
    u = me()
    n = st.session_state.form_n
    st.header(tr("m_bills"))
    show_last_receipt()
    st.caption(f"Balance: {money(u['balance'])}")
    biller = st.selectbox("Service", list(BILLERS.keys()), key=f"biller_{n}")
    ttype, label = BILLERS[biller]
    cust_no = st.text_input(label, key=f"cust_{n}").strip()
    amount = st.number_input("Amount (ETB)", min_value=0.0, step=50.0, format="%.2f", key=f"bamt_{n}")
    st.caption(f"Fee: {money(compute_fee(amount))}")
    pin = st.text_input(tr("confirm_pin"), type="password", max_chars=6, key=f"bpin_{n}")
    if st.button(tr("pay_now")):
        if not cust_no:
            st.error(f"Enter the {label.lower()}.")
        elif amount <= 0:
            st.error("Enter an amount greater than zero.")
        else:
            ok, msg = check_pin(u["account_no"], pin)
            if not ok:
                st.error(msg)
            else:
                ok, msg, ref = process_transaction(u["account_no"], biller, amount, f"{label}: {cust_no}", ttype)
                if ok:
                    st.session_state.last_ref = ref
                    st.session_state.last_msg = f"{msg} Reference: {ref}"
                    st.rerun()
                else:
                    st.error(msg)


def page_beneficiaries():
    u = me()
    st.header(tr("m_receivers"))
    with st.form("add_ben", clear_on_submit=True):
        acc = st.text_input("Receiver account number")
        nick = st.text_input("Nickname")
        add = st.form_submit_button("Save receiver")
    if add:
        r = fetch_user(acc.strip())
        if not r or r["role"] != "customer" or acc.strip() == u["account_no"]:
            st.error("No valid customer account found with this number.")
        else:
            execute(
                "INSERT OR REPLACE INTO beneficiaries(owner,account_no,nickname) VALUES(?,?,?)",
                (u["account_no"], acc.strip(), nick.strip() or r["name"]),
            )
            st.success(f"Saved {r['name']}.")
    bens = df("SELECT account_no AS Account, nickname AS Nickname FROM beneficiaries WHERE owner=?", (u["account_no"],))
    if bens.empty:
        st.info("You have no saved receivers yet. Add one above.")
    else:
        st.dataframe(bens, width="stretch", hide_index=True)
        rm = st.selectbox("Remove a receiver", bens["Account"].tolist())
        if st.button("Remove receiver"):
            execute("DELETE FROM beneficiaries WHERE owner=? AND account_no=?", (u["account_no"], rm))
            st.rerun()


def page_history():
    u = me()
    st.header(tr("m_history"))
    h = history_frame(u["account_no"])
    if h.empty:
        st.info("No transactions yet.")
        return
    c1, c2 = st.columns(2)
    types = c1.multiselect("Type", sorted(h["Type"].unique()), default=sorted(h["Type"].unique()))
    statuses = c2.multiselect("Status", sorted(h["Status"].unique()), default=sorted(h["Status"].unique()))
    view = h[h["Type"].isin(types) & h["Status"].isin(statuses)]
    st.dataframe(view, width="stretch", hide_index=True)
    st.download_button("Download statement (CSV)", view.to_csv(index=False), "statement.csv", "text/csv")
    done = view[view["Status"].isin(["Completed", "Reversed"])]["Reference"].tolist()
    if done:
        st.subheader("Receipt")
        ref = st.selectbox("Choose a transaction", done)
        pdf = make_receipt(ref)
        if pdf:
            st.download_button("Download receipt (PDF)", pdf, file_name=f"receipt_{ref}.pdf", mime="application/pdf")


def page_notifications():
    u = me()
    st.header(tr("m_notif"))
    st.caption("SMS, email and push alerts for your account (simulated in this prototype). New alerts also pop up on screen.")
    n = df("SELECT ts, channel, message FROM notifications WHERE account_no=? ORDER BY id DESC LIMIT 30", (u["account_no"],))
    if n.empty:
        st.info("No notifications yet.")
    for r in n.itertuples():
        st.markdown(f"<div class='sms-box'>{r.message}<br><small>{r.channel} | {r.ts}</small></div>", unsafe_allow_html=True)


def page_profile():
    u = me()
    st.header(tr("m_profile"))
    c1, c2 = st.columns(2)
    c1.write(f"**Name:** {u['name']}")
    c1.write(f"**Account:** {u['account_no']}")
    c1.write(f"**Phone:** {u['phone']}")
    c2.write(f"**Email:** {u['email']}")
    c2.write(f"**Status:** {u['status']}")
    c2.write(f"**Daily limit:** {money(u['daily_limit'])}")
    st.subheader("Change PIN")
    with st.form("chpin", clear_on_submit=True):
        old = st.text_input("Current PIN", type="password", max_chars=6)
        new = st.text_input("New PIN (4 to 6 digits)", type="password", max_chars=6)
        new2 = st.text_input("Repeat new PIN", type="password", max_chars=6)
        go = st.form_submit_button("Change PIN")
    if go:
        ok, msg = check_pin(u["account_no"], old)
        if not ok:
            st.error(msg)
        elif not (new.isdigit() and 4 <= len(new) <= 6):
            st.error("The new PIN must be 4 to 6 digits.")
        elif new != new2:
            st.error("The two new PINs do not match.")
        else:
            salt = new_salt()
            execute("UPDATE users SET pin_hash=?, salt=? WHERE account_no=?", (hash_pin(new, salt), salt, u["account_no"]))
            audit(u["account_no"], "PIN changed")
            notify(u["account_no"], "Your PIN was changed successfully.")
            st.success("PIN changed.")

    st.subheader("Registered devices")
    st.caption(f"You can have up to {MAX_DEVICES} devices. A sign-in from a new device sends you an alert. "
               "When you add one more, the least recently used device is removed.")
    cur_fp, _ = device_info()
    devs = df("SELECT id, fingerprint, label AS Device, first_seen AS 'First seen', last_seen AS 'Last used' "
              "FROM devices WHERE account_no=? ORDER BY last_seen DESC", (u["account_no"],))
    if devs.empty:
        st.info("No devices registered yet.")
    else:
        view = devs.assign(**{"This device": devs["fingerprint"].map(lambda f: "Yes" if f == cur_fp else "")})
        st.dataframe(view.drop(columns=["id", "fingerprint"]), width="stretch", hide_index=True)
        others = devs[devs["fingerprint"] != cur_fp]
        if not others.empty:
            pick = st.selectbox("Remove a device", others["id"].tolist(),
                                format_func=lambda i: others[others["id"] == i].iloc[0]["Device"])
            if st.button("Remove device"):
                execute("DELETE FROM devices WHERE id=? AND account_no=?", (int(pick), u["account_no"]))
                audit(u["account_no"], "Device removed", str(pick))
                st.rerun()


# ----------------------------------------------------------------------------
# Admin pages
# ----------------------------------------------------------------------------
def tx_frame(where="1=1", params=()):
    return df(
        "SELECT id, ts AS Time, ref AS Reference, type AS Type, from_acc AS 'From', to_acc AS 'To', "
        "amount AS Amount, fee AS Fee, status AS Status, flag AS Flag, note AS Note "
        f"FROM transactions WHERE {where} ORDER BY id DESC",
        params,
    )


def page_admin_dashboard():
    st.header("Live transaction monitor")
    t = tx_frame()
    today = now_et().strftime("%Y-%m-%d")
    td = t[t["Time"].str[:10] == today]
    done = td[td["Status"] == "Completed"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Transactions today", len(td))
    c2.metric("Value today", money(done["Amount"].sum()))
    c3.metric("Failed today", int((td["Status"] == "Failed").sum()))
    c4.metric("Flagged (all)", int((t["Flag"] != "").sum()))
    c5.metric("Fee revenue today", money(done["Fee"].sum()))

    deposits = df("SELECT COALESCE(SUM(balance),0) s, COUNT(*) n FROM users WHERE role='customer'").iloc[0]
    st.caption(f"{int(deposits['n'])} customer accounts | total balances {money(deposits['s'])}")

    st.subheader("Latest transactions")
    st.dataframe(t.drop(columns=["id", "Note"]).head(15), width="stretch", hide_index=True)

    ok = t[t["Status"] == "Completed"]
    if not ok.empty:
        a, b = st.columns(2)
        a.subheader("Daily transaction value")
        a.bar_chart(ok.assign(Day=ok["Time"].str[:10]).groupby("Day")["Amount"].sum())
        b.subheader("Transactions by hour")
        b.bar_chart(ok.assign(Hour=ok["Time"].str[11:13]).groupby("Hour")["Reference"].count())

    if st.toggle("Live mode (refresh every 5 seconds)"):
        time.sleep(5)
        st.rerun()


def page_admin_customers():
    st.header("Customers")
    tab1, tab2, tab3 = st.tabs(["Accounts", "Open new account", "Blacklist"])
    with tab1:
        users = df(
            "SELECT account_no AS Account, name AS Name, phone AS Phone, balance AS Balance, "
            "daily_limit AS 'Daily limit', status AS Status FROM users WHERE role='customer'"
        )
        st.dataframe(users, width="stretch", hide_index=True)
        acc = st.selectbox("Select account", users["Account"].tolist(), format_func=lambda a: f"{a} - {fetch_user(a)['name']}")
        u = fetch_user(acc)
        c1, c2, c3 = st.columns(3)
        if u["status"] == "Active":
            if c1.button("Lock account"):
                execute("UPDATE users SET status='Locked' WHERE account_no=?", (acc,))
                audit(st.session_state.acc, "Account locked", acc)
                notify(acc, "Your account was locked by the bank.")
                st.rerun()
        else:
            if c1.button("Unlock account"):
                execute("UPDATE users SET status='Active', failed_attempts=0 WHERE account_no=?", (acc,))
                audit(st.session_state.acc, "Account unlocked", acc)
                notify(acc, "Your account was unlocked.")
                st.rerun()
        if c2.button("Reset PIN"):
            temp = f"{random.randint(0, 9999):04d}"
            salt = new_salt()
            execute("UPDATE users SET pin_hash=?, salt=?, failed_attempts=0 WHERE account_no=?", (hash_pin(temp, salt), salt, acc))
            audit(st.session_state.acc, "PIN reset", acc)
            st.success(f"Temporary PIN for {u['name']}: **{temp}** (give it to the customer in person).")
        with c3:
            lim = st.number_input("Daily limit (ETB)", min_value=0.0, value=float(u["daily_limit"]), step=5000.0, label_visibility="collapsed")
            if st.button("Save daily limit"):
                execute("UPDATE users SET daily_limit=? WHERE account_no=?", (lim, acc))
                audit(st.session_state.acc, "Daily limit changed", f"{acc} -> {lim}")
                st.success("Limit saved.")
    with tab2:
        st.caption("Digital onboarding: open an account without paper forms.")
        with st.form("newacc", clear_on_submit=True):
            name = st.text_input("Full name")
            phone = st.text_input("Phone number")
            email = st.text_input("Email")
            dep = st.number_input("Initial deposit (ETB)", min_value=0.0, step=100.0)
            go = st.form_submit_button("Open account")
        if go:
            if not name.strip() or not phone.strip():
                st.error("Name and phone number are required.")
            else:
                last = fetch_one("SELECT MAX(account_no) m FROM users")["m"]
                acc = str(int(last) + 1)
                pin = f"{random.randint(0, 9999):04d}"
                salt = new_salt()
                execute(
                    "INSERT INTO users(account_no,name,phone,email,pin_hash,salt,role,balance,created) VALUES(?,?,?,?,?,?,?,?,?)",
                    (acc, name.strip(), phone.strip(), email.strip(), hash_pin(pin, salt), salt, "customer", dep, ts_now()),
                )
                audit(st.session_state.acc, "Account opened", f"{acc} {name}")
                notify(acc, f"Welcome to Oromia Bank! Your account number is {acc}.")
                st.success(f"Account **{acc}** opened for {name}. Temporary PIN: **{pin}**")
    with tab3:
        bl = df("SELECT account_no AS Account, reason AS Reason, added AS Added FROM blacklist")
        if bl.empty:
            st.info("No blacklisted accounts.")
        else:
            st.dataframe(bl, width="stretch", hide_index=True)
        with st.form("bl", clear_on_submit=True):
            a = st.text_input("Account number")
            why = st.text_input("Reason")
            c1, c2 = st.columns(2)
            add = c1.form_submit_button("Add to blacklist")
            rem = c2.form_submit_button("Remove from blacklist")
        if add and a.strip():
            execute("INSERT OR REPLACE INTO blacklist VALUES(?,?,?)", (a.strip(), why, ts_now()))
            audit(st.session_state.acc, "Blacklist add", a.strip())
            st.rerun()
        if rem and a.strip():
            execute("DELETE FROM blacklist WHERE account_no=?", (a.strip(),))
            audit(st.session_state.acc, "Blacklist remove", a.strip())
            st.rerun()


def page_admin_transactions():
    st.header("Transactions and reversals")
    t = tx_frame()
    c1, c2 = st.columns(2)
    sts = c1.multiselect("Status", sorted(t["Status"].unique()), default=sorted(t["Status"].unique()))
    tps = c2.multiselect("Type", sorted(t["Type"].unique()), default=sorted(t["Type"].unique()))
    view = t[t["Status"].isin(sts) & t["Type"].isin(tps)]
    st.dataframe(view.drop(columns=["id"]), width="stretch", hide_index=True)

    st.subheader("Reverse a transfer (dispute handling)")
    cand = t[(t["Status"] == "Completed") & (t["Type"].isin(list(TRANSFER_TYPES)))]["Reference"].tolist()
    if cand:
        ref = st.selectbox("Transaction reference", cand)
        reason = st.text_input("Reason for reversal")
        if st.button("Reverse transaction"):
            if not reason.strip():
                st.error("Enter a reason for the reversal.")
            else:
                ok, msg = reverse_transaction(ref, st.session_state.acc, reason.strip())
                (st.success if ok else st.error)(msg)
                if ok:
                    time.sleep(1)
                    st.rerun()
    else:
        st.info("No completed transfers to reverse.")


def page_admin_fraud():
    st.header("Fraud alerts")
    f = tx_frame("flag != ''")
    if f.empty:
        st.success("No flagged transactions.")
    else:
        st.warning(f"{len(f)} flagged transaction(s) need review.")
        st.dataframe(f.drop(columns=["id", "Note"]), width="stretch", hide_index=True)
    st.subheader("Failed transactions")
    fl = tx_frame("status='Failed'")
    st.dataframe(fl.drop(columns=["id", "Flag"]).rename(columns={"Note": "Reason"}), width="stretch", hide_index=True)
    st.caption("Rules: high amount, many transactions in a short time, large first-time transfer. Change them in Settings.")


def page_admin_reports():
    st.header("Reports")
    t = tx_frame()
    t["Date"] = pd.to_datetime(t["Time"]).dt.date
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("From", value=now_et().date() - timedelta(days=7))
    end = c2.date_input("To", value=now_et().date())
    kind = c3.selectbox("Report", ["All transactions", "Failed transactions", "Flagged transactions", "Revenue (fees)", "Per customer summary"])
    r = t[(t["Date"] >= start) & (t["Date"] <= end)]
    if kind == "Failed transactions":
        r = r[r["Status"] == "Failed"]
    elif kind == "Flagged transactions":
        r = r[r["Flag"] != ""]
    elif kind == "Revenue (fees)":
        r = r[(r["Status"] == "Completed") & (r["Fee"] > 0)]
        st.metric("Total fee revenue", money(r["Fee"].sum()))
    elif kind == "Per customer summary":
        ok = r[(r["Status"] == "Completed") & (r["Type"] != "Own Transfer")]
        sent = ok.groupby("From").agg(Sent=("Amount", "sum"), Transactions=("Reference", "count"))
        recv = ok.groupby("To").agg(Received=("Amount", "sum"))
        r = sent.join(recv, how="outer").fillna(0).reset_index().rename(columns={"index": "Account"})
    out = r.drop(columns=[c for c in ["id", "Date"] if c in r.columns])
    st.dataframe(out, width="stretch", hide_index=True)
    a, b = st.columns(2)
    a.download_button("Export CSV", out.to_csv(index=False), "report.csv", "text/csv")
    b.download_button("Export Excel", to_excel(out), "report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def page_admin_settings():
    st.header("Settings and fees")
    labels = {
        "fee_free_limit": "Free transfer limit (ETB)",
        "fee_flat": "Flat fee above the free limit (ETB)",
        "interbank_fee": "Fee for other-bank and mobile money transfers (ETB)",
        "per_txn_limit": "Maximum amount per transaction (ETB)",
        "fraud_amount": "Flag amounts at or above (ETB)",
        "new_ben_amount": "Flag first-time receiver transfers at or above (ETB)",
        "velocity_count": "Flag after this many transactions...",
        "velocity_minutes": "...within this many minutes",
        "dup_seconds": "Duplicate protection window (seconds)",
        "low_balance": "Low balance alert below (ETB)",
    }
    with st.form("settings"):
        vals = {k: st.number_input(lbl, min_value=0.0, value=get_setting(k)) for k, lbl in labels.items()}
        save = st.form_submit_button("Save settings")
    if save:
        for k, v in vals.items():
            set_setting(k, v)
        audit(st.session_state.acc, "Settings changed", str(vals))
        st.success("Settings saved.")


def page_admin_audit():
    st.header("Audit log")
    a = df("SELECT ts AS Time, actor AS Actor, action AS Action, detail AS Detail FROM audit ORDER BY id DESC LIMIT 500")
    st.dataframe(a, width="stretch", hide_index=True)


# ----------------------------------------------------------------------------
# NEW FEATURES
# ----------------------------------------------------------------------------

# ---- Between my own accounts (current <-> savings) -------------------------
def move_own(acc, to_savings, amount):
    amount = round(float(amount), 2)
    if amount <= 0:
        return False, "Amount must be greater than zero.", None
    ref = gen_ref("OWN")
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        u = c.execute("SELECT * FROM users WHERE account_no=?", (acc,)).fetchone()
        if u is None or u["status"] != "Active":
            c.rollback()
            return False, "Your account is not active.", None
        source = u["balance"] if to_savings else u["savings"]
        if source < amount:
            c.rollback()
            return False, "Insufficient balance in the account you are moving money from.", None
        if to_savings:
            c.execute("UPDATE users SET balance=balance-?, savings=savings+? WHERE account_no=?", (amount, amount, acc))
            frm, to = acc, acc + "-SAV"
        else:
            c.execute("UPDATE users SET savings=savings-?, balance=balance+? WHERE account_no=?", (amount, amount, acc))
            frm, to = acc + "-SAV", acc
        c.execute(
            "INSERT INTO transactions(ref,ts,from_acc,to_acc,amount,fee,type,status,note,flag) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ref, ts_now(), frm, to, amount, 0, "Own Transfer", "Completed", "Between my accounts", ""),
        )
        c.commit()
    except Exception as e:
        c.rollback()
        return False, f"System error, nothing was moved: {e}", None
    finally:
        c.close()
    where = "savings" if to_savings else "current account"
    notify(acc, f"You moved {money(amount)} to your {where}. Ref {ref}.")
    audit(acc, "Own transfer", f"{ref} {money(amount)} to {where}")
    return True, f"Moved {money(amount)} to your {where}.", ref


# ---- EthSwitch / mobile money gateway (SIMULATED) --------------------------
EXT_NAMES = ["Tigist Haile", "Mulugeta Assefa", "Sara Mohammed", "Yonas Girma", "Meron Tesfaye", "Kebede Lemma"]


def log_api(endpoint, request, response, status):
    execute(
        "INSERT INTO api_log(ts,system,endpoint,request,response,status) VALUES(?,?,?,?,?,?)",
        (ts_now(), "EthSwitch (simulated)", endpoint, json.dumps(request), json.dumps(response), status),
    )


def valid_external(bank, acc):
    if not acc.isdigit():
        return "Enter digits only."
    if "mobile money" in bank:
        if len(acc) != 10 or acc[:2] not in ("09", "07"):
            return "Enter a 10-digit phone number starting with 09 or 07."
    elif not 8 <= len(acc) <= 16:
        return "The account number must be 8 to 16 digits."
    return None


def switch_lookup(bank, acc):
    """Simulated account-name lookup. Numbers ending in 99 are 'not found'."""
    err = valid_external(bank, acc)
    if err:
        return False, None, err
    if acc.endswith("99"):
        log_api("POST /v1/accounts/lookup", {"bank": bank, "account": acc}, {"code": "ACCOUNT_NOT_FOUND"}, "FAILED")
        return False, None, "Account not found at this bank."
    name = EXT_NAMES[int(acc) % len(EXT_NAMES)]
    log_api("POST /v1/accounts/lookup", {"bank": bank, "account": acc}, {"code": "OK", "holder": name}, "OK")
    return True, name, ""


def switch_transfer(bank, acc, amount, ref):
    """Simulated transfer. Numbers ending in 00 simulate 'receiving bank unavailable'."""
    req = {"bank": bank, "account": acc, "amount": amount, "reference": ref}
    if acc.endswith("00"):
        log_api("POST /v1/transfers", req, {"code": "BANK_UNAVAILABLE"}, "FAILED")
        return False, None, "The receiving bank is not available right now."
    sref = gen_ref("ETS")
    log_api("POST /v1/transfers", req, {"code": "OK", "switch_ref": sref}, "OK")
    return True, sref, ""


def auto_refund(ref, reason):
    """Return the debited money when the external bank fails after we already debited."""
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM transactions WHERE ref=? AND status='Completed'", (ref,)).fetchone()
        if not row:
            c.rollback()
            return False
        c.execute("UPDATE users SET balance=balance+? WHERE account_no=?", (row["amount"] + row["fee"], row["from_acc"]))
        c.execute("UPDATE transactions SET status='Reversed', note=note||? WHERE ref=?", (f" | Auto-refund: {reason}", ref))
        c.commit()
    except Exception:
        c.rollback()
        return False
    finally:
        c.close()
    notify(row["from_acc"], f"Transfer {ref} failed at the receiving bank. {money(row['amount'] + row['fee'])} was returned to your account.")
    audit(row["from_acc"], "Auto-refund", f"{ref}: {reason}")
    return True


# ---- Scheduled and recurring payments --------------------------------------
FREQUENCIES = ["Once", "Daily", "Weekly", "Monthly"]


def add_months(dt, n=1):
    import calendar

    y = dt.year + (dt.month - 1 + n) // 12
    m = (dt.month - 1 + n) % 12 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))


def next_run_after(dt, freq):
    if freq == "Daily":
        return dt + timedelta(days=1)
    if freq == "Weekly":
        return dt + timedelta(days=7)
    return add_months(dt, 1)


def run_due_schedules():
    """Execute every scheduled payment that is due. Called on each page load and from the admin page."""
    due = df("SELECT * FROM scheduled WHERE status='Active' AND next_run<=? ORDER BY next_run", (ts_now(),))
    done = 0
    for r in due.itertuples():
        if r.frequency == "Once":
            new_next, new_status = r.next_run, "Completed"
        else:
            nxt = next_run_after(datetime.strptime(r.next_run, "%Y-%m-%d %H:%M:%S"), r.frequency)
            while nxt <= now_et():
                nxt = next_run_after(nxt, r.frequency)
            new_next, new_status = nxt.strftime("%Y-%m-%d %H:%M:%S"), "Active"
        c = conn()
        try:  # claim the row first so two sessions never run the same payment twice
            cur = c.execute(
                "UPDATE scheduled SET next_run=?, status=? WHERE id=? AND status='Active' AND next_run=?",
                (new_next, new_status, r.id, r.next_run),
            )
            c.commit()
            claimed = cur.rowcount == 1
        finally:
            c.close()
        if not claimed:
            continue
        ok, msg, ref = process_transaction(r.owner, r.target, r.amount, f"Scheduled: {r.note or r.ttype}", r.ttype)
        result = f"{ts_now()} - " + ("Paid" if ok else f"Failed: {msg}")
        if not ok and r.frequency == "Once":
            execute("UPDATE scheduled SET last_result=?, runs=runs+1, status='Failed' WHERE id=?", (result, r.id))
        else:
            execute("UPDATE scheduled SET last_result=?, runs=runs+1 WHERE id=?", (result, r.id))
        audit(r.owner, "Scheduled payment run", f"#{r.id} {money(r.amount)} to {r.target}: {'OK ' + ref if ok else msg}")
        done += 1
    return done


# ---- Registered devices ------------------------------------------------------
MAX_DEVICES = 3


def device_info():
    try:
        h = st.context.headers
        ua = h.get("User-Agent", "") or ""
        lang = h.get("Accept-Language", "") or ""
    except Exception:
        ua, lang = "", ""
    if not ua:
        return "unknown", "Unknown device"
    os_name = next((n for k, n in [("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                                   ("Mac OS", "macOS"), ("Linux", "Linux")] if k in ua), "Unknown OS")
    browser = next((n for k, n in [("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                                   ("Safari/", "Safari")] if k in ua), "Browser")
    return hashlib.sha256((ua + lang).encode()).hexdigest()[:16], f"{browser} on {os_name}"


def register_device(acc):
    fp, label = device_info()
    existing = df("SELECT fingerprint FROM devices WHERE account_no=?", (acc,))
    if fp in existing["fingerprint"].values:
        execute("UPDATE devices SET last_seen=? WHERE account_no=? AND fingerprint=?", (ts_now(), acc, fp))
        return
    execute(
        "INSERT INTO devices(account_no,fingerprint,label,first_seen,last_seen) VALUES(?,?,?,?,?)",
        (acc, fp, label, ts_now(), ts_now()),
    )
    extra = len(existing) + 1 - MAX_DEVICES
    if extra > 0:  # keep at most MAX_DEVICES: drop the least recently used ones
        execute(
            "DELETE FROM devices WHERE id IN (SELECT id FROM devices WHERE account_no=? ORDER BY last_seen ASC LIMIT ?)",
            (acc, extra),
        )
    if len(existing) > 0:
        notify(acc, f"Security alert: a new device ({label}) signed in to your account. "
                    "If this was not you, change your PIN and contact the bank.", "Email")
        audit(acc, "New device", label)


# ---- Push-style notifications ----------------------------------------------
def show_push_notifications(acc):
    """Pop up unread alerts as toast messages (in-app push)."""
    new = df("SELECT id, message FROM notifications WHERE account_no=? AND seen=0 ORDER BY id", (acc,))
    if new.empty:
        return
    for m in new["message"].tail(3):
        st.toast(m, icon="🔔")
    execute("UPDATE notifications SET seen=1 WHERE account_no=? AND seen=0", (acc,))


# ---- QR codes -----------------------------------------------------------------
def make_qr_payload(acc, amount, name):
    return f"ORB|{acc}|{float(amount):.2f}|{name.replace('|', ' ')}"


def parse_qr(text):
    parts = text.strip().split("|")
    if len(parts) < 3 or parts[0] != "ORB" or not parts[1].isdigit():
        return None
    try:
        amt = float(parts[2])
    except ValueError:
        return None
    return parts[1], max(amt, 0.0), (parts[3] if len(parts) > 3 else "")


def make_qr_png(payload):
    import qrcode

    qr = qrcode.QRCode(box_size=8, border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1F2433", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def decode_qr(file_bytes):
    import cv2
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    arr = np.array(img)[:, :, ::-1].copy()
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)
    return data or None


# ---- Backup and restore -------------------------------------------------------
BACKUP_DIR = "backups"


def make_backup_bytes():
    src = conn()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    try:
        dst = sqlite3.connect(tmp.name)
        src.backup(dst)
        dst.close()
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        src.close()
        os.remove(tmp.name)


def restore_from_file(path):
    try:
        src = sqlite3.connect(path)
        try:
            names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"users", "transactions", "settings"} <= names:
                return False, "This file is not an Oromia Bank backup."
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False, "The backup file is damaged."
            if src.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 0:
                return False, "The backup has no admin account."
            dst = sqlite3.connect(DB_PATH, timeout=30)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except sqlite3.Error as e:
        return False, f"This file could not be read as a backup: {e}"
    return True, ""


# ----------------------------------------------------------------------------
# New customer pages
# ----------------------------------------------------------------------------
def page_own():
    u = me()
    n = st.session_state.form_n
    st.header(tr("m_own"))
    show_last_receipt()
    c1, c2 = st.columns(2)
    c1.metric("Current account", money(u["balance"]))
    c2.metric(tr("savings_balance"), money(u["savings"]))
    direction = st.radio("Move money", ["Current account to savings", "Savings to current account"],
                         horizontal=True, key=f"dir_{n}")
    amount = st.number_input(tr("amount"), min_value=0.0, step=100.0, format="%.2f", key=f"oamt_{n}")
    pin = st.text_input(tr("confirm_pin"), type="password", max_chars=6, key=f"opin_{n}")
    st.caption("Moving money between your own accounts is free and has no daily limit.")
    if st.button("Move money"):
        if amount <= 0:
            st.error("Enter an amount greater than zero.")
        else:
            ok, msg = check_pin(u["account_no"], pin)
            if not ok:
                st.error(msg)
            else:
                ok, msg, ref = move_own(u["account_no"], direction.startswith("Current"), amount)
                if ok:
                    st.session_state.last_ref = ref
                    st.session_state.last_msg = f"{msg} Reference: {ref}"
                    st.rerun()
                else:
                    st.error(msg)


def page_other_bank():
    u = me()
    n = st.session_state.form_n
    st.header(tr("m_other"))
    show_last_receipt()
    fee = get_setting("interbank_fee")
    st.caption(f"Balance: {money(u['balance'])}   |   Fee: {money(fee)} per transfer")
    st.info("Transfers to other banks and mobile money wallets go through the EthSwitch gateway. "
            "In this prototype the gateway is simulated.")
    bank = st.selectbox("Receiving bank or wallet", EXTERNAL_BANKS, key=f"xb_{n}")
    mobile = "mobile money" in bank
    acc = st.text_input("Phone number" if mobile else "Account number", key=f"xacc_{n}").strip()
    if st.button("Check account", key=f"xchk_{n}"):
        ok, name, msg = switch_lookup(bank, acc)
        if ok:
            st.success(f"Account holder: {name}")
        else:
            st.error(msg)
    amount = st.number_input(tr("amount"), min_value=0.0, step=100.0, format="%.2f", key=f"xamt_{n}")
    note = st.text_input(tr("note_opt"), max_chars=60, key=f"xnote_{n}")
    st.caption(f"Total to be debited: {money(amount + fee if amount > 0 else 0)}")
    pin = st.text_input(tr("confirm_pin"), type="password", max_chars=6, key=f"xpin_{n}")
    if st.button("Send to other bank"):
        if amount <= 0:
            st.error("Enter an amount greater than zero.")
        else:
            found, name, msg = switch_lookup(bank, acc)
            if not found:
                st.error(msg)
            else:
                ok, msg = check_pin(u["account_no"], pin)
                if not ok:
                    st.error(msg)
                else:
                    ok, msg, ref = process_transaction(u["account_no"], f"{bank} - {acc}", amount,
                                                       f"To {name}. {note}".strip(), "Other Bank")
                    if not ok:
                        st.error(msg)
                    else:
                        sok, sref, smsg = switch_transfer(bank, acc, amount, ref)
                        if sok:
                            execute("UPDATE transactions SET note=note||? WHERE ref=?", (f" | Switch ref {sref}", ref))
                            st.session_state.last_ref = ref
                            st.session_state.last_msg = f"{msg} Switch reference: {sref}"
                            st.rerun()
                        else:
                            auto_refund(ref, smsg)
                            st.error(f"{smsg} Your money was returned to your account.")


def page_qr():
    u = me()
    n = st.session_state.form_n
    st.header(tr("m_qr"))
    show_last_receipt()
    tab1, tab2 = st.tabs(["My QR code", "Scan and pay"])
    with tab1:
        st.caption("Show this code to the person who wants to pay you. They scan it from the Scan and pay tab.")
        req = st.number_input("Amount to request (0 lets the payer choose)", min_value=0.0, step=100.0,
                              format="%.2f", key=f"qreq_{n}")
        png = make_qr_png(make_qr_payload(u["account_no"], req, u["name"]))
        st.image(png, width=260, caption=f"{u['name']} - {u['account_no']}" + (f" - {money(req)}" if req else ""))
        st.download_button("Download QR code (PNG)", png, file_name="my_oromia_qr.png", mime="image/png")
    with tab2:
        raw = None
        if st.toggle("Use the camera", key=f"cam_{n}"):
            pic = st.camera_input("Point the camera at the QR code", key=f"campic_{n}")
            if pic:
                raw = decode_qr(pic.getvalue())
                if raw is None:
                    st.warning("No QR code found in the photo. Hold the phone steady and try again.")
        else:
            up = st.file_uploader("Upload a photo or screenshot of the QR code", type=["png", "jpg", "jpeg"], key=f"qrup_{n}")
            if up:
                raw = decode_qr(up.getvalue())
                if raw is None:
                    st.warning("No QR code found in this image.")
            txt = st.text_input("Or paste the QR code text", key=f"qrtxt_{n}")
            if not raw and txt.strip():
                raw = txt.strip()
        if raw:
            parsed = parse_qr(raw)
            if not parsed:
                st.error("This is not an Oromia Bank QR code.")
            else:
                acc, qamt, qname = parsed
                r = fetch_user(acc)
                if not r or r["role"] != "customer" or acc == u["account_no"]:
                    st.error("This QR code does not belong to a valid receiver account.")
                else:
                    st.success(f"Pay to: {r['name']} ({acc})")
                    amount = st.number_input(tr("amount"), min_value=0.0, value=float(qamt), step=100.0,
                                             format="%.2f", disabled=qamt > 0, key=f"qamt_{n}_{acc}_{qamt}")
                    st.caption(f"Fee: {money(compute_fee(amount))}")
                    pin = st.text_input(tr("confirm_pin"), type="password", max_chars=6, key=f"qpin_{n}")
                    if st.button("Pay with QR"):
                        if amount <= 0:
                            st.error("Enter an amount greater than zero.")
                        else:
                            ok, msg = check_pin(u["account_no"], pin)
                            if not ok:
                                st.error(msg)
                            else:
                                ok, msg, ref = process_transaction(u["account_no"], acc, amount, "QR payment", "QR Payment")
                                if ok:
                                    st.session_state.last_ref = ref
                                    st.session_state.last_msg = f"{msg} Reference: {ref}"
                                    st.rerun()
                                else:
                                    st.error(msg)


def page_scheduled():
    u = me()
    n = st.session_state.form_n
    st.header(tr("m_sched"))
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    tab1, tab2 = st.tabs(["My scheduled payments", "New scheduled payment"])
    with tab1:
        s = df(
            "SELECT id, ttype AS Type, target AS 'To', amount AS Amount, frequency AS Frequency, "
            "next_run AS 'Next run', status AS Status, last_result AS 'Last result' "
            "FROM scheduled WHERE owner=? ORDER BY id DESC",
            (u["account_no"],),
        )
        if s.empty:
            st.info("You have no scheduled payments. Create one in the next tab.")
        else:
            st.dataframe(s.drop(columns=["id"]), width="stretch", hide_index=True)
            active = s[s["Status"] == "Active"]
            if not active.empty:
                pick = st.selectbox(
                    "Cancel a payment", active["id"].tolist(),
                    format_func=lambda i: f"{active[active['id'] == i].iloc[0]['To']} - "
                                          f"{money(active[active['id'] == i].iloc[0]['Amount'])} "
                                          f"({active[active['id'] == i].iloc[0]['Frequency']})",
                )
                if st.button("Cancel payment"):
                    execute("UPDATE scheduled SET status='Cancelled' WHERE id=? AND owner=?", (int(pick), u["account_no"]))
                    audit(u["account_no"], "Scheduled payment cancelled", f"#{pick}")
                    st.rerun()
    with tab2:
        kind = st.radio("Payment type", ["Transfer to an account", "Pay a bill"], horizontal=True, key=f"sk_{n}")
        valid = False
        if kind == "Transfer to an account":
            target = st.text_input(tr("receiver_acc"), key=f"sacc_{n}").strip()
            ttype, note = "Transfer", ""
            if target:
                r = fetch_user(target)
                if r and r["role"] == "customer" and target != u["account_no"]:
                    st.success(f"Account holder: {r['name']}")
                    valid = True
                else:
                    st.warning("No customer account found with this number.")
        else:
            target = st.selectbox("Service", list(BILLERS.keys()), key=f"sbill_{n}")
            ttype, label = BILLERS[target]
            cust_no = st.text_input(label, key=f"scust_{n}").strip()
            note = f"{label}: {cust_no}"
            valid = bool(cust_no)
        amount = st.number_input(tr("amount"), min_value=0.0, step=100.0, format="%.2f", key=f"samt_{n}")
        freq = st.selectbox("How often", FREQUENCIES, key=f"sfreq_{n}")
        c1, c2 = st.columns(2)
        day = c1.date_input("First payment date", value=now_et().date(), min_value=now_et().date(), key=f"sday_{n}")
        default_time = st.session_state.setdefault(
            f"sdt_{n}", (now_et() + timedelta(minutes=5)).time().replace(second=0, microsecond=0))
        tm = c2.time_input("Time (Ethiopia)", value=default_time, key=f"stime_{n}")
        pin = st.text_input(tr("confirm_pin"), type="password", max_chars=6, key=f"spin_{n}")
        if st.button("Schedule payment"):
            when = datetime.combine(day, tm)
            if not valid:
                st.error("Enter valid payment details first.")
            elif amount <= 0:
                st.error("Enter an amount greater than zero.")
            elif when < now_et() - timedelta(minutes=1):
                st.error("The first payment time is in the past. Choose a later time.")
            else:
                ok, msg = check_pin(u["account_no"], pin)
                if not ok:
                    st.error(msg)
                else:
                    execute(
                        "INSERT INTO scheduled(owner,ttype,target,amount,note,frequency,next_run,status,last_result,runs,created) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (u["account_no"], ttype, target, amount, note, freq, when.strftime("%Y-%m-%d %H:%M:%S"),
                         "Active", "", 0, ts_now()),
                    )
                    audit(u["account_no"], "Scheduled payment created", f"{money(amount)} to {target} {freq}")
                    notify(u["account_no"], f"Scheduled payment of {money(amount)} to {target} ({freq}) starts {when:%Y-%m-%d %H:%M}.")
                    st.session_state.flash = f"Scheduled: {money(amount)} to {target}, {freq.lower()}, first on {when:%Y-%m-%d %H:%M}."
                    st.session_state.form_n += 1
                    st.rerun()


# ----------------------------------------------------------------------------
# New admin pages
# ----------------------------------------------------------------------------
def page_admin_scheduled():
    st.header("Scheduled payments")
    s = df(
        "SELECT id, owner AS Customer, ttype AS Type, target AS 'To', amount AS Amount, frequency AS Frequency, "
        "next_run AS 'Next run', status AS Status, runs AS Runs, last_result AS 'Last result' FROM scheduled ORDER BY id DESC"
    )
    if s.empty:
        st.info("No scheduled payments yet.")
    else:
        st.dataframe(s.drop(columns=["id"]), width="stretch", hide_index=True)
    st.caption("Due payments run automatically whenever anyone opens the app. You can also run them now.")
    if st.button("Run due payments now"):
        st.success(f"{run_due_schedules()} payment(s) processed.")
        time.sleep(1)
        st.rerun()


def page_admin_api():
    st.header("Integrations (API log)")
    st.warning("The EthSwitch gateway is simulated in this prototype. A real connection needs an agreement "
               "with EthSwitch and production API credentials.")
    st.markdown(
        "Test numbers for other-bank transfers: an account ending in **99** is not found, "
        "an account ending in **00** simulates an unavailable bank and triggers an automatic refund."
    )
    log = df("SELECT ts AS Time, system AS System, endpoint AS Endpoint, request AS Request, response AS Response, "
             "status AS Status FROM api_log ORDER BY id DESC LIMIT 200")
    if log.empty:
        st.info("No gateway calls yet. Send a transfer to another bank as a customer.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Gateway calls", len(log))
        c2.metric("Failed calls", int((log["Status"] == "FAILED").sum()))
        st.dataframe(log, width="stretch", hide_index=True)


def page_admin_backup():
    st.header("Backup and restore")
    st.caption("A backup contains every account, transaction, setting and log. Keep copies somewhere safe.")
    stamp = now_et().strftime("%Y%m%d_%H%M%S")
    st.subheader("Download a backup")
    st.download_button("Download backup (.db)", make_backup_bytes(), file_name=f"oromia_bank_backup_{stamp}.db",
                       mime="application/octet-stream")

    st.subheader("Snapshots on the server")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if st.button("Save a snapshot now"):
        path = os.path.join(BACKUP_DIR, f"snapshot_{stamp}.db")
        with open(path, "wb") as f:
            f.write(make_backup_bytes())
        for old in sorted(glob.glob(os.path.join(BACKUP_DIR, "snapshot_*.db")))[:-10]:
            os.remove(old)  # keep the 10 newest
        audit(st.session_state.acc, "Snapshot saved", os.path.basename(path))
        st.success(f"Snapshot saved: {os.path.basename(path)}")
    snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "snapshot_*.db")), reverse=True)
    if snaps:
        pick = st.selectbox("Snapshot", snaps, format_func=os.path.basename)
        sure = st.checkbox("I understand this replaces all current data", key="sure_snap")
        if st.button("Restore this snapshot"):
            if not sure:
                st.error("Tick the box to confirm the restore.")
            else:
                ok, msg = restore_from_file(pick)
                if ok:
                    logout("Snapshot restored. Please sign in again.")
                st.error(msg)
    else:
        st.info("No snapshots saved yet.")

    st.subheader("Restore from a backup file")
    up = st.file_uploader("Choose a backup (.db) file", type=["db"])
    sure2 = st.checkbox("I understand this replaces all current data", key="sure_up")
    if st.button("Restore uploaded backup"):
        if up is None:
            st.error("Choose a backup file first.")
        elif not sure2:
            st.error("Tick the box to confirm the restore.")
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
            tmp.write(up.getvalue())
            tmp.close()
            ok, msg = restore_from_file(tmp.name)
            os.remove(tmp.name)
            if ok:
                logout("Backup restored. Please sign in again.")
            st.error(msg)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
init_db()

if not st.session_state.get("acc"):
    login_page()
    st.stop()

if time.time() - st.session_state.get("last_active", time.time()) > SESSION_TIMEOUT_SEC:
    logout("You were signed out after 10 minutes of inactivity.")
st.session_state.last_active = time.time()

if me() is None:
    logout("Your session is no longer valid. Please sign in again.")

run_due_schedules()
if st.session_state.role != "admin":
    show_push_notifications(st.session_state.acc)

CUSTOMER_PAGES = {
    "m_dashboard": page_dashboard,
    "m_send": page_transfer,
    "m_other": page_other_bank,
    "m_own": page_own,
    "m_qr": page_qr,
    "m_bills": page_bills,
    "m_sched": page_scheduled,
    "m_receivers": page_beneficiaries,
    "m_history": page_history,
    "m_notif": page_notifications,
    "m_profile": page_profile,
}
ADMIN_PAGES = {
    "Live monitor": page_admin_dashboard,
    "Customers": page_admin_customers,
    "Transactions and reversals": page_admin_transactions,
    "Scheduled payments": page_admin_scheduled,
    "Fraud alerts": page_admin_fraud,
    "Reports": page_admin_reports,
    "Integrations (API log)": page_admin_api,
    "Backup and restore": page_admin_backup,
    "Settings and fees": page_admin_settings,
    "Audit log": page_admin_audit,
}
pages = ADMIN_PAGES if st.session_state.role == "admin" else CUSTOMER_PAGES

with st.sidebar:
    if os.path.exists(LOGO):
        st.image(LOGO, width="stretch")
    user = me()
    st.markdown(f"**{user['name']}**")
    st.caption("Bank administrator" if user["role"] == "admin" else f"{tr('account')} {user['account_no']}")
    if user["role"] != "admin":
        lang_selector("lang_sidebar")
    keys = list(pages.keys())
    labels = [tr(k) for k in keys]
    current = st.session_state.get("page_key")
    idx = keys.index(current) if current in keys else 0
    chosen = st.radio("Menu", labels, index=idx, label_visibility="collapsed")
    page = keys[labels.index(chosen)]
    if st.session_state.get("page_key") not in (None, page):
        st.session_state.pop("last_ref", None)  # leaving a page closes its receipt screen
    st.session_state["page_key"] = page  # keeps you on the same page when the language changes
    st.divider()
    if st.button(tr("sign_out"), width="stretch"):
        audit(user["account_no"], "Logout")
        logout()

pages[page]()
