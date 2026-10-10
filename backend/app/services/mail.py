from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.core.config import settings


class MailDeliveryError(Exception):
    pass


class RecoveryMailer(Protocol):
    async def send_reset(self, recipient: str, link: str) -> None: ...


class SmtpRecoveryMailer:
    async def send_reset(self, recipient: str, link: str) -> None:
        if not settings.smtp_host or not settings.smtp_from_email:
            raise MailDeliveryError("Recovery email is not configured")
        message = EmailMessage()
        message["Subject"] = "Vietnam Travel Advisor - Dat lai mat khau"
        message["From"] = settings.smtp_from_email
        message["To"] = recipient
        message.set_content(
            f"Ban da yeu cau dat lai mat khau. Mo lien ket sau:\n{link}\n\n"
            f"Lien ket het han sau {settings.password_reset_expire_minutes} phut va chi dung mot lan.\n"
            "Neu ban khong yeu cau, hay bo qua email nay. Khong chia se lien ket."
        )
        try:
            await asyncio.to_thread(self._send, message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailDeliveryError("Recovery email could not be delivered") from exc

    def _send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if settings.smtp_security == "ssl":
            client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        with client:
            if settings.smtp_security == "starttls":
                client.starttls(context=context)
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            client.send_message(message)
