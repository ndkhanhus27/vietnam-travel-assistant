import unittest
from unittest.mock import patch

from app.core.config import settings, Settings
from app.services.mail import SmtpRecoveryMailer, MailDeliveryError


class RecoveryMailTest(unittest.IsolatedAsyncioTestCase):
    async def test_starttls_authenticates_and_sends_the_reset_link(self):
        with patch.object(settings, "smtp_host", "smtp.example.com"), patch.object(settings, "smtp_from_email", "sender@example.com"), patch.object(settings, "smtp_username", "user"), patch("app.services.mail.smtplib.SMTP") as smtp:
            # SMTP's context manager returns the same client.
            smtp.return_value.__enter__.return_value = smtp.return_value
            await SmtpRecoveryMailer().send_reset("recipient@example.com", "https://example.com/reset-password#token=secret")
            smtp.return_value.starttls.assert_called_once()
            smtp.return_value.login.assert_called_once()
            message = smtp.return_value.send_message.call_args.args[0]
            self.assertEqual(message["To"], "recipient@example.com")
            self.assertIn("#token=secret", message.get_content())

    async def test_missing_configuration_fails_without_sending(self):
        with patch.object(settings, "smtp_host", ""):
            with self.assertRaises(MailDeliveryError):
                await SmtpRecoveryMailer().send_reset("user@example.com", "https://example.com")

    def test_recovery_origin_rejects_http_public_hosts_and_url_credentials(self):
        for origin in ["http://example.com", "https://user:pass@example.com", "https://example.com/path", "https://example.com?next=bad"]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                Settings(public_app_url=origin)
