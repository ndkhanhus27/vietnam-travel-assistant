# Vietnam Travel Advisor frontend

React 19, TypeScript, React Router, and Vite frontend for the FastAPI backend.

## Configuration

Copy the values from `.env.example` into a local `.env` when needed:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_GOOGLE_CLIENT_ID=
```

`VITE_GOOGLE_CLIENT_ID` is a browser OAuth client ID. Never place a Google
client secret in a Vite environment variable.

## Commands

```bash
npm install
npm run dev
npm test
npm run build
```

The default frontend origin is `http://localhost:5173`, matching the backend
CORS default.

## Google Sign-In setup

1. In Google Cloud Console, configure the OAuth consent screen for the app.
2. Create an OAuth 2.0 Client ID with application type **Web application**.
3. Add `http://localhost:5173` to **Authorized JavaScript origins**.
4. Put the same Web Client ID in both local environment files:

```env
# backend/.env
GOOGLE_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
CORS_ORIGINS=http://localhost:5173

# frontend/.env
VITE_GOOGLE_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
```

This app uses Google Identity Services ID-token credential mode, so it does
not require a backend OAuth redirect URI. Do not put a Google client secret in
the frontend. For deployment, add the real HTTPS frontend origin in Google
Cloud Console and `CORS_ORIGINS`.

## Integrated flows

- Local registration, login, session bootstrap, rotating refresh, and logout
- Google Identity Services credential exchange when configured
- Authenticated Google-first users can create a local password in account settings
- Conversation list, create, rename, archive, unarchive, delete, and history
- POST SSE chat with buffered incremental parsing
- Progress, tool activity, persisted completion, citations, warnings, and 429
- Route restoration at `/c/:conversationId`
- Three persisted appearance palettes matching the supplied color variants
- Profile display-name editing and logout-all-devices settings
- Server-authorized internal administration at `/admin`

## Development admin

Admin access is enforced by the backend. For a local bootstrap account, add
the following to `backend/.env`, run the Alembic migrations, and restart the
API:

```env
ADMIN_BOOTSTRAP_ENABLED=true
ADMIN_EMAIL=admin@example.com
ADMIN_INITIAL_PASSWORD=replace-with-a-strong-local-password
```

Bootstrap is disabled by default, is idempotent, and never logs the password.
Leave it disabled outside explicitly configured development environments.

PostgreSQL remains authoritative for conversation history. The frontend never
sends visible history, user IDs, tool choices, or internal context in a chat
request.
