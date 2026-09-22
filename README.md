# Swift Mailbox Monitor

Python project structure for monitoring a Microsoft Graph mailbox.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Configure delegated Microsoft Graph permissions in the app registration, then copy
the required values into `.env` before connecting to a mailbox. The app uses the
OAuth authorization-code flow; open `/auth/login` in a browser and sign in before
calling the mailbox endpoints.

Required delegated permissions:

- `Mail.ReadWrite`
- `User.Read`
- `offline_access`

The app registration must use a public client and include the redirect URI
`http://localhost:8000/auth/callback`.

`GET /api/graph/test-user` checks the signed-in account through `/me`. For the
signed-in user's own mailbox, set `SWIFT_MAILBOX=me`. For a shared mailbox, use
its SMTP address and grant the signed-in user Exchange Full Access. A guest-style
address containing `#EXT#` is not a mailbox address.

## Test

```bash
pytest
```
