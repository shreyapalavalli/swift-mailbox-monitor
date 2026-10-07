# Swift Mailbox Monitor

FastAPI backend that polls an Outlook.com mailbox through Microsoft Graph, recognises incoming SWIFT messages (MT and MX), applies automation rules, and exposes the results to a dashboard through a JSON API. Non-SWIFT mail is never modified (not marked as read, not moved). Parsing and classification use the Python standard library only; storage is SQLite.

## Automation rules

Rules are evaluated in order; the first match wins: not SWIFT, SGU, cancellation, amendment, callback, ABA, other.

| Category | Action | Dashboard status |
|---|---|---|
| Not SWIFT | Ignored, mail untouched | none |
| SGU (reference starting `SGU` in field 20, field 21 or the narrative) | Forwarded to `CST_MAILBOX`, then marked as read | `ROUTED_CST` (audit row only, not on the action list) |
| Cancellation | Marked as read | `AUTO_CLOSED` |
| Cancellation, MX type in `CANCELLATION_ACTION_MX_TYPES` (default `camt.056`) | Left unread, waits for an analyst | `ACTION_REQUIRED` (high priority) |
| Amendment | Left unread, listed on `/api/swifts/alerts` | `PRIORITY` (high priority) |
| Callback with an `FT` or `INV` reference (must contain a digit) | Reply-all acknowledgement, marked as read | `RESPONDED` |
| Callback without an `FT`/`INV` reference | Left unread | `ACTION_REQUIRED` |
| ABA request | Left unread | `ACTION_REQUIRED` |
| Any other SWIFT (for example MT298 CLS) | Left unread | `ACTION_REQUIRED` (category `OTHER`) |

A message is SWIFT if its subject starts with `SWIFT Incoming` or the body contains `Swift Output:` / `MX Output:`. Action items are keyed by reference (field 20, else the MX `SWIFT Reference`, else the mail id in the subject); a repeated reference updates the existing row.

Note: camt.058 cancellations are auto-closed under the default `CANCELLATION_ACTION_MX_TYPES`; only camt.056 waits for an analyst.

## Setup (macOS / Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# then create .env with the keys below
```

## Azure app registration

- Supported account type: personal Microsoft accounts (authority `consumers`).
- Authentication > "Allow public client flows" = Yes.
- Redirect URI `http://localhost:8000/auth/callback` under "Mobile and desktop applications".
- Delegated API permissions: `Mail.ReadWrite`, `Mail.Send`, `User.Read`, `offline_access`.

## Configuration (`.env`)

Values below are placeholders. `.env` is gitignored.

| Key | Default | Meaning |
|---|---|---|
| `GRAPH_TENANT_ID` | required | Authority tenant. Use `consumers` for personal accounts. |
| `GRAPH_CLIENT_ID` | required | Application (client) ID from the Azure registration. |
| `SWIFT_MAILBOX` | required | `me` for the signed-in user's own mailbox, or a shared mailbox SMTP address. |
| `GRAPH_BASE_URL` | `https://graph.microsoft.com/v1.0` | Graph API base URL. |
| `GRAPH_REDIRECT_URI` | `http://localhost:8000/auth/callback` | Must match the Azure redirect URI. |
| `GRAPH_SCOPES` | `Mail.ReadWrite Mail.Send User.Read` | Space-separated delegated scopes (`offline_access` is added by MSAL). |
| `TOKEN_CACHE_PATH` | `.token_cache.json` | MSAL token cache file. |
| `DATABASE_PATH` | `data/swift_monitor.db` | SQLite database file. |
| `CST_MAILBOX` | `shreyapalavalli@gmail.com` | Where SGU messages are forwarded. |
| `CANCELLATION_ACTION_MX_TYPES` | `camt.056` | Comma-separated MX types that need an analyst instead of auto-close. |
| `POLL_FOLDERS` | `inbox,junkemail` | Comma-separated Graph folder names to poll. |
| `POLL_INTERVAL_SECONDS` | `30` | Seconds between polls. |
| `POLLER_ENABLED` | `true` | Set `false` to disable the background poller. |
| `FRONTEND_ORIGIN` | `http://localhost:5000` | Origin allowed by CORS. |

Generator keys (read by `scripts/generate_swifts.py`):

| Key | Default | Meaning |
|---|---|---|
| `GMAIL_APP_PASSWORD` | none (required unless `--dry-run`) | Gmail app password used for SMTP. |
| `GENERATOR_SENDER` | `vishnuprakash156@gmail.com` | Gmail address that sends the test mail. |
| `GENERATOR_RECIPIENT` | `MTheadsYI@outlook.com` | Monitored mailbox that receives it. |

Example:

```env
GRAPH_TENANT_ID=consumers
GRAPH_CLIENT_ID=<your-app-client-id>
SWIFT_MAILBOX=me
GMAIL_APP_PASSWORD=<16-char-app-password>
```

## Sign in once

```bash
python -m app.cli login      # device-code flow: open the printed URL, enter the code
```

Alternatively, run the server and open `http://localhost:8000/auth/login` in a browser. Tokens are stored in `.token_cache.json` (gitignored) and refreshed silently, including across restarts.

