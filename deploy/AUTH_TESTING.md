# Authentication and regression checks

Recovery flow reference: https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html

## Account flows

Only `@gmail.com` account addresses are supported, including Google credentials.
Outlook, Hotmail, Yahoo, Workspace/custom domains and misleading suffixes are
rejected on the backend as well as in the UI. Existing non-Gmail account data
is retained, but those accounts cannot authenticate under this policy.
Email matching is case-insensitive; dots and plus aliases are not merged.

The UI collects Gmail first, then the password. The email step does not query
whether an account exists. Login and registration remain separate routes.
The Google button appears on the first step; password confirmation appears only
when an existing account must be linked. Recovery is available on the password step.

- Local account: log in with the existing password.
- New Google identity: verified Google token creates one account.
- Existing local email + Google: the first attempt requests password confirmation;
  a second Google request verifies the Google token and existing local password,
  links the Google subject, and opens the original account with its history.
- Subsequent Google login uses the linked subject without asking for a password.
- Forgotten local password: request an email link, open it, confirm a new password,
  then log in again. Reset invalidates all outstanding reset links and sessions.
- Google-only account: use Google login; recovery does not silently create a password.

## Email setup

Set `PUBLIC_APP_URL` to the HTTPS frontend origin and configure `SMTP_HOST`,
`SMTP_PORT`, `SMTP_SECURITY` (`starttls` on 587 or `ssl` on 465),
`SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL` from the existing provider.
Use the provider's approved sender. Store credentials only in the server environment.
Restart/redeploy the backend after changing its environment.

### Free option for the current DuckDNS demo: Gmail SMTP

Use a separate personal Gmail sender for this demo. It does not require purchasing
a sending domain, but it is subject to Google's sending limits and abuse controls.

1. Sign in to the sender Gmail account at https://myaccount.google.com/security.
2. Enable 2-Step Verification.
3. Open https://myaccount.google.com/apppasswords and create an app password named
   `Vietnam Travel Advisor`. If this option is unavailable, check Google's eligibility
   rules; some managed or protected accounts do not support app passwords.
4. Put the generated app password in the server's `.env.production`, without spaces.
   Never use the normal Gmail password and never post the app password in chat.

```env
PUBLIC_APP_URL=https://vietnam-travel-advisor.duckdns.org
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=your-sender@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-sender@gmail.com
```

Use the same Gmail address for `SMTP_USERNAME` and `SMTP_FROM_EMAIL`. After
deploying the new backend and migration, request recovery for an existing local
Gmail account and check the inbox and Spam folder. Google-only accounts receive
no password-reset link; sign in using Google.

References: https://support.google.com/mail/answer/185833 and
https://developers.google.com/workspace/gmail/imap/imap-smtp.

### Complete setup checklist (Windows and EC2)

#### 1. Choose the sender Google account

Use a Gmail account you control. This is the address sending recovery email;
it does not have to be the same as every user's login address. No Gmail API,
OAuth client secret or paid Google Workspace plan is needed for this SMTP setup.

In a browser, open Google Account > Security > How you sign in to Google >
2-Step Verification. Complete Google's setup and confirm it shows On.

#### 2. Generate an App Password

Open https://myaccount.google.com/apppasswords while signed in to the sender.
Create an entry named `Vietnam Travel Advisor`. Copy the generated 16-character
app password into your local environment file; remove display spaces.
If the page is unavailable, consult Google's App Password eligibility guidance.
Do not put the password in Google OAuth client settings or GitHub Variables.

#### 3. Fill the local files

The local `.env.production` and `backend/.env` contain the SMTP keys already.
Fill `SMTP_USERNAME` and `SMTP_FROM_EMAIL` with the sender Gmail address and
`SMTP_PASSWORD` with the App Password. Keep each key exactly once.

For local Python backend + Vite, use `backend/.env` and
`PUBLIC_APP_URL=http://localhost:5174` (change the port if Vite uses another).
For Docker production use `.env.production` and the HTTPS DuckDNS origin.
Do not put SMTP credentials in `frontend/.env` or any `VITE_*` variable.
Both real environment files must remain ignored by Git; examples contain no secrets.

#### 4. Edit the server environment in the SSH terminal

Open a Windows PowerShell terminal to connect (replace the key path if needed):

```powershell
ssh -i "$HOME\Downloads\vietnam-travel-advisor-key.pem" deploy@52.77.176.40
```

At the `deploy@...` Ubuntu prompt run:

```bash
cd /opt/vietnam-travel-advisor
nano .env.production
```

Add or edit the SMTP block from above, using the real sender and App Password.
Keep `PUBLIC_APP_URL=https://vietnam-travel-advisor.duckdns.org`.
Do not replace the rest of the existing server file. Save with Ctrl+O, Enter,
then exit with Ctrl+X. Restrict file permissions:

```bash
chmod 600 .env.production
```

#### 5. Deploy the new code before testing

The existing production image does not contain the new recovery routes.
Publish the reviewed authentication changes, then wait for CI and both build
and deploy jobs to pass. The deploy script applies `alembic upgrade head`
before starting the new backend, including `d8e4a61f209b`.
Verify that the new frontend displays the Gmail-first login screen.

