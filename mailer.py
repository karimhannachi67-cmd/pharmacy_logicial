"""إرسال الإيميلات عبر Brevo (ملف مستقل عن main.py).

الإعدادات تتقرا من Environment Variables في Render، وإلا تاخذ القيم الافتراضية هنا.
- MAIL_SENDER : الإيميل لي يبعث منو (لازم يكون Verified في Brevo > Senders)
- BREVO_KEY   : المفتاح
- BREVO_LOGIN : (اختياري) لوجين SMTP تع Brevo، يشبه xxxx@smtp-brevo.com.
                لكان محطوط يبعث عبر SMTP (بورت 2525)، وإلا يبعث عبر REST API.
"""
import os, json, smtplib, ssl, urllib.request, urllib.error
from email.message import EmailMessage

SENDER = os.environ.get("MAIL_SENDER", "pharmalink132@gmail.com")
SENDER_NAME = "PharmaLink"
BREVO_KEY = os.environ.get("BREVO_KEY", "xsmtpsib-327ff7d56bbf9ff5861a6c0cb55a7da397aa8368e6d8062408032544935e9a31-LHpLNTRI1dLR1tH7")
BREVO_LOGIN = os.environ.get("BREVO_LOGIN", "")


def _send_api(to, subject, text):
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email", method="POST",
        data=json.dumps({"sender": {"name": SENDER_NAME, "email": SENDER}, "to": [{"email": to}],
                         "subject": subject, "textContent": text}).encode(),
        headers={"api-key": BREVO_KEY, "Content-Type": "application/json", "accept": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=12).read()
    except urllib.error.HTTPError as e:   # نبينو السبب في Logs
        error_body = e.read().decode(errors='ignore')
        print(f"BREVO_ERROR_DETAIL: Code={e.code}, Message={error_body}")
        raise RuntimeError(f"Brevo API {e.code}: {error_body[:300]}")
    except Exception as ex:
        print(f"GENERAL_MAIL_ERROR: {ex}")
        raise ex


def _send_smtp(to, subject, text):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = f"{SENDER_NAME} <{SENDER}>", to, subject
    m.set_content(text)
    with smtplib.SMTP("smtp-relay.brevo.com", 2525, timeout=12) as c:
        c.starttls(context=ssl.create_default_context())
        c.login(BREVO_LOGIN, BREVO_KEY)
        c.send_message(m)


def send_mail(to, subject, text):
    (_send_smtp if BREVO_LOGIN else _send_api)(to, subject, text)
