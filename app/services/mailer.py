"""Optional SMTP email delivery. In-app notifications still work without SMTP."""
import smtplib
from email.message import EmailMessage
from flask import current_app


def send_email(recipient, subject, body):
    config = current_app.config
    server = config.get("MAIL_SERVER")
    sender = config.get("MAIL_DEFAULT_SENDER") or config.get("MAIL_USERNAME")
    if not server or not sender or not recipient:
        current_app.logger.info("Email not sent because SMTP is not configured (subject=%s).", subject)
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)
    try:
        with smtplib.SMTP(server, int(config.get("MAIL_PORT", 587)), timeout=10) as smtp:
            if config.get("MAIL_USE_TLS", True):
                smtp.starttls()
            username = config.get("MAIL_USERNAME")
            password = config.get("MAIL_PASSWORD")
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return True
    except Exception:
        current_app.logger.exception("SMTP email delivery failed")
        return False