If the new code is already deployed and only environment values changed,
recreate the backend so it reads them (a plain restart does not reread env files):

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml up -d --no-deps --force-recreate backend
```

Run all Docker commands here in the EC2 Ubuntu terminal, not Windows PowerShell.

#### 6. Validate SMTP authentication without sending email

After the new backend image is deployed, run in the EC2 terminal:

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml exec -T backend python - <<'PY'
import smtplib
import ssl
import sys
from app.core.config import settings as s

required = [s.smtp_host, s.smtp_username, s.smtp_password.get_secret_value(), s.smtp_from_email]
if not all(required):
    sys.exit("Missing SMTP configuration; fill the server environment first.")
try:
    if s.smtp_security == "ssl":
        client = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
    with client:
        if s.smtp_security == "starttls":
            client.starttls(context=ssl.create_default_context())
        client.login(s.smtp_username, s.smtp_password.get_secret_value())
    print("SMTP authentication OK; no email sent.")
except (OSError, smtplib.SMTPException) as exc:
    sys.exit("SMTP check failed: " + type(exc).__name__)
PY
```

This prints no credentials. `SMTPAuthenticationError` usually means the wrong
App Password, sender account, or a revoked App Password. `TimeoutError` means
the server could not reach the SMTP endpoint; check EC2 outbound access to 587.
Opening inbound SMTP ports is not necessary.

#### 7. Test the full recovery flow

Open https://vietnam-travel-advisor.duckdns.org/login in your browser.
Use an existing Gmail account that has a local password (or register a test
account through the application's Gmail/password registration flow).
Enter its Gmail, Continue, then Forgot password. Submit the Gmail and wait for
the email; check Spam as well. Open the link, set and confirm a new password,
and log in. Verify the old password and previously opened sessions no longer work.
Open the same email link again: it must be rejected. Link expiry is 20 minutes;
requests for the same account are limited to one email per 60 seconds.

Test account linking separately: choose the same Gmail using the Google button,
confirm the new local password, and verify the original conversation history.
Log out and try Google again: no password confirmation should be required.

The public "check your email" response is deliberately generic and is not
proof that mail was delivered. For delivery problems inspect:

```bash
docker compose --env-file .deploy.env --env-file .env.production \
  -f docker-compose.prod.yml logs --since 10m backend
```

`Password recovery mail delivery failed` means SMTP failed or is not configured.
If a successful request produces no message and no error, check whether the
account is Google-only, inactive, unknown, or within the 60-second cooldown.

### Alternative: Brevo Free

Brevo advertises 300 free emails per day, including SMTP relay. Create a free
account, activate transactional email, verify an approved sender, and obtain
SMTP credentials under SMTP & API. Use `smtp-relay.brevo.com`, port 587,
`starttls`, the SMTP login shown by Brevo, and an SMTP key (not the API key).
Sender approval can be required. A free Gmail sender cannot authenticate its own
domain; Brevo may replace its From address with a compliant address. For a stable
branded sender, use a domain whose DNS you control.

References: https://www.brevo.com/products/transactional-email/ and
https://help.brevo.com/hc/en-us/articles/14925263522578-Comply-with-Gmail-Yahoo-and-Microsoft-s-requirements-for-email-senders.

The endpoint always returns the same public message for known, unknown, inactive,
and Google-only accounts. SMTP runs after the response in a background task;
delivery failures are logged without addresses, passwords, or reset tokens.
There is a 60-second per-account cooldown in addition to the auth IP rate limit.
Links contain a random token in the URL fragment, so it is not sent in HTTP URLs;
the frontend removes the fragment after loading. The database stores only its hash.
Links expire in 20 minutes by default and are consumed atomically.

The background mail task is not a durable queue: if the process stops during
delivery, the user must request another link. There is no automatic retry.

## Automated checks

Backend: `cd backend` then `python -m pytest -q` against a migrated, isolated test
database. Frontend: `cd frontend` then `npm test` and `npm run build`.
Never point regression tests at the production database.

CI starts PostgreSQL, Redis and Qdrant. PostgreSQL tests exercise the real schema;
Redis tests cover concurrent rate limits and cache expiry; Qdrant tests create
and delete only uniquely named regression collections. For local service tests,
set `TEST_REDIS_URL` and `TEST_QDRANT_URL` to disposable test services.
If these are absent those two tests are explicitly skipped.

Auth integration tests cover password-proof linking, replay, wrong password,
unverified Google identity, reset hashing, expiry, reuse, mismatched passwords,
concurrent use, cooldown, SMTP failure, and access/refresh session revocation.
UI tests exercise confirmation, recovery submission, reset success and failure.
SMTP unit tests exercise encrypted transport and message construction; they do
not send mail. Google verifier and AI workflow remain stubbed in regression tests.

## Real deployment smoke check

Use a dedicated existing test account and set `SMOKE_BASE_URL`, `SMOKE_EMAIL`,
and `SMOKE_PASSWORD` in the shell environment, then run from `backend`:

```bash
python -m scripts.smoke_deployment
```

This calls the real HTTP API and RAG workflow, checks citations and persisted
history, deletes only the conversation it created, and logs out its session.
It can incur provider usage. Model loading and RAM must be checked separately
using backend logs and `docker stats --no-stream` after the request.

Before deploying, also test Gmail/Google in a browser, actual SMTP delivery to
an inbox, expired links, and history after reloading. CI cannot confirm external
OAuth console configuration, inbox delivery or production model performance.
