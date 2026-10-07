# Demo Plan: SWIFT Mailbox Monitor

What to cover when demoing to the judges, in order. Target length is about 8 minutes, plus Q&A.

**Windows to have open:**
1. The dashboard at `http://localhost:5001`. Fallback: `http://localhost:8000/docs`.
2. Outlook web for **MTheadsYI@outlook.com**, showing the Inbox.
3. Gmail for **shreyapalavalli@gmail.com**, the CST team mailbox.
4. Gmail for **vishnuprakash156@gmail.com**, which receives the callback acknowledgements.
5. A terminal for the generator, and a second one running `tail -f data/backend.log | grep -E "swift\.(processor|poller)"`.

---

## 1. Before the judges arrive

| # | Check | How | Expected |
|---|---|---|---|
| 1 | `.env` has the demo settings | `grep -E "POLL_INTERVAL_SECONDS\|FRONTEND_ORIGIN\|GMAIL_APP_PASSWORD" .env` | `POLL_INTERVAL_SECONDS=10`, `FRONTEND_ORIGIN=http://localhost:5001`, app password set |
| 2 | Backend running | `uvicorn app.main:app --port 8000 2>&1 \| tee data/backend.log` | `curl localhost:8000/health` → `{"status":"UP"}` |
| 3 | Mailbox signed in | `curl localhost:8000/api/graph/test-user` | 200, `userPrincipalName` = MTheadsYI@outlook.com. If not, run `python -m app.cli login` |
| 4 | Actions are live (not a dry run) | `.env` has no `ACTIONS_ENABLED=false` | Backend log has no "dry run" warning at startup |
| 5 | Frontend running | `cd frontend && flask --app app run --port 5001` | Dashboard loads with no CORS errors in the browser console |
| 6 | Generator can send | `python -m scripts.generate_swifts --scenario demo --dry-run` | Prints 6 steps; nothing sent |
| 7 | Full rehearsal | `python -m scripts.generate_swifts --scenario demo` | All 6 outcomes in §2 appear; time the Gmail → Outlook delay |
| 8 | Clean starting view | Resolve leftover rehearsal items on the dashboard (or PATCH them `RESOLVED`) | Queue shows only what you want judges to see |
| 9 | Outlook folders | Check whether test mail lands in Inbox or Junk | Know where to point (the backend watches both) |

---

## 2. Live demo script

| # | Segment | You do | Judges see | Talking point | Time |
|---|---|---|---|---|---|
| 1 | **The problem** | Show the Outlook inbox | Dozens of emails, all with the same subject "SWIFT Incoming Funds Transfer message-…" | 200+ SWIFTs a day and 3,000+ a month. Analysts open each one by hand, which is slow and error-prone, and messages get missed | 1 min |
| 2 | **The solution** | Show the dashboard overview | KPI tiles, work queue, live activity feed, "Connected" status | The backend reads the mailbox every 10 s, understands each SWIFT, acts on it by the business rules, and only surfaces what needs a human | 1 min |
| 3 | **Amendment: priority alert** | Run `python -m scripts.generate_swifts --scenario demo`, press Enter at step 1 | About 10–25 s later: a **priority toast and alert chip** with reference, related reference, amount, sender BIC, and the "PLEASE AMEND … SHOULD READ … INSTEAD OF" text. The email stays **unread** | Amendments are prioritised automatically, with the key details extracted so the analyst can respond immediately | 1 min |
| 4 | **SGU: route to CST** | Press Enter (step 2) | The email turns **read** in Outlook. A **forward arrives in the CST Gmail**. The activity feed shows `ROUTED_CST`, and the "Routed to CST" tile increments | References starting with SGU belong to the CST team, so they're forwarded and closed with no human touch. SGU is detected in fields 20/21 *and* in free text | 1 min |
| 5 | **Cancellation: auto-close** | Press Enter (step 3, MT192) | The email turns **read**. The activity feed shows `AUTO_CLOSED` | Routine cancellations are marked read automatically | 30 s |
| 6 | **camt.056: held for analyst** | Press Enter (step 4) | The email stays **unread**. A **HIGH** item appears in the queue as `ACTION_REQUIRED` | The rules know the exception: camt.056 cancellations always need an analyst | 30 s |
| 7 | **FT callback: auto-reply** | Press Enter (step 5) | A **reply-all acknowledgement arrives** in vishnuprakash's Gmail. The row shows `RESPONDED`, and the email turns read | Callbacks with FT/INV references are answered automatically | 30 s |
| 8 | **ABA request: analyst queue** | Press Enter (step 6) | A new `ACTION_REQUIRED` row (ABA_REQUEST) | Requests for missing ABA routing numbers are tracked instead of lost in the inbox | 20 s |
| 9 | **Analyst workflow** | On the amendment: click **Start**, then **Resolve** | The status changes, the item leaves the open queue, and tiles update live | The dashboard is the analyst's worklist, with every open item tracked to resolution | 40 s |
| 10 | **Key extracts and explainability** | Open the camt.056 or amendment detail | Message type (MT/MX), payment reference, related reference, amount, BICs, business purpose, plus **"Why this category"**: the reason and the matched keywords | Every decision is explained. It's not a black box | 40 s |
| 11 | **Audit trail** | Open the Activity page | Every email processed, including the non-SWIFT ones (left untouched), with outcome, completed steps and timestamps | Full audit trail. Non-SWIFT mail is never modified | 30 s |
| 12 | **Volume** (optional) | Run `python -m scripts.generate_swifts --interval 8` (Ctrl-C after a minute) | Tiles counting up, feed scrolling, alerts popping | Handles the 200+/day volume continuously | 1 min |

