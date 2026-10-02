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

## Integrated flows

- Local registration, login, session bootstrap, rotating refresh, and logout
- Google Identity Services credential exchange when configured
- Conversation list, create, rename, archive, unarchive, delete, and history
- POST SSE chat with buffered incremental parsing
- Progress, tool activity, persisted completion, citations, warnings, and 429
- Route restoration at `/c/:conversationId`

PostgreSQL remains authoritative for conversation history. The frontend never
sends visible history, user IDs, tool choices, or internal context in a chat
request.
