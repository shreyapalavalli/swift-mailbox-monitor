# Frontend Plan: SWIFT Monitor Dashboard

How to build the Flask frontend for the SWIFT mailbox monitor, which backend endpoints feed each screen, and how the two sides work together in real time.

Read this first, then the backend [README.md](README.md). Everything below matches the backend on branch `dev-backend-vishnu` (PR #1). Sample payloads are real responses from the live mailbox.

---

## 1. What the frontend is for

The backend does the work: every 30 seconds it reads the SWIFT mailbox, classifies each SWIFT message, and acts on it automatically (forward, mark read, reply). The frontend is where an operations analyst:

1. **Sees what needs a human.** These are SWIFTs the backend could not, or must not, close on its own: camt.056 cancellations, amendments, unknown messages and ABA requests.
2. **Gets alerted immediately** when an amendment request arrives (priority), with the key details needed to respond.
3. **Watches the automation.** This covers what was auto-closed, what was routed to the CST team, what got an auto-reply, and what failed.
4. **Works the queue.** The analyst marks items *In progress* or *Resolved*.
5. **Checks system health.** This covers whether the mailbox connection is signed in, when the last poll ran, and whether anything failed.

The business rules the backend applies (from the brief's "Key Automation Scenarios"):

| SWIFT type | Backend action | Shows on dashboard as |
|---|---|---|
| Reference starting `SGU` (field 20/21 or narrative) | Forwarded to CST (shreyapalavalli@gmail.com) and marked read | Activity feed only: `ROUTED_CST` |
| Cancellation (MT n92, camt.058, "return the funds"…) | Marked read | Activity feed only: `AUTO_CLOSED` |
| **camt.056** cancellation | Left unread | **Queue: `ACTION_REQUIRED`, priority `HIGH`** |
| **Amendment** request | Left unread | **Alert + Queue: `PRIORITY`, priority `HIGH`** |
| Callback with `FT…`/`INV…` reference | Reply-all acknowledgement sent, marked read | Queue (informational): `RESPONDED` |
| ABA/routing request, weak-evidence cancellation, anything unrecognised | Left unread | **Queue: `ACTION_REQUIRED`** |
| Non-SWIFT email | Untouched | Activity feed only: `IGNORED` (hide by default) |

---

## 2. Architecture

```
 Browser (analyst)                     Flask frontend (:5001)              FastAPI backend (:8000)
 ─────────────────                     ──────────────────────              ───────────────────────
  HTML/CSS/JS pages  ◄── GET pages ───  serves templates + static          poller (every 30s)
        │                                (no business logic)                  │  Graph API ⇄ mailbox
        │                                                                     ▼
        └──── fetch() JSON every 3–10s (CORS) ──────────────────────────►  /api/swifts…  ◄── SQLite
                                                                           /api/process…
                                                                           /api/graph/test-user
```

- **Flask only serves pages and static assets.** All data comes from the FastAPI backend. Browser JavaScript calls it directly with `fetch()`, and the backend's CORS setting allows exactly one frontend origin (§3).
- **Real time means polling.** The backend has no WebSocket or SSE. The dashboard polls with a `since` cursor so each poll returns only what changed (§5). With a 30 s backend poll interval, polling the API every 3–5 s feels instant.
- **The backend is the source of truth.** The frontend never talks to Microsoft Graph or SQLite directly, and never decides categories or actions. It displays them and updates status only.

> **Alternative (only if you hit CORS trouble or need to hide the API):** have Flask proxy `/api/*` to `http://127.0.0.1:8000` server-side, for example with `requests`, and have the browser call Flask only. The endpoint contract below stays the same.

---

## 3. Running both sides locally

```bash
# Terminal 1: backend (from repo root, venv active; see README for one-time sign-in)
FRONTEND_ORIGIN=http://localhost:5001 uvicorn app.main:app --port 8000

# Terminal 2: frontend
cd frontend && flask --app app run --port 5001
```

- **Don't use port 5000 on macOS.** AirPlay Receiver (Control Center) already listens on it. Use 5001, and set `FRONTEND_ORIGIN` on the backend to match exactly.
- **CORS origin must match exactly.** `http://localhost:5001` and `http://127.0.0.1:5001` are different origins. Open the dashboard with the same host you put in `FRONTEND_ORIGIN`, or the browser blocks the API calls.
- **Make the API base URL configurable** in the frontend, for example `API_BASE = os.environ.get("SWIFT_API_BASE", "http://localhost:8000")`, and inject it into templates.
- **Safe test mode:** start the backend with `ACTIONS_ENABLED=false` to classify and store without touching the mailbox. Rows still appear in the API, and the activity feed shows outcome `DRY_RUN`.
- **Generating test traffic:** `python -m scripts.generate_swifts --count 10 --interval 15` emails realistic SWIFTs of every kind (amendments, camt.056, callbacks, SGU…) into the mailbox. It needs `GMAIL_APP_PASSWORD` in `.env`. Use `--kinds amendment,camt056` to target one flow, for example to test the alert toast.
- **Interactive API docs:** `http://localhost:8000/docs` lists every endpoint with a "Try it out" button.

---

## 4. Endpoint reference

All timestamps are **UTC ISO-8601** strings, for example `2026-10-07T09:00:42.166635+00:00`. Convert to the analyst's local time (SGNY is America/New_York) for display only.

### 4.1 `GET /api/swifts`: the work queue

These are SWIFTs that need, or needed, a human, **one row per payment reference**. If a later message arrives with the same reference, it updates that row: the latest message wins, `created_at` is kept and `updated_at` moves.

| Query param | Type | Default | Notes |
|---|---|---|---|
| `status` | string | – | `ACTION_REQUIRED`, `PRIORITY`, `RESPONDED`, `IN_PROGRESS`, `RESOLVED` |
| `category` | string | – | `CANCELLATION`, `AMENDMENT`, `CALLBACK`, `ABA_REQUEST`, `OTHER` |
| `since` | ISO datetime | – | Only rows with `updated_at` **strictly after** this. Trailing `Z` is OK, and a value with no offset is treated as UTC. Invalid → 422 |
| `limit` | int 1–1000 | 200 | Out of range → 422 |

Sorted by `updated_at` **descending**. Response is an array of `SwiftAction`:

```json
{
  "reference": "RPIS20260908",
  "graph_message_id": "AQMkADAw…E2UU3wAAAA==",
  "received_at": "2026-10-07T07:14:40+00:00",
  "format": "MT",
  "message_type": "MT298",
  "related_reference": "06997CBR0811269A",
  "category": "OTHER",
  "status": "ACTION_REQUIRED",
  "priority": "NORMAL",
  "sender_bic": "SOGEFRPPCLS",
  "receiver_bic": "SOGEUS33XXX",
  "currency": "USD",
  "amount": "315071.79",
  "business_purpose": ":25:00188050 :30:260908 :21:06997CBR…",
  "narrative": ":25:00188050\n:30:260908\n:21:06997CBR0811269A\n…",
  "matched_terms": [],
  "reason": "Unmatched SWIFT message requires analyst review",
  "created_at": "2026-10-07T08:57:30.994245+00:00",
  "updated_at": "2026-10-07T08:57:30.994245+00:00"
}
```

**Field guide (the "key extracts"):**

| Field | Brief's term | Display notes |
|---|---|---|
| `message_type` + `format` | Message Type (MT/MX) | e.g. `MT199`, `MT298`, `camt.056.001.08`. Badge: `MT` or `MX`. |
| `reference` | Payment Reference | The row key. MT: field 20. MX: SWIFT Reference. Fallback: mail id. Monospace and copyable. |
| `related_reference` | Related reference | MT field 21. Often the reference the counterparty is asking about. Can be null. |
| `category` | Request Category | Enum §6. |
| `business_purpose` | Business Purpose | Extracted purpose, or the first sentence of the narrative. **Can be noisy** for structured messages like MT298, so truncate to about 120 chars and show the full text in the detail view. |
| `amount` + `currency` | – | `amount` is a **decimal string** (`"315071.79"`), so never use float maths. Format with `Intl.NumberFormat(…, {style:'currency', currency})`. Both can be null. |
| `sender_bic` / `receiver_bic` | – | 8 or 11-char BICs. Can be null. |
| `narrative` | Business Content | Field 79/77E text (MT) or the whole message (MX). Has `\n` line breaks, so render in `<pre>` or with `white-space: pre-wrap`. |
| `matched_terms` | – | Keywords that drove the classification, e.g. `["PLEASE AMEND","SHOULD READ"]`. Show as chips under "Why this category". Can be `[]`. |
| `reason` | – | Plain-English reason for the decision. Show as-is. |
| `priority` | – | `HIGH` / `NORMAL` / `LOW`. **Use this for highlighting**, not `status` (see §6.2). |
| `received_at` | – | When the email arrived. Use it for "age" and SLA timers. |
| `graph_message_id` | – | Mailbox id of the source email (§4.7). Opaque; don't display. |

### 4.2 `GET /api/swifts/alerts`: priority alerts (amendments)

Same shape as 4.1, filtered to `status == "PRIORITY"`. Optional `since`. These are amendment requests the brief says must be prioritised. Show them as a pinned alert strip, and raise a toast for each **new** one (§5.3).

### 4.3 `GET /api/swifts/metrics`: KPI tiles

```json
{
  "processed_today": 12,
  "swift_today": 4,
  "by_category_today": {"CANCELLATION": 1, "CST": 2, "OTHER": 1},
  "by_status_today":   {"ACTION_REQUIRED": 1, "AUTO_CLOSED": 1, "ROUTED_CST": 2},
  "open_action_required": 1,
  "open_priority": 0,
  "failed_open": 0,
  "last_processed_at": "2026-10-07T09:00:42.166635+00:00"
}
```

| Key | Meaning |
|---|---|
| `processed_today` | All emails processed today, SWIFT and non-SWIFT. |
| `swift_today` | SWIFT emails processed today. |
| `by_category_today` | SWIFTs today by category. Includes `CST` (SGU routed). Keys only appear when the count is > 0, so default missing keys to 0. |
| `by_status_today` | SWIFTs today by outcome status: `AUTO_CLOSED`, `ROUTED_CST`, `RESPONDED`, `ACTION_REQUIRED`, `PRIORITY`. Same missing-key rule. |
| `open_action_required` | Queue rows currently `ACTION_REQUIRED` (all days). |
| `open_priority` | Queue rows currently `PRIORITY` (all days). Use it for the alert badge. |
| `failed_open` | Emails whose last processing attempt failed. The backend retries them every poll. If this is above 0, show a warning. |
| `last_processed_at` | Last time the backend processed any email, or `null`. Use it for the "last activity" indicator. |

- **"Today" is the UTC day.** It rolls over at 8 pm New York time (EDT). Label the tiles "today (UTC)", or ask for a timezone parameter later.
- **Suggested tiles:**
  - SWIFTs today
  - **Needs action** (`open_action_required`)
  - **Priority** (`open_priority`)
  - Auto-closed today (`by_status_today.AUTO_CLOSED`)
  - Routed to CST today (`by_status_today.ROUTED_CST`)
  - Auto-replied today (`by_status_today.RESPONDED`)
  - Failures (`failed_open`)
- **Suggested chart:** today's SWIFTs by category, as a small bar chart built from `by_category_today`.

### 4.4 `GET /api/swifts/{reference}`: detail

This returns one `SwiftAction`, or 404 `{"detail": "SWIFT not found"}`. References can contain `-`, `.`, `:`, for example the MX reference `swi04003-2026-09-08T06:43:03.23847.2373755Z`. Build the URL with `encodeURIComponent(reference)`; the backend route accepts the encoded form.

### 4.5 `PATCH /api/swifts/{reference}`: analyst updates status

```http
PATCH /api/swifts/RPIS20260908
Content-Type: application/json

{"status": "IN_PROGRESS"}      // or "RESOLVED"
```

| Response | When |
|---|---|
| 200 + updated `SwiftAction` | OK. `updated_at` moves, so the next delta poll sees it too. |
| 404 | Unknown reference. |
| 422 | Any status other than `IN_PROGRESS` / `RESOLVED`. |

- **The mailbox doesn't change.** This only updates the dashboard. Resolving does **not** mark the email read.
- **There's no assignee field.** If you need "who's working on it", that's a backend addition (§9).

### 4.6 Processing and activity

**`GET /api/process/log?limit=100`** (1–1000) is the audit trail of **every** email the backend handled, newest first (`processed_at` DESC). There's no `since` parameter, so poll with a small limit and diff (§5.2).

```json
{
  "graph_message_id": "AQMkADAw…",
  "folder": "inbox",
  "received_at": "2026-10-07T07:14:40+00:00",
  "subject": "SWIFT Incoming Funds Transfer message-08/09/26-03.10.02MpGPSMail-5510-000001",
  "sender": "vishnuprakash156@gmail.com",
  "is_swift": 1,
  "reference": "WFW260907-001017",
  "message_type": "MT199",
  "category": "CST",
  "action": "FORWARD_TO_CST",
  "status": "ROUTED_CST",
  "outcome": "DONE",
  "completed_steps": "FORWARDED,MARKED_READ",
  "error": null,
  "attempts": 1,
  "processed_at": "2026-10-07T09:00:40.339000+00:00"
}
```

- **Automated outcomes live here.** SGU-routed and auto-closed SWIFTs are **only** visible in this log, never in `/api/swifts`. That's why the activity feed matters.
- **Hide non-SWIFT rows by default:** `is_swift == 0` means category `NOT_SWIFT`. Add a toggle to show them.
- **What `outcome` means:**
  - `DONE`: finished.
  - `FAILED`: the backend will retry. Show `error` and `completed_steps`.
  - `DRY_RUN`: the backend is in dry-run mode, so nothing was changed in the mailbox.
- **`action` values:** `FORWARD_TO_CST`, `MARK_READ`, `AUTO_REPLY`, `STORE_FOR_ANALYST`, `IGNORE`. Can be null on a failed parse.
- **`attempts`:** goes up with each retry.

**`POST /api/process/run`** is the "Check mailbox now" button. It runs one processing pass immediately.

| Response | When / UI |
|---|---|
| 200 `{"fetched":12,"processed":3,"skipped":9,"failed":0,"by_action":{"MARK_READ":1,…}}` | Toast: "Checked mailbox: 3 new, 0 failed". |
| 409 `{"detail":"A processing run is already in progress."}` | Toast: "Already checking, try again in a few seconds". Disable the button briefly. |
| 401 `{"detail":"Microsoft sign-in required. Visit /auth/login first."}` | Show the sign-in banner (§4.8). |
| 500 | Generic error toast. |

The button is optional: the poller runs every 30 s anyway. A full pass can take a few seconds, so show a spinner.

### 4.7 Original email (optional detail tab)

**`GET /api/graph/messages/{graph_message_id}`** fetches the source email live from the mailbox: `{id, subject, sender, received_date_time, body, is_read, has_attachments, folder}`. The body is plain text.

- **It calls Microsoft Graph live**, so it's slower and can fail. Load it lazily when the user opens an "Original email" tab.
- **Some ids can't be fetched.** Graph ids can contain `/`, which breaks this route even when URL-encoded. If it returns 404, show "Original email unavailable" and rely on `narrative`, which already holds the business content.

### 4.8 Connection / sign-in status

There's no dedicated status endpoint. Use **`GET /api/graph/test-user`**:

| Response | Meaning |
|---|---|
| 200 `{"userPrincipalName": "MTheadsYI@outlook.com", "displayName": "MT heads", …}` | Backend is signed in to the mailbox. Show "Connected as MTheadsYI@outlook.com". |
| any non-200 (typically 500 when signed out) | Not signed in. Show a banner: "Mailbox not connected. [Sign in]", linking to **`http://localhost:8000/auth/login`** in a new tab. The analyst signs in with Microsoft and the backend picks it up on its next poll. |

Check this on page load and then every 60 s, not every few seconds, because each call hits Microsoft.

### 4.9 Endpoints the frontend should **not** call

| Endpoint | Why not |
|---|---|
| `PATCH /api/graph/messages/{id}/read` | Changes the real mailbox behind the processor's back. |
| `GET /api/graph/messages`, `/messages/unread` | Raw mailbox dumps with full bodies of all mail. Not needed; the dashboard data is in `/api/swifts` and `/api/process/log`. |
| `POST /auth/logout` | Disconnects the whole backend from the mailbox. Admin-only, if at all. |

---

## 5. Real-time strategy (polling)

### 5.1 Poll schedule

| What | Endpoint | Interval |
|---|---|---|
| Queue changes | `GET /api/swifts?since=<cursor>` | 3 s |
| KPI tiles | `GET /api/swifts/metrics` | 5 s |
| Activity feed | `GET /api/process/log?limit=50` | 5 s |
| Connection | `GET /api/graph/test-user` | 60 s |

Pause polling when the tab is hidden (`document.visibilityState === "hidden"`), and do one immediate refresh when it becomes visible again. On fetch errors, back off (for example 3 s → 6 s → 12 s → max 30 s) and show a small "Backend unreachable" pill. Reset the backoff on success.

### 5.2 The delta pattern (queue)

```js
const API = window.SWIFT_API_BASE;          // injected by Flask template
const rows = new Map();                      // reference -> SwiftAction
let cursor = null;                           // max updated_at seen

async function initialLoad() {
  const data = await (await fetch(`${API}/api/swifts?limit=1000`)).json();
  data.forEach(r => rows.set(r.reference, r));
  cursor = data.reduce((m, r) => (m && m > r.updated_at ? m : r.updated_at), null);
  render();
}

async function pollQueue() {
  const url = cursor ? `${API}/api/swifts?since=${encodeURIComponent(cursor)}&limit=1000`
                     : `${API}/api/swifts?limit=1000`;
  const changed = await (await fetch(url)).json();
  for (const r of changed) {
    const prev = rows.get(r.reference);
    rows.set(r.reference, r);
    if (r.status === "PRIORITY" && prev?.status !== "PRIORITY") notifyPriority(r);  // §5.3
    if (!prev) flashNewRow(r.reference);
  }
  if (changed.length) {
    cursor = changed.reduce((m, r) => (m > r.updated_at ? m : r.updated_at), cursor ?? changed[0].updated_at);
    render();
  }
}
```

- **Cursor comparisons:** `updated_at` strings are all UTC `+00:00` ISO strings, so plain string comparison orders them correctly.
- **Your own updates:** a `PATCH` returns the updated row, so apply it to `rows` straight away (optimistic UI). The next delta poll returns it again, harmlessly.
- **Activity feed:** keep a `Set` of `graph_message_id + processed_at` keys you've shown. Prepend unseen rows from each `?limit=50` poll, highlighting `FAILED`.

### 5.3 Priority alerts (amendments)

When a row first appears with `status == "PRIORITY"`, or an existing row changes to it:

1. Show a toast or pinned card: **"Amendment request: {reference}"**, with message type, sender BIC, amount + currency, related reference, business purpose (truncated) and age, plus buttons **[Open]** and **[Start]**. **[Start]** does `PATCH status=IN_PROGRESS`.
2. Optionally play a short sound and update `document.title` to `(n) SWIFT Monitor`, where n = `open_priority`.
3. Optionally send a browser notification, after asking permission once (`Notification.requestPermission()`).

On first page load, don't toast the existing PRIORITY rows. Show them in the alert strip instead, and only toast what arrives afterwards.

---

## 6. Enumerations

### 6.1 `category` (queue rows)

| Value | Label | Notes |
|---|---|---|
| `AMENDMENT` | Amendment | Always `PRIORITY` / `HIGH` when it arrives. |
| `CANCELLATION` | Cancellation | Only in the queue when it's camt.056 (HIGH) or weak evidence (NORMAL). Others are auto-closed. |
| `CALLBACK` | Callback | `RESPONDED` = auto-acknowledged. `ACTION_REQUIRED` = callback with no FT/INV reference. |
| `ABA_REQUEST` | ABA / routing | Remitter responses about missing ABA numbers. |
| `OTHER` | Other / unrecognised | Needs a human to read it. |

In `/api/process/log` and `by_category_today` you'll also see **`CST`** (routed to the CST team) and **`NOT_SWIFT`**.

### 6.2 `status`

| Value | Set by | Open? | Suggested style |
|---|---|---|---|
| `PRIORITY` | backend (amendment) | yes | red / alert |
| `ACTION_REQUIRED` | backend | yes | amber |
| `RESPONDED` | backend (callback auto-reply) | no, informational | blue |
| `IN_PROGRESS` | analyst via PATCH | yes | purple |
| `RESOLVED` | analyst via PATCH | no | grey |
| `AUTO_CLOSED`, `ROUTED_CST`, `IGNORED` | backend | – | **log/metrics only**, never in the queue |

Once an analyst PATCHes a PRIORITY row to `IN_PROGRESS`, its `status` is no longer `PRIORITY`. It leaves `/alerts`, and `open_priority` decreases. **`priority` stays `HIGH`**, so keep highlighting with `priority == "HIGH"` (plus `category`) in the queue rather than relying on `status`.

If a new email arrives with the same reference, the backend overwrites the row, including `status`. A RESOLVED item can therefore reopen as ACTION_REQUIRED or PRIORITY. Treat that as a new arrival: flash the row, and toast if it's PRIORITY.

### 6.3 `priority`

`HIGH` (camt.056, amendments), `NORMAL`, `LOW`. Sort the queue by priority (HIGH first), then `received_at` (oldest first), so the oldest urgent item is on top.

---

## 7. Screens

### 7.1 Overview (`/`): the main monitoring screen

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ SWIFT Monitor        ● Connected as MTheadsYI@outlook.com   Last activity 12s ago   [Check now] │
├───────────────────────────────────────────────────────────────────────────────┤
│ ⚠ 2 PRIORITY AMENDMENTS  [SGU…] [0433…]  ─ alert strip (from status==PRIORITY)       │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬───────────┤
│ SWIFTs   │ Needs    │ Priority │ Auto-    │ Routed   │ Auto-    │ Failures  │
│ today    │ action   │          │ closed   │ to CST   │ replied  │           │
├──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴───────────┤
│ Work queue (open items)                         │ Live activity               │
│ Pri Ref        Type   Category   Amount   Age   │ 09:00 ROUTED_CST WFW2609…   │
│ ●H  RPIS2026…  MT298  Other      USD 315k 2h    │ 09:00 AUTO_CLOSED 04358…    │
│ …                                               │ 09:00 STORED RPIS2026…      │
└─────────────────────────────────────────────────┴─────────────────────────────┘
```

- **Header:** connection status (§4.8) and last activity, as a relative time from `metrics.last_processed_at` that ticks every second client-side. Also the **Check now** button (§4.6).
  - If `last_processed_at` is older than about 2 minutes while connected, show "Poller may be stalled".
- **Alert strip:** one chip per PRIORITY row. Clicking a chip opens its detail.
- **KPI tiles:** from §4.3. Clicking a tile filters the queue, for example Needs action → `status=ACTION_REQUIRED`.
- **Work queue:** rows where `status` is one of `PRIORITY`, `ACTION_REQUIRED` or `IN_PROGRESS`.
  - Columns: priority dot, reference, message type, category, sender BIC, amount, business purpose (truncated), age (now − `received_at`), status.
  - Inline actions: **Start** and **Resolve**.
  - New or changed rows flash briefly.
- **Live activity feed:** from `/api/process/log`, SWIFT-only by default. Each line shows time, status chip, reference, and the subject tail. `FAILED` lines are red, with `error` on hover.

### 7.2 Queue (`/queue`): full work list

- **Filters:** status (multi-select; default = open statuses), category, priority, free-text search over reference / related reference / BIC / business purpose (client-side).
- **Display:** sortable columns, and "Resolved" and "Responded" tabs to see closed items.
- **Data:** the same `rows` map from §5.2, filtered client-side. One data source keeps every screen consistent.

### 7.3 SWIFT detail (`/swift/<reference>` or a side drawer)

The **key extracts** panel, for the analyst who has to respond quickly:

| Section | Content |
|---|---|
| Header | `reference` (copy button), `message_type` + `format` badge, category, status, priority, age |
| Key details | Related reference (copy), sender BIC → receiver BIC, amount + currency, received at (local + UTC tooltip) |
| Business purpose | Full `business_purpose` |
| Why this category | `reason` + `matched_terms` chips |
| Message text | `narrative` in a monospace, pre-wrapped block |
| Original email (tab, lazy) | §4.7 |
| Actions | **Start** / **Resolve** (PATCH), **Copy summary**: a plain-text block (ref, type, amount, related ref, purpose) for pasting into a reply |

For amendments specifically, put **related reference, amount and the narrative's "SHOULD READ … INSTEAD OF …" text** at the top. That is what the analyst needs to process the amendment.

### 7.4 Activity / audit (`/activity`)

A full table of `/api/process/log` (limit 500):
- **Filters:** outcome (`DONE`/`FAILED`/`DRY_RUN`), action, category, SWIFT only, and folder.
- **Columns:** processed time, folder, subject, sender, reference, category, action, status, outcome, attempts, completed steps, error.

This is where a supervisor checks that the automation is doing the right thing.

### 7.5 System (`/system`, small)

- Connection status with a sign-in link (§4.8).
- Last activity, and failures count (link to Activity filtered to `FAILED`).
- **Dry-run indicator:** if the recent log has `outcome == "DRY_RUN"`, show a prominent "DRY RUN: no mailbox changes" banner on every page.
- The Check now button.

---

## 8. Suggested Flask project layout

```
frontend/
  app.py                 # Flask app: routes render templates, injects SWIFT_API_BASE
  templates/
    base.html            # header (connection pill, last activity), nav, toast container, dry-run banner
    overview.html
    queue.html
    detail.html
    activity.html
    system.html
  static/
    js/api.js            # fetch wrapper: base URL, JSON, error/backoff handling
    js/store.js          # rows Map + cursor + subscribe(); the single source for all screens
    js/poller.js         # schedules from §5.1, visibility pause, backoff
    js/alerts.js         # toast/sound/notification for new PRIORITY rows
    js/views/*.js        # render functions per screen
    css/app.css
  requirements.txt       # flask
```

```python
# frontend/app.py
import os
from flask import Flask, render_template

app = Flask(__name__)
API_BASE = os.environ.get("SWIFT_API_BASE", "http://localhost:8000")

@app.context_processor
def inject_api():
    return {"api_base": API_BASE}

@app.get("/")
def overview(): return render_template("overview.html")
@app.get("/queue")
def queue(): return render_template("queue.html")
@app.get("/swift/<path:reference>")
def detail(reference): return render_template("detail.html", reference=reference)
@app.get("/activity")
def activity(): return render_template("activity.html")
@app.get("/system")
def system(): return render_template("system.html")
```

```html
<!-- templates/base.html (excerpt) -->
<script>window.SWIFT_API_BASE = {{ api_base|tojson }};</script>
```

Use `<path:reference>` for the detail route. References contain characters such as `.`, `:` and `-` (MX references look like `swi04003-2026-09-08T06:43:03.23847.2373755Z`), and `path` accepts anything.

Plain JS with no build step is enough. If you prefer, htmx or Alpine.js work well with this polling model. Don't add a SPA framework unless you need it.

---

## 9. Known limitations / possible backend additions

These aren't needed to build everything above. If the UI wants them, ask the backend owner, and use the suggested contracts so both sides agree:

| Gap | Workaround now | Suggested backend addition |
|---|---|---|
| No push channel | Poll (§5) | `GET /api/events` (Server-Sent Events) emitting `swift.updated` / `process.logged` |
| No auth-status endpoint | `/api/graph/test-user` (§4.8) | `GET /api/status` → `{signed_in, account, actions_enabled, poller_enabled, last_processed_at}` |
| No dry-run flag in the API | Infer from log `outcome == "DRY_RUN"` | Include `actions_enabled` in `/api/status` |
| Activity log has no `since` | Poll `limit=50` and diff | `GET /api/process/log?since=` |
| No assignee / notes on queue items | – | `PATCH` body `{status, assignee, note}` + columns |
| "Today" = UTC day | Label tiles "(UTC)" | `GET /api/swifts/metrics?tz=America/New_York` |
| Resolve doesn't mark the email read | Explain in UI | Optional `mark_read: true` on PATCH |
| API has no authentication | Run on localhost only | Token or session auth before any shared deployment |

---

## 10. Error handling cheat sheet

| Status | Where | UI behaviour |
|---|---|---|
| network error / backend down | any | "Backend unreachable" pill, back off (§5.1), keep showing last data greyed |
| 401 | `POST /api/process/run` | Sign-in banner (§4.8) |
| 404 | detail / PATCH / original email | "Not found" message. For original email, fall back to `narrative`. |
| 409 | `POST /api/process/run` | "Already checking" toast |
| 422 | PATCH / bad `since` / `limit` | Bug in the frontend: log it to the console and show a generic error |
| 500 | any | Generic error toast. On `/api/graph/test-user` it means "not signed in". |

FastAPI errors are JSON `{"detail": "<message>"}`, or for 422 `{"detail": [ {loc, msg, type}, … ]}`.

---

## 11. Build order and acceptance checklist

1. **Skeleton:** Flask app, base layout, `api.js` with the base URL. Load `/api/swifts/metrics` and render the tiles.
2. **Store and poller:** initial load plus delta polling (§5.2), rendering the work queue.
3. **Detail view:** key extracts panel, and PATCH Start/Resolve with optimistic update.
4. **Alerts:** strip, toast and title badge for PRIORITY (§5.3).
5. **Activity feed:** overview panel plus the full Activity page.
6. **System:** connection status, Check now, dry-run banner, error and backoff states.
7. **Polish:** relative times, local-time display, number formatting, empty states ("No open items 🎉"), keyboard shortcut `/` for search.

Test against the backend with the generator (`--kinds amendment,camt056,callback_ft,sgu_reply,aba_request`). Done means:

- [ ] A generated **amendment** produces a toast and alert chip within about 35 s of the email arriving (≤ 30 s poller + ≤ 5 s UI poll). The detail shows reference, related reference, amount, BICs and the "SHOULD READ" narrative.
- [ ] A **camt.056** appears in the queue as HIGH / ACTION_REQUIRED, and the email stays unread.
- [ ] An **SGU** message shows in the activity feed as ROUTED_CST and is **not** in the queue. The "Routed to CST" tile increments.
- [ ] A non-camt.056 **cancellation** shows as AUTO_CLOSED in the feed only.
- [ ] An **FT/INV callback** shows as RESPONDED (closed) and the auto-reply count increments.
- [ ] **Start** then **Resolve** moves the item out of the open queue, and the metrics tiles update without a page reload.
- [ ] Stopping the backend shows "Backend unreachable" and it recovers automatically when restarted.
- [ ] With the backend signed out, the sign-in banner shows and links to `/auth/login`.
- [ ] With `ACTIONS_ENABLED=false`, the dry-run banner shows.
- [ ] The dashboard works from `http://localhost:5001` with `FRONTEND_ORIGIN=http://localhost:5001`, with no CORS errors in the console.
