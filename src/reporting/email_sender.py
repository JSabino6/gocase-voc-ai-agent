from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

from src.config import AppSettings

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def parse_recipient_emails(raw_input: str) -> list[str]:
    candidates = [item.strip() for item in raw_input.replace(";", ",").split(",")]
    recipients = [item for item in candidates if item]

    invalid = [email for email in recipients if not EMAIL_PATTERN.match(email)]
    if invalid:
        raise ValueError(f"Emails invalidos: {', '.join(invalid)}")

    deduplicated = list(dict.fromkeys(recipients))
    return deduplicated


def _validate_smtp_settings(settings: AppSettings) -> None:
    smtp_host = getattr(settings, "smtp_host", "")
    smtp_port = int(getattr(settings, "smtp_port", 0) or 0)
    smtp_sender_email = getattr(settings, "smtp_sender_email", "")

    if not smtp_host:
        raise ValueError("SMTP_HOST nao configurado.")
    if smtp_port <= 0:
        raise ValueError("SMTP_PORT invalido.")
    if not smtp_sender_email:
        raise ValueError("SMTP_SENDER_EMAIL nao configurado.")


def send_pdf_report_via_email(
    *,
    recipients: list[str],
    subject: str,
    body: str,
    pdf_path: Path,
    settings: AppSettings,
) -> None:
    _validate_smtp_settings(settings)

    if not recipients:
        raise ValueError("Informe pelo menos um destinatario.")

    if not pdf_path.exists():
        raise FileNotFoundError(f"Arquivo PDF nao encontrado: {pdf_path}")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = getattr(settings, "smtp_sender_email", "")
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with pdf_path.open("rb") as handler:
        pdf_bytes = handler.read()
        message.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_path.name,
        )

    smtp_host = str(getattr(settings, "smtp_host", "")).strip()
    smtp_port = int(getattr(settings, "smtp_port", 587) or 587)
    timeout_seconds = int(getattr(settings, "request_timeout_seconds", 30) or 30)
    smtp_use_tls = bool(getattr(settings, "smtp_use_tls", True))
    smtp_username = str(getattr(settings, "smtp_username", "")).strip()
    smtp_password = str(getattr(settings, "smtp_password", "")).replace(" ", "").strip()

    with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds) as smtp:
        if smtp_use_tls:
            smtp.starttls()

        if smtp_username and smtp_password:
            smtp.login(smtp_username, smtp_password)

        smtp.send_message(message)
