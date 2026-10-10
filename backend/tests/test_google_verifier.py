import unittest
from unittest.mock import patch

from app.security.google import GoogleAuthVerifier, InvalidGoogleCredentialError, UnverifiedGoogleEmailError


class GoogleVerifierTest(unittest.IsolatedAsyncioTestCase):
    async def test_library_receives_expected_audience_and_verified_subject(self):
        with patch("app.security.google.id_token.verify_oauth2_token", return_value={"sub": "trusted-subject", "email": "user@gmail.com", "email_verified": True}) as verify:
            identity = await GoogleAuthVerifier("expected-client-id").verify("signed-token")
            self.assertEqual(verify.call_args.args[2], "expected-client-id")
            self.assertEqual(identity.subject, "trusted-subject")

    async def test_invalid_signature_or_audience_is_rejected(self):
        with patch("app.security.google.id_token.verify_oauth2_token", side_effect=ValueError("Invalid audience")):
            with self.assertRaises(InvalidGoogleCredentialError):
                await GoogleAuthVerifier("expected-client-id").verify("bad-token")

    async def test_unverified_google_email_is_rejected(self):
        with patch("app.security.google.id_token.verify_oauth2_token", return_value={"sub": "subject", "email": "user@gmail.com", "email_verified": False}):
            with self.assertRaises(UnverifiedGoogleEmailError):
                await GoogleAuthVerifier("expected-client-id").verify("token")
