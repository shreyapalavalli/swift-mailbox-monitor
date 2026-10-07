# SWIFT Mailbox Monitor Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI + SQLite backend that polls the SWIFT mailbox through Microsoft Graph, parses and classifies each SWIFT email with standard-library NLP, carries out the business-rule action (forward to CST, mark as read, auto-reply, or hold for an analyst), and stores action-required SWIFTs keyed by reference for a Flask dashboard. A separate script generates realistic dummy SWIFTs into the mailbox.

**Architecture:** The pipeline is `GraphMailService` (I/O) → `normalizer` → `parser` → `classifier` → `rules` (pure functions, no I/O) → `SwiftProcessor` (carries out the Graph actions, writes to `SwiftRepository`). An asyncio poller in the FastAPI lifespan calls `SwiftProcessor.run_once()` every N seconds. The dashboard API reads SQLite only, so it never waits on Graph.

**Tech Stack:** Python 3.14 (`.venv`), FastAPI 0.142, msal 1.39 (persistent token cache), httpx 0.28, stdlib `sqlite3`, stdlib NLP (`re`, `unicodedata`, `difflib`), stdlib `smtplib` for the generator, pytest 9.

**Spec:** `prompts/backend-prompt.md`, plus the **Decisions** section below (taken from the mailbox exploration on 2026-10-07 and the user's answers).

## Global Constraints

- Mailbox: `MTheadsYI@outlook.com` (personal Outlook.com). Authority `GRAPH_TENANT_ID=consumers`, `SWIFT_MAILBOX=me`.
- CST team mailbox (SGU routing target): `shreyapalavalli@gmail.com`.
- Generator sends from `vishnuprakash156@gmail.com` to `MTheadsYI@outlook.com`.
- NLP uses **only the Python standard library** (`re`, `unicodedata`, `difflib`, `collections`, `string`). No nltk, spaCy or scikit-learn.
- DB is SQLite through stdlib `sqlite3`. Action-required SWIFTs are keyed by **reference**.
- Non-SWIFT emails are never modified (not marked as read, not moved).
- camt.056 is never auto-actioned. It always waits for an analyst.
- Graph scopes: `Mail.ReadWrite Mail.Send User.Read` (+ `offline_access`, which MSAL adds itself).
- Secrets (`.token_cache.json`, `data/`, `GMAIL_APP_PASSWORD`) stay out of git.
- Run tests with `.venv/bin/pytest`.

## Decisions (from mailbox exploration and user answers)

1. **Bodies are OCR'd screenshots.** They contain `MpGPSMai1` for `MpGPSMail`, `USDO,` for `USD0,`, `:130:`/`:328:` for `:13C:`/`:32B:`, Greek homoglyphs (`PAYMΕΝΤ`, `Ν.Α.`) and shuffled label/value order. The MX sample has no line breaks at all. Normalize before parsing.
2. **Subjects are fixed** (`SWIFT Incoming Funds Transfer message-…MpGPSMail-NNNN-NNNNNN`, `SWIFT Incoming MX message-…MpBroadcastEMX-…`), so classification uses the body. A message is SWIFT if the subject starts with `SWIFT Incoming` **or** the body has `Swift Output:` / `MX Output:`.
3. **SGU** is detected in field 20, field 21 **or anywhere in the narrative** (example `mt199_sgu_in_narrative`).
4. **Unmatched SWIFTs** (e.g. the MT298 CLS schedule) are stored as category `OTHER`, status `ACTION_REQUIRED`, and left unread.
5. **Cancellation:** every cancellation is marked as read except MX types listed in `CANCELLATION_ACTION_MX_TYPES` (default `camt.056`). The user's sample is **camt.058**, so it is auto-marked as read under this default. Flag this in the demo.
6. **Callback:** a callback request whose references include one starting with `FT` or `INV` (containing at least one digit) gets a **reply-all** acknowledgement, is marked as read, and is stored with status `RESPONDED`. A callback without an FT/INV reference → `ACTION_REQUIRED`.
7. **Amendment** → stored with status `PRIORITY`, priority `HIGH`, left unread, and exposed on `/api/swifts/alerts`.
8. **SGU** → forwarded to CST, then marked as read. Audit row only (not on the dashboard list).
9. **Rule precedence:** not SWIFT → SGU → cancellation → amendment → callback → ABA → other.
10. **Reference key:** field 20, else MX `SWIFT Reference`, else the subject mail id (`MpGPSMail-5505-000001`). Upsert, latest wins.
11. **Missing examples:** there are no amendment or FT/INV callback examples. These, plus camt.056, MT192 and ABA, are synthesized (Task 12) in the same layout as the real ones.
12. **Folders:** poll `inbox` and `junkemail`. Gmail→Outlook test mail can land in Junk, and the SWIFT filter keeps junk noise untouched.
13. **Auth:** delegated with a persistent MSAL cache. One-time `python -m app.cli login` (device code) or browser `/auth/login`. After that the poller refreshes tokens silently, including across restarts.
14. **Frontend:** Flask is out of scope here (next plan). This plan fixes the API contract and CORS for `http://localhost:5000`.

## Review Focus

1. **Same email seen on every poll** (ACTION_REQUIRED mail stays unread) → it must be processed exactly once, with no duplicate replies or forwards. Test: `test_run_once_twice_acts_once` (Task 9).
2. **Graph fails halfway** (forward OK, mark-read 500) → record `FAILED` with `completed_steps="FORWARDED"`. The retry only marks as read and never forwards again. Test: `test_partial_failure_retry_skips_completed_steps` (Task 9).
3. **Not signed in or refresh token expired during a poll** → the poller logs and sleeps, without crashing or writing FAILED rows. Test: `test_poller_survives_signin_required` (Task 10).
4. **Body shape varies** (collapsed MX text with no newlines; HTML if the Prefer header is lost) → the parser still extracts fields, and the mail service always sends `Prefer: outlook.body-content-type="text"`. Tests: `test_parse_mx_collapsed`, `test_fetch_unread_requests_text_body` (Tasks 3, 5).
5. **Same reference arrives twice** (amendment, then a later message with the same field 20) → upsert updates category/status/updated_at, one row. Test: `test_upsert_same_reference_updates` (Task 8).

---

## File Structure

```
app/
  config/settings.py          MODIFY  new settings
  graph/auth_service.py       MODIFY  persistent token cache, device-code login
  graph/graph_client.py       MODIFY  post(), injectable transport, shared error logging
  graph/mail_service.py       MODIFY  text bodies, folders, forward, reply_all
  models/email_message.py     MODIFY  + folder
  swift/__init__.py           CREATE
  swift/normalizer.py         CREATE  OCR/homoglyph cleanup
  swift/parser.py             CREATE  ParsedSwift extraction
  swift/classifier.py         CREATE  stdlib-NLP category scoring
  swift/rules.py              CREATE  business rules → Decision
  db/__init__.py              CREATE
  db/repository.py            CREATE  sqlite schema + SwiftRepository
  services/__init__.py        CREATE
  services/processor.py       CREATE  SwiftProcessor
  services/poller.py          CREATE  asyncio loop
  api/swift_routes.py         CREATE  dashboard API
  api/mail_routes.py          MODIFY  use shared service instances
  dependencies.py             CREATE  singletons (auth, mail, repo, processor)
  cli.py                      CREATE  `python -m app.cli login|run-once`
  main.py                     MODIFY  lifespan, CORS, routers
scripts/
  __init__.py                 CREATE
  swift_samples.py            CREATE  synthetic SWIFT templates
  generate_swifts.py          CREATE  continuous Gmail SMTP sender
tests/
  conftest.py                 CREATE  env isolation, fixture loader
  fixtures/emails/*.json      EXISTS  4 real mailbox emails, 1 non-SWIFT, 1 MX sample
  test_settings.py, test_graph_client.py, test_mail_service.py (MODIFY),
  test_normalizer.py, test_parser.py, test_classifier.py, test_rules.py,
  test_repository.py, test_processor.py, test_poller.py, test_swift_api.py,
  test_swift_samples.py
```

---

### Task 1: Settings and test isolation

**Files:**
- Modify: `app/config/settings.py`
- Modify: `.gitignore` (add `.token_cache.json`, `data/`)
- Create: `tests/conftest.py`, `tests/test_settings.py`

**Interfaces:**
- Produces: `settings` with the new fields below, `settings.cancellation_action_mx_type_list -> list[str]`, `settings.poll_folder_list -> list[str]`. In `tests/conftest.py`: a `load_fixture(name) -> dict` pytest fixture that reads `tests/fixtures/emails/<name>.json`; a plain helper `subject_body(fixture: dict) -> dict` returning `{"subject": ..., "body": ...}`; and `FakeAuth` (Task 2) once it exists.

New fields (env name = upper-case field name):

| field | default |
|---|---|
| `graph_scopes` | `"Mail.ReadWrite Mail.Send User.Read"` |
| `token_cache_path` | `".token_cache.json"` |
| `database_path` | `"data/swift_monitor.db"` |
| `cst_mailbox` | `"shreyapalavalli@gmail.com"` |
| `cancellation_action_mx_types` | `"camt.056"` (comma-separated) |
| `poll_folders` | `"inbox,junkemail"` |
| `poll_interval_seconds` | `30` |
| `poller_enabled` | `True` |
| `frontend_origin` | `"http://localhost:5000"` |

- [ ] **Step 1: Write the failing tests.** `conftest.py` sets `os.environ` **before any `app` import**: `GRAPH_TENANT_ID=consumers`, `GRAPH_CLIENT_ID=test-client`, `SWIFT_MAILBOX=me`, `TOKEN_CACHE_PATH=<tmp>/cache.json`, `DATABASE_PATH=<tmp>/test.db`, `POLLER_ENABLED=false`. Use `tempfile.mkdtemp()` at module import.

```python
def test_defaults_parse_lists():
    from app.config.settings import settings
    assert settings.cancellation_action_mx_type_list == ["camt.056"]
    assert settings.poll_folder_list == ["inbox", "junkemail"]
    assert "Mail.Send" in settings.graph_scope_list
    assert settings.cst_mailbox == "shreyapalavalli@gmail.com"
```

- [ ] **Step 2:** `.venv/bin/pytest tests/test_settings.py -v` → FAIL (`AttributeError`).
- [ ] **Step 3:** Add the fields and the two list properties (split on `,`, strip, drop empties, lower-case the MX types).
- [ ] **Step 4:** `.venv/bin/pytest -v` → all PASS (including the existing `test_mail_service.py`).
- [ ] **Step 5:** Commit `feat: add monitor settings and test isolation`.

---

### Task 2: Persistent auth and Graph client POST

**Files:**
- Modify: `app/graph/auth_service.py`, `app/graph/graph_client.py`
- Create: `app/cli.py`, `tests/test_graph_client.py`
- Modify: `tests/test_mail_service.py` (keep the existing 2 tests passing)

**Interfaces:**
- Produces:
  - `GraphAuthService(cache_path: str | None = None)`. It loads `msal.SerializableTokenCache` from `cache_path` (default `settings.token_cache_path`) and sets `self._account` to the first cached account. It writes the cache back (`umask`-safe, mode `0o600`) whenever `cache.has_state_changed` after any acquire. `is_authenticated` is now `True` when an access token is valid **or** a cached account exists.
  - `GraphAuthService.login_device_flow(echo: Callable[[str], None] = print) -> str`: runs `initiate_device_flow` → `echo(flow["message"])` → `acquire_token_by_device_flow`, and returns the signed-in username. Raises `RuntimeError` on error.
  - `GraphClient(auth_service: GraphAuthService | None = None, transport: httpx.AsyncBaseTransport | None = None)`, with `get(url, params=None, headers=None) -> dict`, `patch(url, data) -> None` and `post(url, data) -> None`. Error logging moves into one `_raise_for_status(response)` helper.
  - `app/cli.py`: `python -m app.cli login` (device flow) and `python -m app.cli run-once` (calls `processor.run_once()` from Task 9 and prints the summary; wire it in Task 9).

- [ ] **Step 1: Write the failing tests**

```python
class FakeAuth:
    async def get_access_token(self): return "tok"

def test_post_sends_bearer_and_json():
    seen = {}
    def handler(req):
        seen["auth"] = req.headers["authorization"]; seen["body"] = json.loads(req.content)
        return httpx.Response(202)
    client = GraphClient(auth_service=FakeAuth(), transport=httpx.MockTransport(handler))
    asyncio.run(client.post("https://graph.test/x", {"comment": "hi"}))
    assert seen == {"auth": "Bearer tok", "body": {"comment": "hi"}}

def test_post_raises_on_4xx():
    client = GraphClient(auth_service=FakeAuth(), transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.post("https://graph.test/x", {}))

def test_cache_with_no_file_is_signed_out(tmp_path):
    assert GraphAuthService(cache_path=str(tmp_path / "none.json")).is_authenticated is False
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement as in Interfaces. `get` merges any extra `headers` over the defaults.
- [ ] **Step 4:** `.venv/bin/pytest -v` → PASS.
- [ ] **Step 5: Manual check** (needs the user): `.venv/bin/python -m app.cli login`, sign in as MTheadsYI@outlook.com, then confirm `.token_cache.json` exists and `git status` doesn't list it.
- [ ] **Step 6:** Commit `feat: persistent MSAL cache, device login CLI, graph POST`.

---

### Task 3: Mail service actions

**Files:**
- Modify: `app/graph/mail_service.py`, `app/models/email_message.py`
- Modify: `tests/test_mail_service.py`

**Interfaces:**
- Consumes: `GraphClient.get/patch/post` (Task 2).
- Produces:
  - `EmailMessage.folder: str | None = None`.
  - `GraphMailService(graph_client: GraphClient | None = None)`.
  - `fetch_unread_messages(folder: str = "inbox", top: int = 50) -> list[EmailMessage]`: URL `/{mailbox}/mailFolders/{folder}/messages`, `$filter=isRead eq false`, and header `Prefer: outlook.body-content-type="text"`. Sets `folder` on each message.
  - `forward_message(message_id: str, to_address: str, comment: str) -> None`: `POST /{mailbox}/messages/{id}/forward` with `{"comment": comment, "toRecipients": [{"emailAddress": {"address": to_address}}]}`.
  - `reply_all(message_id: str, comment: str) -> None`: `POST /{mailbox}/messages/{id}/replyAll` with `{"comment": comment}`.
  - `mark_as_read` stays unchanged. `fetch_messages`/`fetch_message_by_id` also send the Prefer header.
  - Message ids go through `quote(id, safe='')` in every URL.

- [ ] **Step 1: Write the failing tests** (use `httpx.MockTransport` through `GraphClient(transport=…)`, and `FakeAuth` from Task 2 moved into `conftest.py`)

```python
def test_fetch_unread_requests_text_body(): ...
    # assert request.headers["prefer"] == 'outlook.body-content-type="text"'
    # assert "/me/mailFolders/junkemail/messages" in request.url.path
    # assert result[0].folder == "junkemail"
def test_forward_posts_recipient(): ...
    # assert path endswith "/forward" and body["toRecipients"][0]["emailAddress"]["address"] == "shreyapalavalli@gmail.com"
def test_reply_all_posts_comment(): ...
    # assert path endswith "/replyAll" and body == {"comment": "ack"}
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: mail service forward, replyAll, text bodies per folder`.

---

### Task 4: Normalizer

**Files:** Create `app/swift/__init__.py`, `app/swift/normalizer.py`, `tests/test_normalizer.py`

**Interfaces:**
- Produces: `normalize_text(raw: str) -> str`.

Rules, in order:
1. `unicodedata.normalize("NFKC")`.
2. Map Greek and Cyrillic look-alikes to Latin (`ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ`→`ABEZHIKMNOPTYX`, Cyrillic `АВЕКМНОРСТХ`→`ABEKMHOPCTX`, plus lower-case `аеорсх`→`aeopcx`).
3. `\r\n`→`\n`, and collapse runs of blank lines to one `\n`.
4. `MpGPSMai1`→`MpGPSMail`.
5. MT tag repair: `:130:`→`:13C:`, `:328:`→`:32B:`.
6. Inside a `:32B:` value only, after the 3-letter currency, replace `O`→`0` in the amount.

Never swap O/0 globally.

- [ ] **Step 1: Write the failing tests**

```python
def test_greek_homoglyphs_become_latin():
    assert normalize_text("PAYMΕΝΤ Ν.Α.") == "PAYMENT N.A."
def test_ocr_mail_id_and_tags():
    out = normalize_text("MpGPSMai1-5505\r\n\r\n:130:/CLSTIME/1100\r\n:328:USDO,")
    assert out == "MpGPSMail-5505\n:13C:/CLSTIME/1100\n:32B:USD0,"
def test_letter_o_outside_amount_untouched():
    assert normalize_text("SOGEUS33XXX :32B:USD315071,79") == "SOGEUS33XXX :32B:USD315071,79"
```

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: OCR-tolerant SWIFT text normalizer`.

---

### Task 5: Parser

**Files:** Create `app/swift/parser.py`, `tests/test_parser.py`

**Interfaces:**
- Consumes: `normalize_text` (Task 4).
- Produces: `parse_swift(subject: str | None, body: str | None) -> ParsedSwift`, a frozen dataclass:

```python
@dataclass(frozen=True)
class ParsedSwift:
    is_swift: bool
    format: str                      # "MT" | "MX" | "UNKNOWN"
    message_type: str | None         # "MT199", "MT298", "camt.058.001.08"
    mx_family: str | None            # "camt.058"
    sub_message_type: str | None     # field 12, "211"
    transaction_reference: str | None  # field 20
    related_reference: str | None      # field 21
    swift_reference: str | None        # MX "SWIFT Reference"
    mail_id: str | None              # "MpGPSMail-5505-000001" / "MpBroadcastEMX-1894-000001" from subject
    sender_bic: str | None
    receiver_bic: str | None
    currency: str | None
    amount: Decimal | None
    narrative: str                   # 79 / 77E text; for MX, the whole normalized body
    references: tuple[str, ...]      # SGU…, FT…, INV… tokens from 20, 21 and narrative, in order, deduped
    text: str                        # full normalized body (classifier input)

    @property
    def reference(self) -> str | None:  # Decision 10
```

Regex anchors (on normalized text, `\s*` across newlines, case-insensitive labels):
- MT type: `Swift\s+Output\s*:\s*FIN\s+(\d{3})`. MX: `MX\s+Output\s*:\s*([a-z]{4}\.\d{3}\.\d{3}\.\d{2})`.
- Field 20/21/12: `\b20:\s*Transaction Reference Number\s+(\S+)`, `\b21:\s*Related Reference\s+(\S+)`, `\b12:\s*Sub-Message Type\s+(\d{3})`. Also accept raw `:20:`/`:21:` lines.
- BIC: `Sender\s*:\s*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b` (same for Receiver).
- Narrative: from `79: Narrative` or `77E: Proprietary Message` up to `{CHK:` or `Message Trailer`.
- MX SWIFT Reference: value up to the next known label (`SWIFT Request Reference|CBT Reference|Store-and-forward|$`), because the sample has no whitespace between labels.
- Amount: first non-zero `:32B:([A-Z]{3})([\d,.]+)` (SWIFT comma decimal), else narrative `\b(USD|EUR|GBP|CHF|JPY)\s?([\d,]*\d\.\d{2})\b`.
- References: `\bSGU(?=[A-Z0-9-]*\d)[A-Z0-9-]{5,}`, `\b(?:FT|INV)[-/]?(?=[A-Z0-9/-]*\d)[A-Z0-9/-]{5,}`. The digit lookahead keeps `INVESTIGATIONS` and `SWIFT` out.

- [ ] **Step 1: Write the failing tests** (values pinned from the real fixtures)

```python
@pytest.mark.parametrize("name,expected", [
  ("mt298_cls_schedule", dict(message_type="MT298", sub_message_type="211", transaction_reference="RPIS20260908",
        sender_bic="SOGEFRPPCLS", receiver_bic="SOGEUS33XXX", currency="USD", amount=Decimal("315071.79"),
        mail_id="MpGPSMail-5505-000001")),
  ("mt199_return_funds_cancellation", dict(message_type="MT199", transaction_reference="0435825000432026",
        related_reference="043586750036171H", sender_bic="SOGEFRPPXXX", references=())),
  ("mt199_sgu_related_ref", dict(transaction_reference="WFW260907-001017", related_reference="SGU260903-000033",
        sender_bic="WFBIUS6SXXX", references=("SGU260903-000033",))),
  ("mt199_sgu_in_narrative", dict(transaction_reference="0433924700132026", related_reference="04339674028730PU",
        currency="USD", amount=Decimal("9843.75"), references=("SGU260902-000054",))),
])
def test_parse_real_fixtures(load_fixture, name, expected): ...

def test_parse_mx_collapsed(load_fixture):
    p = parse_swift(**subject_body(load_fixture("mx_camt058_cancellation_notice")))
    assert (p.format, p.message_type, p.mx_family) == ("MX", "camt.058.001.08", "camt.058")
    assert p.swift_reference == "swi04003-2026-09-08T06:43:03.23847.2373755Z"
    assert p.reference == p.swift_reference

def test_non_swift_is_flagged(load_fixture):
    assert parse_swift(**subject_body(load_fixture("non_swift_ms_signin"))).is_swift is False
```

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: SWIFT MT/MX parser`.

---

### Task 6: Classifier (stdlib NLP)

**Files:** Create `app/swift/classifier.py`, `tests/test_classifier.py`

**Interfaces:**
- Consumes: `ParsedSwift` (Task 5).
- Produces: `class Category(str, Enum): CANCELLATION, AMENDMENT, CALLBACK, ABA_REQUEST, OTHER`. Also `classify(parsed: ParsedSwift) -> Classification`, where `Classification(category: Category, confidence: float, matched_terms: tuple[str, ...], business_purpose: str | None)` is a frozen dataclass.

Method:
1. Tokenize `parsed.narrative` (or the whole text for MX) with `re.findall(r"[A-Z][A-Z'-]+", text.upper())`.
2. Score each category: phrase hits (regex on the upper-cased text) + token hits (exact, or `difflib.SequenceMatcher(None, tok, term).ratio() >= 0.85` for terms of 5+ characters, which absorbs OCR typos such as `CANCELATION`) + a type prior.
3. Best score ≥ `2.0` wins. Otherwise `OTHER`. `confidence = best / total` (0 if total is 0). Break ties in the order CANCELLATION > AMENDMENT > CALLBACK > ABA_REQUEST.

Lexicon (weights):

| Category | Phrases | Tokens | Type prior (+5) |
|---|---|---|---|
| CANCELLATION | `RETURN THE FUNDS` 3, `RETURN OF FUNDS` 3, `REQUEST FOR CANCELLATION` 3, `PLEASE CANCEL` 3, `STOP PAYMENT` 3, `PAYER'S REQUEST` 1 | `CANCEL` `CANCELLATION` `CANCELLED` `RECALL` `REVOKE` `REFUND` 2 | MT `192/292/992`, MX `camt.056`, `camt.058`, name contains `Cancellation` |
| AMENDMENT | `PLEASE AMEND` 3, `CHANGE THE BENEFICIARY` 3, `CORRECT THE BENEFICIARY` 3, `SHOULD READ` 2, `INSTEAD OF` 1 | `AMEND` `AMENDMENT` `AMENDED` 3, `MODIFY` 2, `REVISED` 1 | MX `camt.087` |
| CALLBACK | `CALL BACK` 3, `CONFIRM BY PHONE` 3, `VERIFY BY TELEPHONE` 3, `PHONE CONFIRMATION` 2 | `CALLBACK` 3, `TELEPHONE` 1 | — |
| ABA_REQUEST | `ROUTING NUMBER` 3, `ROUTING NO` 3, `VALID ABA` 3 | `ABA` 3, `FEDWIRE` 1 | — |

`business_purpose`: `PURPOSE OF PAYMENT[.:]?\s*(.+?)(?=\s+\d\.\s|$)`. Otherwise, for MX, the camel-case name after `_` split into words (`Notification To Receive Cancellation Advice`). Otherwise the first sentence of the narrative, at most 160 characters.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("name,category", [
  ("mt199_return_funds_cancellation", Category.CANCELLATION),
  ("mx_camt058_cancellation_notice", Category.CANCELLATION),
  ("mt298_cls_schedule", Category.OTHER),
  ("mt199_sgu_related_ref", Category.OTHER),     # SGU is handled by rules, not the classifier
])
def test_real_fixture_categories(load_fixture, name, category): ...

def test_ocr_typo_still_cancellation():
    assert classify(parsed_from_narrative("PLS PROCESS CANCELATION OF OUR PAYMNT")).category is Category.CANCELLATION
def test_amendment_phrase():
    assert classify(parsed_from_narrative("PLEASE AMEND FIELD 59 TO READ ACME LTD")).category is Category.AMENDMENT
def test_callback_phrase():
    assert classify(parsed_from_narrative("PLS CALL BACK TO CONFIRM FT26090811223")).category is Category.CALLBACK
def test_business_purpose_extracted(load_fixture):
    c = classify(parse_swift(**subject_body(load_fixture("mt199_sgu_in_narrative"))))
    assert c.business_purpose.startswith("CONSULTING")
def test_confirm_credited_is_not_callback():   # wording from the real mt199_sgu_in_narrative fixture
    assert classify(parsed_from_narrative("PLEASE CONFIRM US IF FUNDS ARE CREDITED")).category is Category.OTHER
```

(`parsed_from_narrative(text)` is a test helper that builds a `ParsedSwift` from an MT199 body wrapper.)

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: stdlib NLP SWIFT classifier`.

---

### Task 7: Rules engine

**Files:** Create `app/swift/rules.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: `ParsedSwift`, `Classification`, `Category`, and `settings.cancellation_action_mx_type_list`.
- Produces:
  - `class Action(str, Enum): IGNORE, FORWARD_TO_CST, MARK_READ, AUTO_REPLY, STORE_FOR_ANALYST`.
  - `Decision(action: Action, category: str, status: str, priority: str, reason: str)`, a frozen dataclass. `category` is a `Category` value or `"CST"` / `"NOT_SWIFT"`. `status` is one of `"IGNORED" | "AUTO_CLOSED" | "ROUTED_CST" | "RESPONDED" | "ACTION_REQUIRED" | "PRIORITY"`. `priority` is one of `"HIGH" | "NORMAL" | "LOW"`.
  - `decide(parsed: ParsedSwift, classification: Classification, action_mx_types: list[str]) -> Decision`.

Decision table (first match wins; Decision 9):

| # | Condition | action | status | priority |
|---|---|---|---|---|
| 1 | `not parsed.is_swift` | IGNORE | IGNORED | LOW |
| 2 | any ref in `references` starts with `SGU` | FORWARD_TO_CST | ROUTED_CST | NORMAL |
| 3 | CANCELLATION and `mx_family in action_mx_types` | STORE_FOR_ANALYST | ACTION_REQUIRED | HIGH |
| 4 | CANCELLATION | MARK_READ | AUTO_CLOSED | LOW |
| 5 | AMENDMENT | STORE_FOR_ANALYST | PRIORITY | HIGH |
| 6 | CALLBACK and an `FT`/`INV` ref present | AUTO_REPLY | RESPONDED | NORMAL |
| 7 | CALLBACK | STORE_FOR_ANALYST | ACTION_REQUIRED | NORMAL |
| 8 | ABA_REQUEST | STORE_FOR_ANALYST | ACTION_REQUIRED | NORMAL |
| 9 | OTHER | STORE_FOR_ANALYST | ACTION_REQUIRED | NORMAL |

`reason` is a short English sentence naming the rule, e.g. `"camt.056 cancellation requires analyst review"`.

- [ ] **Step 1: Write the failing tests.** One test per row. Also add the real-fixture end-to-end mapping:

```python
@pytest.mark.parametrize("name,action", [
  ("mt298_cls_schedule", Action.STORE_FOR_ANALYST),
  ("mt199_return_funds_cancellation", Action.MARK_READ),
  ("mt199_sgu_related_ref", Action.FORWARD_TO_CST),
  ("mt199_sgu_in_narrative", Action.FORWARD_TO_CST),
  ("mx_camt058_cancellation_notice", Action.MARK_READ),
  ("non_swift_ms_signin", Action.IGNORE),
])
def test_real_fixture_actions(load_fixture, name, action): ...

def test_sgu_beats_cancellation(): ...          # SGU ref + "PLEASE CANCEL" → FORWARD_TO_CST
def test_camt058_becomes_analyst_when_configured(): ...  # action_mx_types=["camt.056","camt.058"] → STORE_FOR_ANALYST
```

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: SWIFT business rules engine`.

---

### Task 8: SQLite repository

**Files:** Create `app/db/__init__.py`, `app/db/repository.py`, `tests/test_repository.py`

**Interfaces:**
- Produces: `SwiftRepository(db_path: str)`. It creates the parent dir, runs `init_schema()` in `__init__`, and opens a new `sqlite3` connection per call with `PRAGMA journal_mode=WAL` and `row_factory=sqlite3.Row`. Timestamps are ISO-8601 UTC strings.

Schema:

```sql
CREATE TABLE IF NOT EXISTS processed_messages (
  graph_message_id TEXT PRIMARY KEY, folder TEXT, received_at TEXT, subject TEXT, sender TEXT,
  is_swift INTEGER NOT NULL, reference TEXT, message_type TEXT, category TEXT, action TEXT,
  status TEXT, outcome TEXT NOT NULL,            -- 'DONE' | 'FAILED'
  completed_steps TEXT NOT NULL DEFAULT '',      -- comma list: FORWARDED, REPLIED, MARKED_READ, STORED
  error TEXT, attempts INTEGER NOT NULL DEFAULT 1, processed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS swift_actions (
  reference TEXT PRIMARY KEY, graph_message_id TEXT NOT NULL, received_at TEXT,
  format TEXT, message_type TEXT, related_reference TEXT, category TEXT NOT NULL,
  status TEXT NOT NULL, priority TEXT NOT NULL, sender_bic TEXT, receiver_bic TEXT,
  currency TEXT, amount TEXT, business_purpose TEXT, narrative TEXT,
  matched_terms TEXT, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_actions_updated ON swift_actions(updated_at);
CREATE INDEX IF NOT EXISTS ix_processed_at ON processed_messages(processed_at);
```

Methods:
- `get_processed(graph_message_id) -> dict | None`
- `record_processed(row: dict) -> None` (upsert; `attempts = attempts + 1` on conflict)
- `upsert_action(row: dict) -> None` (on conflict update every column except `created_at`)
- `list_actions(status: str | None = None, category: str | None = None, since: str | None = None, limit: int = 200) -> list[dict]` (`since` filters `updated_at > since`, ordered `updated_at DESC`)
- `get_action(reference) -> dict | None`
- `update_action_status(reference, status) -> bool`
- `list_processed(limit: int = 100) -> list[dict]`
- `metrics(day: str) -> dict`, where `day` is `YYYY-MM-DD` (UTC). The result has keys `processed_today`, `swift_today`, `by_category_today` (dict), `by_status_today` (dict), `open_action_required`, `open_priority`, `failed_open`, `last_processed_at`. The `*_today` keys come from `processed_messages` with `is_swift=1`. `open_*` counts come from `swift_actions` where status is `ACTION_REQUIRED` / `PRIORITY`.

- [ ] **Step 1: Write the failing tests** (use `tmp_path`)

```python
def test_upsert_same_reference_updates(tmp_path):
    repo = SwiftRepository(str(tmp_path / "t.db"))
    repo.upsert_action(action_row(reference="R1", status="PRIORITY", category="AMENDMENT"))
    first = repo.get_action("R1")
    repo.upsert_action(action_row(reference="R1", status="ACTION_REQUIRED", category="CANCELLATION"))
    row = repo.get_action("R1")
    assert (row["status"], row["category"]) == ("ACTION_REQUIRED", "CANCELLATION")
    assert row["created_at"] == first["created_at"] and len(repo.list_actions()) == 1

def test_record_processed_increments_attempts(tmp_path): ...   # FAILED then DONE → attempts == 2, outcome == "DONE"
def test_list_actions_since_filters(tmp_path): ...
def test_metrics_counts(tmp_path): ...  # 3 swift processed today (1 CST, 1 AUTO_CLOSED, 1 PRIORITY) + 1 non-swift → swift_today == 3, open_priority == 1
def test_update_status_unknown_reference_returns_false(tmp_path): ...
```

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: sqlite repository for processed and action-required SWIFTs`.

---

### Task 9: Processor

**Files:** Create `app/services/__init__.py`, `app/services/processor.py`, `app/dependencies.py`, `tests/test_processor.py`. Modify `app/cli.py` (wire `run-once`).

**Interfaces:**
- Consumes: `parse_swift`, `classify`, `decide`, `Action`, `SwiftRepository`, plus the `GraphMailService` methods from Task 3 (through a Protocol).
- Produces:
  - `class MailGateway(Protocol)` with `fetch_unread_messages(folder: str, top: int = 50)`, `mark_as_read(message_id)`, `forward_message(message_id, to_address, comment)`, `reply_all(message_id, comment)`, all `async`.
  - `SwiftProcessor(mail: MailGateway, repo: SwiftRepository, folders: list[str], cst_mailbox: str, action_mx_types: list[str])`.
  - `async process_message(msg: EmailMessage) -> dict`: returns the processed row.
  - `async run_once() -> dict`: returns `{"fetched": int, "processed": int, "skipped": int, "failed": int, "by_action": {action: count}}`.
  - `app/dependencies.py`: module-level singletons `auth_service`, `graph_client`, `mail_service`, `repository`, `processor`, built from `settings`. `mail_routes.py` switches to these so `/auth/login` and the poller share one token cache.

Behaviour:
- Skip a message whose `get_processed(id)["outcome"] == "DONE"`.
- When re-processing a `FAILED` row, skip any step already in its `completed_steps`.
- Step order per action:
  - FORWARD_TO_CST: `FORWARDED` → `MARKED_READ`
  - AUTO_REPLY: `REPLIED` → `MARKED_READ` → `STORED`
  - MARK_READ: `MARKED_READ`
  - STORE_FOR_ANALYST: `STORED`
  - IGNORE: no steps
- If any step raises `httpx.HTTPError`, record `outcome="FAILED"`, keep the steps that did complete, put `error=str(exc)[:500]`, and move on to the next message.
- The stored action row comes from the parsed + classified fields, with `matched_terms` JSON-encoded and `amount` stored as `str(Decimal)`.

Fixed text:
- Forward comment: `Auto-routed by SWIFT Mailbox Monitor: reference {ref} belongs to the CST team.`
- Reply text:

```
Dear Sir/Madam,

We acknowledge your callback request regarding reference {ref}. SGNY Operations will contact you by telephone to complete the verification.

Regards,
SGNY Payments Operations
```

`{ref}` is the first FT/INV reference for a reply, and the SGU reference for a forward.

- [ ] **Step 1: Write the failing tests** with a `FakeMail` that records calls and can be told to fail one method once.

```python
def test_run_once_routes_real_fixtures(tmp_path, load_fixture):
    # inbox: mt199_sgu_related_ref, mt199_return_funds_cancellation, mt298_cls_schedule, non_swift_ms_signin
    summary = asyncio.run(proc.run_once())
    assert fake.forwards == [("id-sgu", "shreyapalavalli@gmail.com")]
    assert set(fake.marked_read) == {"id-sgu", "id-cancel"}           # non-SWIFT and MT298 untouched
    assert repo.get_action("RPIS20260908")["status"] == "ACTION_REQUIRED"
    assert summary["by_action"] == {"FORWARD_TO_CST": 1, "MARK_READ": 1, "STORE_FOR_ANALYST": 1, "IGNORE": 1}

def test_run_once_twice_acts_once(...): ...    # second run: processed == 0, skipped == 4, no new forwards/replies
def test_partial_failure_retry_skips_completed_steps(...):
    # mark_as_read fails once for the SGU mail → FAILED, completed_steps == "FORWARDED"
    # second run → DONE, len(fake.forwards) == 1, attempts == 2
def test_callback_ft_replies_and_stores_responded(...): ...   # inline MT199 body: "PLS CALL BACK ... FT26090811223" → reply_all once, marked read, status RESPONDED
def test_camt056_left_unread_and_stored_high(...): ...        # inline MX body "MX Output: camt.056.001.08 ..." → not marked read, ACTION_REQUIRED/HIGH
```

- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** `.venv/bin/python -m app.cli run-once` against the live mailbox. Expect `fetched ≥ 4`, MT199 #3 marked as read, both SGU mails forwarded to shreyapalavalli@gmail.com and marked as read, MT298 left unread and stored. Check with the curl runbook (Appendix).
- [ ] **Step 6:** Commit `feat: SWIFT processor with idempotent, resumable actions`.

---

### Task 10: Poller and app lifespan

**Files:** Create `app/services/poller.py`, `tests/test_poller.py`. Modify `app/main.py`.

**Interfaces:**
- Consumes: `SwiftProcessor.run_once` and `dependencies.processor`.
- Produces: `async run_poller(processor, interval_seconds: float, stop: asyncio.Event) -> None`. It loops until `stop` is set and calls `run_once()`. On `RuntimeError` containing `"sign-in required"` it logs a warning (`logging.getLogger("swift.poller")`). Any other exception is logged with the traceback. The loop never exits on an error, and waits with `asyncio.wait_for(stop.wait(), interval)`.
- `main.py`: `lifespan` starts `run_poller` as a task when `settings.poller_enabled`, and sets `stop` and awaits the task on shutdown. Adds `CORSMiddleware(allow_origins=[settings.frontend_origin], allow_methods=["*"], allow_headers=["*"])` and includes `swift_routes.router`.

- [ ] **Step 1: Write the failing tests**

```python
def test_poller_survives_signin_required():
    proc = RaisingThenCountingProcessor(first=RuntimeError("Microsoft sign-in required. Visit /auth/login first."))
    stop = asyncio.Event()
    async def go():
        t = asyncio.create_task(run_poller(proc, 0.01, stop)); await asyncio.sleep(0.05); stop.set(); await t
    asyncio.run(go())
    assert proc.calls >= 2
```

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: background poller in FastAPI lifespan`.

---

### Task 11: Dashboard API

**Files:** Create `app/api/swift_routes.py`, `tests/test_swift_api.py`

**Interfaces:**
- Consumes: `dependencies.repository`, `dependencies.processor`. Tests override them with `app.dependency_overrides` via `Depends(get_repository)` / `Depends(get_processor)` defined in `app/dependencies.py`.
- Produces (the contract the Flask frontend relies on; JSON field names are the snake_case DB columns):

| Method | Path | Response |
|---|---|---|
| GET | `/api/swifts?status=&category=&since=&limit=` | `list[SwiftAction]` |
| GET | `/api/swifts/alerts?since=` | `list[SwiftAction]` where `status == "PRIORITY"` |
| GET | `/api/swifts/metrics` | the `metrics(today)` dict |
| GET | `/api/swifts/{reference}` | `SwiftAction`, or 404 |
| PATCH | `/api/swifts/{reference}` body `{"status": "IN_PROGRESS" \| "RESOLVED"}` | `SwiftAction`. 404 if unknown, 422 if any other status |
| POST | `/api/process/run` | the `run_once()` summary |
| GET | `/api/process/log?limit=` | `list[dict]` of processed rows |

`SwiftAction` is a pydantic model with every `swift_actions` column. `matched_terms` is decoded to `list[str]`. Declare the `/alerts` and `/metrics` routes **before** `/{reference}`. References contain `-`, `.` and `:`, so use `{reference:path}`.

- [ ] **Step 1: Write the failing tests** (`fastapi.testclient.TestClient`, repo on `tmp_path`, fake processor)

```python
def test_alerts_only_priority(client, repo): ...
def test_patch_status_validates(client, repo):
    assert client.patch("/api/swifts/R1", json={"status": "BOGUS"}).status_code == 422
    assert client.patch("/api/swifts/R1", json={"status": "RESOLVED"}).json()["status"] == "RESOLVED"
def test_get_mx_reference_with_colons(client, repo): ...  # "swi04003-2026-09-08T06:43:03.23847.2373755Z" → 200
def test_cors_header_for_frontend(client):
    r = client.get("/api/swifts", headers={"Origin": "http://localhost:5000"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5000"
```

- [ ] **Step 2–4:** fail → implement → pass. **Step 5:** Commit `feat: dashboard API for action-required SWIFTs, alerts, metrics`.

---

### Task 12: Synthetic SWIFT samples and continuous generator

**Files:** Create `scripts/__init__.py`, `scripts/swift_samples.py`, `scripts/generate_swifts.py`, `tests/test_swift_samples.py`. Add `GMAIL_APP_PASSWORD=` guidance to the README (Task 13).

**Interfaces:**
- Produces:
  - `KINDS = ("cancellation_mt192", "cancellation_return_mt199", "camt056", "camt058", "amendment", "callback_ft", "callback_inv", "aba_request", "sgu_reply", "cls_mt298")`.
  - `make_sample(kind: str, rng: random.Random, now: datetime) -> tuple[str, str]`: returns `(subject, body)`.
  - `generate_swifts.py` CLI: `python -m scripts.generate_swifts [--interval 60] [--count N] [--kinds a,b] [--dry-run]`. It loops forever by default, sending one random kind each interval with stdlib `smtplib.SMTP("smtp.gmail.com", 587)` + `starttls()` + `login(GENERATOR_SENDER, GMAIL_APP_PASSWORD)`. It reads `.env` through `python-dotenv`. Defaults: `GENERATOR_SENDER=vishnuprakash156@gmail.com`, `GENERATOR_RECIPIENT=MTheadsYI@outlook.com`. `--dry-run` prints instead of sending. Kind weights favour realism: cancellation 30%, sgu 25%, amendment 15%, callback 15%, other 15%.

Template rules:
- Copy the real layout lines (`Copy received from SWIFT`, `Message Output Reference: …`, `Swift Output: FIN 199 Free Format Message`, `Sender : …`, `20: Transaction Reference Number`, `21: Related Reference`, `79: Narrative`, `{CHK:…}`, `Message Trailer`, `PKI Signature: MAC-Equivalent`). Separate lines with `\r\n\r\n`, as in the real bodies.
- Subjects follow the real formats exactly: `SWIFT Incoming Funds Transfer message-{dd/mm/yy}-{HH.MM.SS}MpGPSMail-{4 digits}-{6 digits}`, and for MX `SWIFT Incoming MX message-{dd/mm/yy}-{HH.MM.SS}MpBroadcastEMX-{4}-{6}`.
- Amendment narrative example: `PLEASE AMEND OUR PAYMENT {trn} FOR USD {amt}. FIELD 59 BENEFICIARY SHOULD READ {name} INSTEAD OF {old}.`
- Callback narrative example: `RE YOUR REF {FT…|INV…}. PLS CALL BACK THE REMITTER TO CONFIRM PAYMENT DETAILS BEFORE RELEASE.`
- Add OCR noise to about 30% of samples (`l→1` in `MpGPSMail`, one Greek `Ε` in a word), so the normalizer is exercised live.

- [ ] **Step 1: Write the failing tests.** For every kind, round-trip through the real pipeline:

```python
EXPECTED = {"cancellation_mt192": Action.MARK_READ, "cancellation_return_mt199": Action.MARK_READ,
            "camt056": Action.STORE_FOR_ANALYST, "camt058": Action.MARK_READ, "amendment": Action.STORE_FOR_ANALYST,
            "callback_ft": Action.AUTO_REPLY, "callback_inv": Action.AUTO_REPLY, "aba_request": Action.STORE_FOR_ANALYST,
            "sgu_reply": Action.FORWARD_TO_CST, "cls_mt298": Action.STORE_FOR_ANALYST}
@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("kind", KINDS)
def test_sample_round_trips(kind, seed):
    subject, body = make_sample(kind, random.Random(seed), datetime(2026, 10, 7, 9, 30))
    p = parse_swift(subject, body); d = decide(p, classify(p), ["camt.056"])
    assert p.is_swift and p.reference and d.action is EXPECTED[kind]

def test_amendment_status_priority(): ...   # decision.status == "PRIORITY"
def test_dry_run_sends_nothing(monkeypatch, capsys): ...  # patch smtplib.SMTP to raise; --dry-run --count 2 → 2 subjects printed
```

- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Live check** (needs `GMAIL_APP_PASSWORD`; Gmail requires 2-Step Verification, then Google Account → Security → App passwords). Run `python -m scripts.generate_swifts --count 3 --interval 5`, then confirm the 3 messages appear in Inbox or Junk using the curl runbook.
- [ ] **Step 6:** Commit `feat: synthetic SWIFT generator over Gmail SMTP`.

---

### Task 13: End-to-end verification and README

**Files:** Modify `README.md` (macOS setup, `.env` keys, `app.cli login`, generator, API table, curl runbook).

- [ ] **Step 1:** `.venv/bin/pytest -v` → all PASS.
- [ ] **Step 2:** `uvicorn app.main:app --reload`. With the token cache present, the poller logs `run_once` summaries every 30s.
- [ ] **Step 3:** Run the generator `--count 10 --interval 10`. Within 2 poll cycles:
  - `GET /api/swifts/metrics` → `swift_today ≥ 10`
  - `GET /api/swifts/alerts` lists the amendments
  - shreyapalavalli@gmail.com receives the SGU forwards
  - vishnuprakash156@gmail.com receives the callback acknowledgements
- [ ] **Step 4:** Check with curl that the non-SWIFT Microsoft mails are still unread.
- [ ] **Step 5:** Commit `docs: setup, generator and verification runbook`.

---

## Appendix: Mailbox curl runbook (used on 2026-10-07)

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

Findings at that time: Inbox had 15 messages, 4 of them SWIFT (MT298 CLS; MT199 return-of-funds; MT199 with SGU in field 21; MT199 with SGU in the narrative). The other 11 were Microsoft account/marketing mail. Junk had 2 non-SWIFT messages.
