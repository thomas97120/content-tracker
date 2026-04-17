"""
mailer.py — Envoi d'emails via SMTP
Variables d'env : SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, APP_URL
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
APP_URL   = os.environ.get("APP_URL", "http://localhost:5000")


def send_email(to: str, subject: str, html: str) -> bool:
    if not SMTP_USER or not SMTP_PASS:
        print(f"[MAILER] SMTP non configuré — mail simulé pour {to}")
        print(f"[MAILER] Sujet : {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = to
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to, msg.as_string())
        print(f"[MAILER] Mail envoyé → {to}")
        return True
    except Exception as e:
        print(f"[MAILER] Erreur : {e}")
        return False


def send_verification(to: str, token: str) -> bool:
    url  = f"{APP_URL}/api/auth/verify/{token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px">
      <h2 style="color:#7c6aff">📊 Content Tracker</h2>
      <h3>Confirme ton adresse email</h3>
      <p>Clique sur le bouton pour activer ton compte :</p>
      <a href="{url}"
         style="display:inline-block;background:linear-gradient(135deg,#7c6aff,#ff6a9b);
                color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;
                font-weight:600;margin:16px 0">
        ✅ Confirmer mon email
      </a>
      <p style="color:#888;font-size:13px;margin-top:24px">
        Lien valable <strong>24 heures</strong>.<br>
        Si tu n'as pas créé de compte, ignore ce mail.
      </p>
    </div>"""
    return send_email(to, "Content Tracker — Confirme ton email", html)


def send_reset(to: str, token: str) -> bool:
    url  = f"{APP_URL}/api/auth/reset/{token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px">
      <h2 style="color:#7c6aff">📊 Content Tracker</h2>
      <h3>Réinitialisation de mot de passe</h3>
      <p>Clique pour choisir un nouveau mot de passe :</p>
      <a href="{url}"
         style="display:inline-block;background:linear-gradient(135deg,#ff6a9b,#7c6aff);
                color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;
                font-weight:600;margin:16px 0">
        🔑 Réinitialiser mon mot de passe
      </a>
      <p style="color:#888;font-size:13px;margin-top:24px">
        Lien valable <strong>1 heure</strong>.<br>
        Si tu n'as pas demandé ça, ignore ce mail — ton compte est en sécurité.
      </p>
    </div>"""
    return send_email(to, "Content Tracker — Réinitialisation mot de passe", html)