Process the mailbox one time without starting the server:

```bash
python -m app.cli run-once   # prints a JSON summary
```

Do not run `python -m app.cli run-once` while the server is running. It is a separate process, so the server's run lock cannot see it, and both could forward or reply to the same message.

## Run

```bash
uvicorn app.main:app --reload
```

The poller starts with the app and runs every `POLL_INTERVAL_SECONDS` (default 30) over `POLL_FOLDERS`. Set `POLLER_ENABLED=false` to run the API only. Polls are skipped with a warning until you have signed in. Interactive docs: `http://localhost:8000/docs`.

## Synthetic SWIFT generator

Sends realistic test messages (about 30% noise mixed in) from Gmail to the monitored mailbox.

1. Enable 2-Step Verification on the Gmail account.
2. Create an App Password (Google Account > Security > App passwords) and put it in `.env` as `GMAIL_APP_PASSWORD`.

```bash
python -m scripts.generate_swifts --dry-run --count 3        # print only, nothing sent
python -m scripts.generate_swifts --count 10 --interval 10   # send 10 messages, 10 s apart
python -m scripts.generate_swifts --kinds amendment,sgu_reply --count 4
```

| Option | Default | Meaning |
|---|---|---|
| `--interval` | `60` | Seconds between messages. |
| `--count` | run forever | Stop after N messages. |
| `--kinds` | all | Comma-separated subset of `cancellation_mt192`, `cancellation_return_mt199`, `camt056`, `camt058`, `amendment`, `callback_ft`, `callback_inv`, `aba_request`, `sgu_reply`, `cls_mt298`. |
| `--dry-run` | off | Print instead of sending. |

Test mail from Gmail can land in Junk, which is why `junkemail` is polled by default.

## API

Dashboard (`app/api/swift_routes.py`):

| Method | Path | Query / body | Returns |
|---|---|---|---|
| GET | `/api/swifts` | `status`, `category`, `since` (ISO-8601), `limit` (1-1000, default 200) | List of SWIFT actions |
| GET | `/api/swifts/alerts` | `since` | Actions with status `PRIORITY` (amendments) |
| GET | `/api/swifts/metrics` | none | Today's counts: `processed_today`, `swift_today`, `by_category_today`, `by_status_today`, `open_action_required`, `open_priority`, `failed_open`, `last_processed_at` |
| GET | `/api/swifts/{reference}` | none | One action; 404 if unknown |
| PATCH | `/api/swifts/{reference}` | body `{"status": "IN_PROGRESS" \| "RESOLVED"}` | Updated action; 404 if unknown |
| POST | `/api/process/run` | none | Runs one processing pass and returns its summary; 401 if not signed in; 409 if a run (poller or manual) is already in progress |
| GET | `/api/process/log` | `limit` (1-1000, default 100) | Recent processed-message log |

Mailbox and auth (`app/api/mail_routes.py`):

| Method | Path | Returns |
|---|---|---|
| GET | `/auth/login` | Redirect to Microsoft sign-in |
| GET, POST | `/auth/callback` | Completes sign-in, `{"authenticated": true}` |
| POST | `/auth/logout` | `{"authenticated": false}` |
| GET | `/api/graph/messages` | Messages from the mailbox |
| GET | `/api/graph/messages/unread` | Unread messages |
| GET | `/api/graph/messages/{message_id}` | One message |
| PATCH | `/api/graph/messages/{message_id}/read` | Marks the message as read |
| GET | `/api/graph/test-user` | Signed-in account from Graph `/me` |

CORS allows `FRONTEND_ORIGIN` (default `http://localhost:5000`).

## Mailbox curl runbook

Inspect the mailbox directly with Graph, independent of the app.

```bash
set -a; source .env; set +a
# 1. device code (the app accepts personal accounts via the "consumers" authority)
curl -s -X POST "https://login.microsoftonline.com/$GRAPH_TENANT_ID/oauth2/v2.0/devicecode" \
  -d "client_id=$GRAPH_CLIENT_ID" --data-urlencode "scope=Mail.ReadWrite Mail.Send User.Read offline_access"
# → open https://www.microsoft.com/link, enter user_code, sign in as MTheadsYI@outlook.com
# 2. poll for the token (repeat until no "authorization_pending")
curl -s -X POST "https://login.microsoftonline.com/$GRAPH_TENANT_ID/oauth2/v2.0/token" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:device_code" -d "client_id=$GRAPH_CLIENT_ID" -d "device_code=<device_code>"
TOKEN=<access_token>
# 3. folder counts
curl -s -H "Authorization: Bearer $TOKEN" "https://graph.microsoft.com/v1.0/me/mailFolders?\$select=displayName,totalItemCount,unreadItemCount"
# 4. messages as plain text (selecting fields does NOT mark them read)
curl -s -H "Authorization: Bearer $TOKEN" -H 'Prefer: outlook.body-content-type="text"' \
  "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?\$top=50&\$select=id,subject,from,receivedDateTime,isRead,body"
```

## Tests

```bash
.venv/bin/pytest
```
