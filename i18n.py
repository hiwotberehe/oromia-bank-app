"""Translations for the customer screens: English, Amharic, Afaan Oromo.

Add a new text by adding a key here and calling tr("key") in app.py.
Missing translations fall back to English.
"""

LANGS = {"English": "en", "አማርኛ": "am", "Afaan Oromoo": "om"}

TR = {
    # ---- login ----
    "portal": {"en": "Digital Banking Portal", "am": "ዲጂታል ባንኪንግ", "om": "Baankii Dijitaalaa"},
    "acc_no": {"en": "Account number", "am": "የሂሳብ ቁጥር", "om": "Lakkoofsa herregaa"},
    "pin": {"en": "PIN", "am": "ፒን", "om": "PIN"},
    "continue": {"en": "Continue", "am": "ቀጥል", "om": "Itti fufi"},
    "back": {"en": "Back", "am": "ተመለስ", "om": "Duubatti"},
    "verify": {"en": "Verify and sign in", "am": "አረጋግጥና ግባ", "om": "Mirkaneessiitii seeni"},
    "enter_code": {"en": "Enter the 6-digit code", "am": "ባለ 6 አሃዝ ኮዱን ያስገቡ", "om": "Koodii lakkoofsa 6 galchi"},
    "otp_sent": {
        "en": "A 6-digit code was sent by SMS to ******{p}.",
        "am": "ባለ 6 አሃዝ ኮድ በኤስኤምኤስ ወደ ******{p} ተልኳል።",
        "om": "Koodiin lakkoofsa 6 ergaa SMS'n gara ******{p} ergameera.",
    },
    "demo_accounts": {"en": "Demo accounts", "am": "የሙከራ ሂሳቦች", "om": "Herregoota shaakalaa"},
    "sign_out": {"en": "Sign out", "am": "ውጣ", "om": "Ba'i"},
    # ---- menu (customer) ----
    "m_dashboard": {"en": "Dashboard", "am": "ዳሽቦርድ", "om": "Daashboordii"},
    "m_send": {"en": "Send money", "am": "ገንዘብ ላክ", "om": "Maallaqa ergi"},
    "m_other": {"en": "Other banks and wallets", "am": "ወደ ሌላ ባንክ እና ዋሌት", "om": "Baankiiwwan fi wallet biroo"},
    "m_own": {"en": "My accounts", "am": "የእኔ ሂሳቦች", "om": "Herregoota koo"},
    "m_qr": {"en": "QR payment", "am": "QR ክፍያ", "om": "Kaffaltii QR"},
    "m_bills": {"en": "Pay bills and airtime", "am": "ሂሳብ እና የአየር ሰዓት ክፈል", "om": "Kaffaltii fi airtime"},
    "m_sched": {"en": "Scheduled payments", "am": "የታቀዱ ክፍያዎች", "om": "Kaffaltiiwwan karoorfaman"},
    "m_receivers": {"en": "Saved receivers", "am": "የተቀመጡ ተቀባዮች", "om": "Fudhattoota olkaa'aman"},
    "m_history": {"en": "Transaction history", "am": "የግብይት ታሪክ", "om": "Seenaa daldalaa"},
    "m_notif": {"en": "Notifications", "am": "ማሳወቂያዎች", "om": "Beeksisoota"},
    "m_profile": {"en": "Profile and security", "am": "መገለጫ እና ደህንነት", "om": "Profaayilii fi nageenya"},
    # ---- dashboard ----
    "welcome": {"en": "Welcome", "am": "እንኳን ደህና መጡ", "om": "Baga nagaan dhuftan"},
    "avail_balance": {"en": "Available balance", "am": "ያለዎት ቀሪ ሂሳብ", "om": "Balaansii jiru"},
    "savings_balance": {"en": "Savings balance", "am": "የቁጠባ ሂሳብ", "om": "Herrega qusannoo"},
    "account": {"en": "Account", "am": "ሂሳብ ቁጥር", "om": "Herrega"},
    "spent_today": {"en": "Spent today", "am": "ዛሬ ያወጡት", "om": "Har'a kan baasan"},
    "daily_limit": {"en": "Daily limit", "am": "ዕለታዊ ገደብ", "om": "Daangaa guyyaa"},
    "remaining_today": {"en": "Remaining today", "am": "ዛሬ የቀረዎት", "om": "Har'a kan hafe"},
    "recent": {"en": "Recent transactions", "am": "የቅርብ ጊዜ ግብይቶች", "om": "Daldalawwan dhiyoo"},
    # ---- send money / bills ----
    "send_to": {"en": "Send to", "am": "ተቀባይ", "om": "Kan fudhatu"},
    "receiver_acc": {"en": "Receiver account number", "am": "የተቀባይ ሂሳብ ቁጥር", "om": "Lakkoofsa herrega fudhataa"},
    "amount": {"en": "Amount (ETB)", "am": "መጠን (ብር)", "om": "Hammaa (ETB)"},
    "note_opt": {"en": "Note (optional)", "am": "ማስታወሻ (አማራጭ)", "om": "Yaadannoo (yoo barbaade)"},
    "confirm_pin": {"en": "Confirm with your PIN", "am": "በፒን ቁጥርዎ ያረጋግጡ", "om": "PIN keessaniin mirkaneessaa"},
    "send_btn": {"en": "Send money", "am": "ላክ", "om": "Ergi"},
    "pay_now": {"en": "Pay now", "am": "አሁን ክፈል", "om": "Amma kaffali"},
    "dl_receipt": {"en": "Download receipt (PDF)", "am": "ደረሰኝ አውርድ (PDF)", "om": "Ragaa kaffaltii buusi (PDF)"},
    "another": {"en": "Make another payment", "am": "ሌላ ክፍያ ፈጽም", "om": "Kaffaltii biraa raawwadhu"},
}
