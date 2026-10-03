# Oromia Bank - Real-Time Transaction System (Prototype)

A Streamlit prototype that digitalizes core bank services: instant transfers, QR payment,
scheduled payments, other-bank transfers (simulated EthSwitch), notifications, fraud alerts
and an admin monitoring dashboard. Customer screens are available in English, Amharic and
Afaan Oromo.

## Run on your computer

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501

## Deploy on Streamlit Community Cloud (free)

1. Create a GitHub account and a new repository (e.g. `oromia-bank-app`).
2. Upload ALL files from this folder (keep `assets/`, `.streamlit/` and `i18n.py`).
3. Go to https://share.streamlit.io and sign in with GitHub.
4. Click **Create app**, choose your repository, branch `main`, main file `app.py`.
5. Click **Deploy**. You get a public link to show your supervisor.

Note: the SQLite database resets when the cloud app restarts. Demo accounts and sample
data are recreated automatically. Use Admin > Backup and restore to save your data.

## Demo accounts

| Role       | Account    | PIN  |
|------------|------------|------|
| Customer   | 1000000101 | 1234 |
| Customer   | 1000000102 | 1234 |
| Customer   | 1000000103 | 1234 |
| Customer   | 1000000104 | 1234 |
| Bank admin | 1000000001 | 9999 |

Login uses PIN + OTP. There is no real SMS gateway, so the OTP is shown on screen.

## Customer features

- Login with PIN + OTP, lock after 3 wrong PINs, auto logout after 10 minutes
- Live balance, savings balance, daily limit bar, recent transactions
- Send money to another Oromia Bank customer (name shown before sending)
- Other banks and mobile money (Telebirr, M-Birr) through a simulated EthSwitch gateway,
  with automatic refund if the receiving bank fails
- My accounts: move money between current and savings accounts
- QR payment: show your own QR code, or scan / upload / paste a QR code to pay
- Scheduled and recurring payments (once, daily, weekly, monthly) for transfers and bills
- Bill payment and airtime, saved receivers
- PDF receipts, CSV statement export, transaction history
- Notifications: SMS and email inbox, pop-up (push-style) alerts, failed transaction alerts,
  low balance alerts, new device alerts
- Registered devices (maximum 3) and PIN change
- Languages: English, Amharic, Afaan Oromo

## Admin features

Live monitor with charts, open new accounts, lock/unlock, PIN reset, daily limits, blacklist,
transaction reversal, scheduled payments overview, fraud alerts, failed transaction report,
reports (CSV/Excel), integrations/API log, backup and restore (download, server snapshots,
upload), fees and rules settings, audit log.

## Test numbers for the simulated gateway

- Other-bank account ending in `99`: account not found
- Other-bank account ending in `00`: receiving bank unavailable (money is refunded automatically)
- Mobile money numbers must be 10 digits starting with 09 or 07

## Not included (future work)

- Fingerprint / face login: needs a mobile app with biometric hardware
- Real EthSwitch / mobile money connection: needs an agreement and production credentials
- Real SMS and phone push notifications: needs an SMS gateway and a mobile app
- Production database (PostgreSQL), HTTPS hardening and an official security audit
- The translations cover menus and the main screens; system messages are in English.
  Please have a native speaker review the Amharic and Afaan Oromo text before presenting.

## Project files

- `app.py` - the application
- `i18n.py` - Amharic / Afaan Oromo / English texts (edit here to improve translations)
- `assets/logo.png` - Oromia Bank logo
- `.streamlit/config.toml` - colors/theme
- `requirements.txt` - Python packages