---

## 3. Requirement coverage

Point to this table if the judges ask "does it do X?"

| Requirement from the brief | Where it's shown | Demo step |
|---|---|---|
| Identify SGU references and route to the CST team / mark read | Forward in CST Gmail, `ROUTED_CST` | 4 |
| Identify and classify cancellation messages | `CANCELLATION` category | 5, 6 |
| Mark cancellations read, **except camt.056** | MT192 auto-closed; camt.056 left unread and queued HIGH | 5, 6 |
| Identify amendments and route for priority action, with an alert to the frontend | Priority toast and alert strip with key attributes | 3 |
| Identify and respond to FT/INV callbacks | Reply-all acknowledgement, `RESPONDED` | 7 |
| Extract message type, payment reference, business purpose, request category | Detail view: key extracts | 10 |
| Store action-required SWIFTs keyed by reference, shown in real time | Queue updates live, without a reload | 3, 6, 8, 9 |
| Track exceptions and action-required messages | Queue plus statuses (In progress / Resolved) | 8, 9 |
| NLP with built-in Python libraries only | Classifier uses only the standard library (`re`, `difflib`, `unicodedata`) | Q&A |
| Script that continuously mails dummy SWIFTs | `scripts/generate_swifts.py` (`--scenario demo`, `--interval`) | 3–8, 12 |
| FastAPI + SQLite backend, Flask frontend | Architecture slide / `/docs` | 2 |

---

## 4. Points to make in Q&A

| Topic | Point |
|---|---|
| Robustness | Real SWIFT emails arrive as OCR'd screenshots: misread characters (`MpGPSMai1`, `USDO,`), Greek look-alike letters (`PAYMΕΝΤ`) and broken tags (`:130:` for `:13C:`). A normalizer repairs these before parsing. |
| Safety | Every email is actioned **exactly once**, even across crashes, retries and overlapping runs (step-level progress plus a run lock). Weak evidence never auto-closes a message; it goes to an analyst instead. |
| Rollout | `ACTIONS_ENABLED=false` gives a dry run that classifies and records everything without touching the mailbox. |
| Explainability | Each decision stores a plain-English reason and the matched keywords. |
| Testing | 416 automated tests, including the real mailbox emails as fixtures and a round-trip of every synthetic SWIFT type. |
| Configurability | The camt types that need an analyst (`CANCELLATION_ACTION_MX_TYPES`), poll interval, folders and CST mailbox are all settings. |
| Offline development | `scripts/seed_demo_data.py` fills the dashboard with realistic data through the real pipeline, with no mailbox needed. |

---

## 5. If something goes wrong

| Problem | Do this |
|---|---|
| Email slow to arrive (Gmail → Outlook) | Keep talking through the previous step. Before starting, run `--interval 20` in the background so there's always fresh activity |
| Dashboard not updating | Check the backend terminal for `poll complete` lines. Click **Check now** (`POST /api/process/run`) |
| "Not connected" banner | `python -m app.cli login`, sign in as MTheadsYI@outlook.com. The next poll picks it up, with no restart needed |
| Generator: "Gmail rejected the login" | Check `GMAIL_APP_PASSWORD` in `.env` (16-character app password) |
| Mail landed in Junk | Fine. The backend polls Junk too. Show it there in Outlook |
| Frontend broken | Use `http://localhost:8000/docs`: run `/api/swifts/alerts`, `/api/swifts/metrics` and `/api/process/log` live |
| No mailbox or network at all | Offline fallback: `python -m scripts.seed_demo_data --reset --db data/demo.db` and `--live`, with the backend started with `DATABASE_PATH=data/demo.db POLLER_ENABLED=false` |
| Sending limits | Don't leave the generator running for hours beforehand. Gmail allows about 500 emails a day, and each SGU or callback also triggers an outbound email from Outlook |
