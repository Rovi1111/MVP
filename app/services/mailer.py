"""Отправка отчётов по email через SMTP."""

import re
import smtplib
from email.message import EmailMessage

from app.errors import AppError, InvalidDataError
from app.services.settings import OrgSettings

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SMTP_TIMEOUT = 30


class MailError(AppError):
    status_code = 502


def send_mail(
    settings: OrgSettings,
    to: str,
    subject: str,
    body: str,
    attachments: list[tuple[bytes, str, str]],
) -> None:
    """attachments: список (содержимое, MIME-тип, имя файла)."""
    to = to.strip()
    if not _RE_EMAIL.match(to):
        raise InvalidDataError("Укажите корректный адрес электронной почты")
    if not settings.smtp_configured:
        raise InvalidDataError("Отправка почты не настроена: задайте SMTP в настройках или в .env")

    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.smtp_from, to, subject
    message.set_content(body)
    for content, mime, name in attachments:
        maintype, subtype = mime.split("/", 1)
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Не удалось отправить письмо: {exc}") from exc
