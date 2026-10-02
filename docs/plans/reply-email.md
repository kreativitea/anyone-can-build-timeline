Status: built on branch reply-email, awaiting merge

# Reply email

Planned against the `accounts` branch (`.claude/worktrees/accounts/with-backend/server.py`), and
against `replies.md`: a reply is a row in `posts` with a `parent_id`, saved by `save_reply`, and the
place for the email is the reply branch in `take_post`, after the `201` answer (`replies.md`,
"The hook for `reply-email`"). It also follows `japanese.md` section 3.4 (the words contract) and
uses `rate-limit.md`'s `LIMITS` table.

## 1. What it does

When someone replies to your post, Timeline makes an email for you: who replied, what they wrote,
and a link back to the timeline, in English and then in Japanese. You add your email address on the
page, and confirm it by opening a link from a confirm email. A switch turns reply emails off (and on
again) whenever you like. **Nothing is really sent yet:** the running server prints each email,
whole, in its terminal, in a frame that cannot be mistaken for a post's log line. Real sending is a
later plan (section 8).

## 2. Decisions (made by the owner)

**D1. Where the address is kept: a new table `emails`, at most one row per user.** *(approved)*
Removing your address is a `DELETE` of one row, like taking back a like. `users` is left alone, so
no collision with plans that change `users`, and the address sits away from the table every post
query joins, so it cannot slip into a post's JSON.

**D2. Where a person types it: an "Email" box shown only when signed in.** *(approved)* Sign-up
stays as `accounts` built it. Old users who claimed their name can add an address too.

**D3. The address is confirmed before any reply email is made for it.** *(approved)* Otherwise
anyone could type a stranger's address. The confirm email is printed in the terminal like every
other email; the person copies its link into the browser.

**D4. Sending lives in its own file, `with-backend/outbox.py`, with two kinds of outbox:
`ConsoleOutbox` and `KeptOutbox`.** *(approved)* Deciding to notify is a rule, so it is the
**model** (`reply_email_for`). Writing the email is the **view** (`reply_email_message`). Carrying
it out is neither: it decides nothing and reads no database. It is a door to the outside, like
`send_answer` for HTTP, but it runs on its own thread, so it does not belong in the controller
either. In its own file, a test swaps it for a fake in one argument, and the later real-sending plan
adds one class there and changes nothing else.

**D5. If carrying an email out fails: print one line and forget the email. No retry.**
*(approved)* The reply is already saved and shown; the email is an extra.

**D6. Development (and, for now, only) mode: print the whole email to the terminal.** *(approved)*

**D7. Reply emails are on when an address is first confirmed.** *(approved)* The switch turns them
off.

## 3. Design

### Words used here

- **Thread**: a second line of work running inside the same program at the same time.
- **Queue**: a waiting line. The controller puts an email at the back; the outbox's thread takes
  from the front.
- **Token**: a long random text that proves something, here that you can read the confirm email.

### Database: `upgrade_to_reply_email(connection)`

Written like `upgrade_to_accounts`: one transaction, `BEGIN` … `COMMIT`. The orchestrator gives the
`user_version` number. It only adds a table, so every old row is kept.

```sql
CREATE TABLE emails (
  user_id       INTEGER PRIMARY KEY REFERENCES users(id),  -- at most one address per person
  address       TEXT NOT NULL,
  confirmed     INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
  check_hash    TEXT UNIQUE,      -- the hash of the confirm link's token; NULL once confirmed
  check_sent_at INTEGER,          -- when the confirm email was made (seconds); the link lasts 24 hours
  reply_emails  INTEGER NOT NULL DEFAULT 1 CHECK (reply_emails IN (0, 1))
)
```

- `user_id` is the primary key, so the **database** refuses a second address for one person.
- The token is kept only as a hash (`hash_token`, from `accounts`), like a session token, so a copy
  of `timeline.db` cannot be used to confirm an address.
- The address is not unique: one person may own two accounts with one mailbox.
- The address is kept once, here, and never copied into another table.

### Model

Every refusal is a code, as `japanese.md` 3.4 says. New codes go at the end of `PROBLEMS`, under
`# reply-email`:

| Code | English |
|---|---|
| `email_empty` | The email address must not be empty. |
| `email_too_long` | The email address must be {limit} characters or fewer. |
| `email_not_valid` | That does not look like an email address. |
| `email_hidden` | The email address must not have hidden characters or line breaks. |
| `email_link_wrong` | This confirm link is wrong or too old. Add your address again. |
| `email_missing` | You have no email address saved. |

| Function | What it does |
|---|---|
| `check_email(address)` | Trims spaces. Raises `email_empty`; `email_too_long` (`limit=MAX_EMAIL`, 254); `email_hidden` (`HIDDEN_CHARACTERS`); `email_not_valid` if it does not match `EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")`. Returns the address. |
| `email_settings_for(db_path, user_id)` | The user's row in `emails`, or `None`. Only reads. |
| `set_email(db_path, user_id, address)` | `check_email`, then `use_allowance(db_path, "confirm_email", str(user_id))` (see "Rate limit" below), then makes a token (`secrets.token_urlsafe(32)`) and saves the address as *not confirmed* with the token's hash and `check_sent_at` (`INSERT … ON CONFLICT(user_id) DO UPDATE`). A new address is always unconfirmed again. Returns `(token, row)`. |
| `confirm_email(db_path, token)` | One `UPDATE emails SET confirmed = 1, check_hash = NULL WHERE check_hash = ? AND check_sent_at > ?` (now − `CONFIRM_HOURS` = 24 hours). `rowcount` 0 → `RuleBroken("email_link_wrong")`. One statement both looks and confirms, so a link works once. **It needs only the token, never a session** (see "Confirming" below). Returns the row. |
| `remove_email(db_path, user_id)` | `DELETE FROM emails WHERE user_id = ?`. `rowcount` 0 → `RuleBroken("email_missing")`. |
| `set_reply_emails(db_path, user_id, on)` | `UPDATE emails SET reply_emails = ? WHERE user_id = ?`. `rowcount` 0 → `RuleBroken("email_missing")`. Returns the row. |
| `reply_email_for(db_path, reply_id)` | **The rule that decides.** One `SELECT` from the reply, joined to its parent post, the parent's author, and `emails`. Returns one row (the reply's text and its author's two names; the parent's id and text; the address and display name of the parent's author), or `None`. `None` when: the post has no `parent_id`; the parent's author wrote the reply; the parent's author has no row in `emails`, or `confirmed = 0`, or `reply_emails = 0`. A missing row simply gives `None`. It only reads, and it does not touch `POSTS_WITH_AUTHORS`. |

**Rate limit.** Confirm emails are limited by one more row in `rate-limit`'s `LIMITS` table, not by
a mechanism of their own:

```python
LIMITS = {..., "confirm_email": (1, 300)}   # one confirm email per account per 5 minutes
```

plus its entry in `WHAT` (or whatever form the `too_fast` words take once `japanese` and
`rate-limit` are both merged). `set_email` calls `use_allowance` after `check_email`, so a refused
address is not counted. The `TooFast` it raises becomes a `429` through `rate-limit`'s `try … except
TooFast` around the `do_POST` dispatch, so `add_email` must be called inside that `try`. **If
`rate-limit` has not merged when this is built, the builder adds the `LIMITS` row and the
`use_allowance` line anyway, as part of building on top of `rate-limit`** (this plan then waits for
`rate-limit`; see section 5).

### Routes (controller)

Every route except confirming needs sign-in, through `signed_in_user()` (so `user_for_session`).
Every body is JSON, as `read_json` demands. A refusal goes through `send_problem` (`japanese` Part
A). The address appears **only** in these answers, to its owner. It is never in `/posts`, `/likes`,
or the post log line.

| Request | JSON in | Answer |
|---|---|---|
| `GET /email` | — | 200 `{"email": "aiko@example.com" or null, "confirmed": false, "reply_emails": true}` · 401 |
| `POST /email` | `{"email": "aiko@example.com"}` | 201, the same shape, `confirmed: false`; a confirm email is queued · 400 · 401 · 429 |
| `DELETE /email` | — | 200 `{"email": null, "confirmed": false, "reply_emails": false}` · 400 `email_missing` · 401 |
| `POST /email-confirmations` | `{"token": "…"}` | 200, the same shape, `confirmed: true` · 400 `email_link_wrong` |
| `POST /reply-emails` | `{}` | 200, the same shape, `reply_emails: true` · 400 `email_missing` · 401 |
| `DELETE /reply-emails` | — | 200, the same shape, `reply_emails: false` · 400 `email_missing` · 401 |

The method says what happens, as with likes: `POST /reply-emails` turns them on, `DELETE` turns
them off. The page never sends `true` or `false`, so the server never has to guess.

New controller methods (added): `show_email_settings`, `add_email`, `confirm_email_link` (named so
it does not hide the model's `confirm_email`), `drop_email`, `turn_reply_emails(on)`.

**Confirming.** The confirm link is `http://localhost:<port>/#confirm-email=<token>`. The person
copies it from the terminal into the browser. The page reads the token from the address and sends
it with `fetch` to `POST /email-confirmations`. The server finds the person **from the token
alone**. It must not need the `session` cookie: that cookie is `SameSite=Strict`, so a browser
does not send it on a visit that starts from a link in an email app, and a later real-sending plan
must still work. The token is after `#`, not `?`: the part after `#` is never sent to the server, so
it never appears in the server's request log.

**The hook into replies.** In `take_post`, in the reply branch that `replies` adds, after
`self.send_json(201, …)` and the log line, two lines:

```python
email = reply_email_for(self.server.db_path, row["id"])          # model: should we?
if email is not None:
    self.server.outbox.send_later(reply_email_message(email, self.server.base_url))  # view, then out
```

The answer has already gone to the page before the email is even made, and `send_later` only puts
it in a queue. So the reply request is never slower, and a broken outbox can never turn a saved
reply into an error.

### View

The email's words are **not** in `server.py`, because `japanese` keeps `server.py` free of Japanese
(and tests it). They are in a new file, `with-backend/email_words.py`: one dictionary,
`EMAIL_WORDS`, each entry with `en` and `ja`, written with `{names}` like `PROBLEMS`. Every email
has both languages, **English first, then Japanese** (`japanese.md` decision 6), because the server
does not know the reader's language. This is not translating for a reader: every reader gets the
same email. This branch writes both halves; the Japanese is read by a native speaker in `japanese`
Part B's check by hand.

| Key | English (Japanese follows in the same entry) |
|---|---|
| `reply_subject` | {display_name} (@{account_name}) replied to your post |
| `reply_body` | {display_name} (@{account_name}) replied to your post. Their reply: {reply} Your post: {post} See it: {link} To stop these emails, turn off "Email me when someone replies" on Timeline. |
| `confirm_subject` | Confirm your email address for Timeline |
| `confirm_body` | To confirm this address, copy this link into your browser: {link} The link works once, for 24 hours. If you did not ask for this, ignore this email. |

(The bodies are written on several lines in the file; the table shows them on one.)

| Function | What it gives |
|---|---|
| `both_languages(key, **values)` | The `en` text filled in, a blank line, then the `ja` text filled in. The subject joins the two with ` / `. |
| `email_settings_to_json(row)` | `{"email", "confirmed", "reply_emails"}`; for `None`, `null` / `false` / `false`. |
| `reply_email_message(row, base_url)` | An `email.message.EmailMessage`. **To:** the address. **Subject** and **body** from `reply_subject` and `reply_body`. The reply and the post are put in quotes with `json.dumps(…, ensure_ascii=False)`, as `post_to_log_line` does. The link is `<base_url>/#post-<parent id>`. Plain text only. |
| `confirm_email_message(address, token, base_url)` | The same shape, from `confirm_subject` and `confirm_body`, with the link `<base_url>/#confirm-email=<token>`. |

`EmailMessage` is kept even though nothing is sent: it refuses a line break inside a header, and
`accounts` already refuses line breaks in display names, so a name can never add a header such as a
second `To:`. The later real-sending plan can hand the same object to `smtplib` unchanged.

### Carrying it out: `with-backend/outbox.py` (new file)

Standard library only: `queue`, `threading`, `sys`.

```
class Outbox          one queue and one background thread (daemon=True). send_later(message)
                      puts the message in the queue and returns at once. The thread takes each
                      message and calls deliver(message). Any exception from deliver is caught:
                      one line is printed ("An email could not be printed: <reason>") and the
                      thread goes on to the next message. No retry (D5).
                      wait_until_sent() waits until the queue is empty (queue.join), for tests.
class ConsoleOutbox   the running server. deliver prints the whole email to its stream
                      (sys.stdout unless another is given), framed like this:

                      ==================== EMAIL (printed here, not sent) ====================
                      | To:      aiko@example.com
                      | Subject: Ben Sato (@ben) replied to your post / …
                      |
                      | Ben Sato (@ben) replied to your post.
                      | …
                      ============================= END OF EMAIL =============================

                      Every line inside the frame starts with "| ", so a post's text, which may
                      hold line breaks, can never fake the END line or a post log line (those
                      start with a time, "15:42  "). The headers are read decoded (msg["Subject"])
                      and the body with get_content(), so Japanese prints as Japanese, not as
                      encoded text. The whole block is one print(…, flush=True) call, so a post
                      log line printed at the same moment cannot land in the middle of it.
class KeptOutbox      for tests. deliver appends the message to a list, self.sent. Prints nothing.
```

**Starting the server.** `make_server(port, db_path, outbox=None)` sets `server.outbox` to the
outbox it is given, or **a `KeptOutbox` when it is given none**, and sets
`server.base_url = "http://localhost:" + str(port)`. Only the `if __name__ == "__main__":` block
passes `ConsoleOutbox()`, and prints one more start-up line: "Emails are printed here, not sent."
So every test, which calls `make_server` without an outbox, prints no emails and sends nothing.

### Page

Every visible word follows `japanese.md` 3.4: a key in `words.js` (at the end of `WORDS`, under
`// reply-email`, `en:` only; Part B adds `ja:`), shown with `data-words="…"` in `index.html` or
`say(…)` / `showStatus(…)` in `app.js`. The address itself is what a person wrote, so it is never a
key; it goes in with `textContent` or as a `{email}` value.

New keys: `email_heading` (Email), `email_label` (Your email address), `email_save` (Save),
`email_remove` (Remove), `email_state_none` (No email address saved.), `email_state_unconfirmed`
(Not confirmed yet. Open the link in the confirm email sent to {email}.), `email_state_confirmed`
(Confirmed: {email}), `reply_emails_label` (Email me when someone replies), `email_saved` (Saved.
Now open the link in the confirm email.), `email_confirmed` (Your email address is confirmed.),
`email_removed` (Your email address is removed.), `reply_emails_on` (Reply emails are on.),
`reply_emails_off` (Reply emails are off.). And the six `PROBLEMS` codes above, with exactly the
same English.

- `index.html`: inside `#signed-in`, after the post form, `<section id="email-settings">`: a heading;
  a form `#email-form` with `<input id="email" type="email" autocomplete="email">` and a **Save**
  button; a line `#email-state`; a **Remove** button `#email-remove`; and
  `<input type="checkbox" id="reply-emails">` with its label. Every word with `data-words`.
- `app.js`, new: `const MAX_EMAIL = 254;` and `const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;` (the same
  as the model); `emailProblem(address)` (returns a code, as the other `…Problem` functions do after
  `japanese`); `askEmailSettings()` (`GET /email`); `showEmailSettings(settings)`;
  `saveEmail(event)` (`POST /email`; on `429`, `holdForm(emailForm, answer.retry_after)` from
  `rate-limit`); `removeEmail()` (`DELETE /email`); `switchReplyEmails()` (`POST` or
  `DELETE /reply-emails`, chosen by the checkbox, as `pressHeart` chooses by the heart);
  `confirmEmailFromLink()`: if `location.hash` starts with `#confirm-email=`, it sends
  `POST /email-confirmations` with the token, shows `email_confirmed` or the problem, and removes
  the token from the address bar with `history.replaceState`. It works whether or not this window
  is signed in.
- `app.js`, changed: `showSignedIn` calls `askEmailSettings()` (one line); the start-up code at the
  bottom calls `confirmEmailFromLink()` (one line). A `401` from an email request calls
  `showSignedOut`, like the other requests.
- `style.css`: rules for `#email-settings` at the end, under `/* reply-email */`. The same lines at
  the end of `page-only/style.css`, which stays a copy.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/outbox.py` | new file: `Outbox`, `ConsoleOutbox`, `KeptOutbox` | add |
| `with-backend/email_words.py` | new file: `EMAIL_WORDS` (`en` and `ja`) | add |
| `with-backend/server.py` | imports: `from outbox import ConsoleOutbox, KeptOutbox`, `from email_words import EMAIL_WORDS`, `from email.message import EmailMessage` | change (3 lines) |
| `with-backend/server.py` | MODEL: `create_tables` (call the upgrade) | change (2 lines) |
| `with-backend/server.py` | MODEL: `upgrade_to_reply_email` | add |
| `with-backend/server.py` | MODEL: `MAX_EMAIL`, `EMAIL`, `CONFIRM_HOURS` | add |
| `with-backend/server.py` | MODEL: `PROBLEMS` (6 codes at the end, `# reply-email`) | add |
| `with-backend/server.py` | MODEL: `LIMITS` (`"confirm_email"` row) and its `WHAT` entry | change (1 entry each) |
| `with-backend/server.py` | MODEL: `check_email`, `email_settings_for`, `set_email`, `confirm_email`, `remove_email`, `set_reply_emails`, `reply_email_for` | add |
| `with-backend/server.py` | CONTROLLER: `do_GET` (`/email`), `do_POST` (path list and 3 branches, inside the `TooFast` `try`), `do_DELETE` (2 branches before the `/likes` check) | change |
| `with-backend/server.py` | CONTROLLER: `show_email_settings`, `add_email`, `confirm_email_link`, `drop_email`, `turn_reply_emails` | add |
| `with-backend/server.py` | CONTROLLER: `take_post`, reply branch (2 lines after the `201`) | change |
| `with-backend/server.py` | VIEW: `both_languages`, `email_settings_to_json`, `reply_email_message`, `confirm_email_message` | add |
| `with-backend/server.py` | `make_server` (`outbox=None`, `server.outbox`, `server.base_url`) and the `__main__` block (`ConsoleOutbox()`, one printed line) | change |
| `with-backend/words.js` | `WORDS`: 13 page keys and 6 problem codes at the end, `// reply-email`, `en:` only | add |
| `with-backend/app.js` | `MAX_EMAIL`, `EMAIL`, `emailProblem`, `askEmailSettings`, `showEmailSettings`, `saveEmail`, `removeEmail`, `switchReplyEmails`, `confirmEmailFromLink`, their event listeners | add |
| `with-backend/app.js` | `showSignedIn` (1 line); start-up code (1 line) | change |
| `with-backend/index.html` | `<section id="email-settings">` inside `#signed-in`, words by `data-words` | add |
| `with-backend/style.css`, `page-only/style.css` | `/* reply-email */` rules at the end | add |
| `with-backend/test_server.py` | new methods at the end of `ModelTests`, `RealServerTest`, `JourneyTest`, `PageAndServerAgreeTest`; new class `OutboxTests` at the end of the file | add |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (see 7) | add |

No change to `.gitignore` or the `Makefile`.

## 5. Depends on, and collides with

- **`accounts`** (depends): `user_for_session`, `signed_in_user`, `hash_token`, `HIDDEN_CHARACTERS`,
  and the JSON-only rule in `read_json`.
- **`replies`** (depends): `posts.parent_id`, `save_reply`, and the reply branch in `take_post`.
  If `replies` gives each post an anchor (`id="post-7"`), the email link opens at the right post;
  otherwise it opens the timeline.
- **`japanese` Part A** (depends): `Problem`, `PROBLEMS`, `send_problem`, `words.js`, `say`,
  `showStatus` with keys. Build after Part A. **Part B** then adds `ja:` for this plan's keys in
  `words.js`, and its native-speaker check reads `email_words.py` too.
- **`rate-limit`** (depends): `LIMITS`, `use_allowance`, `TooFast` → `429`, `holdForm`. Build after
  it. If it has not merged when this is built, the builder adds the `LIMITS` row and the
  `use_allowance` call anyway, on top of whatever `rate-limit` branch is current.
- **`block`** (collides, small): if A has blocked B, A should get no email when B replies. Whichever
  of the two merges second adds one condition to `reply_email_for` and one test.
- **`edit-delete`** (light): a reply deleted after its email was printed stays in that email. A
  deleted parent gives `reply_email_for` no row, so no email.
- **Routing.** Every plan with new routes collides in `do_GET` / `do_POST` / `do_DELETE` and
  `make_server`. The changes here are new branches only. One wording note for the orchestrator: the
  `delete_where` sentence ("You can only take back a like at /likes, or log out at /sessions")
  becomes incomplete once other `DELETE` routes exist; that is a one-line words fix for whoever
  owns it, not part of this plan.
- **Database.** Upgrade numbers are given by the orchestrator.

## 6. Tests

No test sends or prints a real email: `make_server` uses `KeptOutbox` unless told otherwise, and the
`ConsoleOutbox` tests give it an `io.StringIO` to print into.

**`ModelTests`** (new methods at the end)
- `check_email` accepts `aiko@example.com` and trims spaces; raises `email_empty`, `email_not_valid`
  (no `@`, a space), `email_hidden` (a line break), `email_too_long` with `limit` 254.
- `set_email` saves the address unconfirmed; the plain token is in no table, only its hash.
- `confirm_email` with the right token confirms; a wrong token, a token over 24 hours old, and the
  same token twice all raise `email_link_wrong`. It is given no user id: the token alone is enough.
- A second `set_email` within 5 minutes raises `TooFast`; after moving `clock` forward 301 seconds it
  works. A refused address is not counted.
- `remove_email` deletes the row; removing twice raises `email_missing`.
- `set_reply_emails` without an address raises `email_missing`.
- `reply_email_for`: `None` for a post that is not a reply; `None` when you reply to yourself; `None`
  with no address, with an unconfirmed address, and with reply emails off; one row with the right
  address, names and texts when all is well; `None` for a reply to an unclaimed old user's post.
- The upgrade keeps every old row and adds an empty `emails` table.
- View: `reply_email_message` has the right `To`; its subject and body have the English **before**
  the Japanese; the body holds the reply's text and the link. `confirm_email_message` has the token
  after `#`. A display name cannot add a header.
- `EMAIL_WORDS`: every entry has `en` and `ja`, neither empty, with the same `{names}`.

**`OutboxTests`** (new class at the end of the file)
- `ConsoleOutbox` prints the whole email between the two frame lines, and every line in between
  starts with `| `.
- A reply whose text holds a line break and a fake `END OF EMAIL` line: the printed block still has
  exactly one real END line, and the fake one starts with `| `.
- Japanese in the subject and body is printed as Japanese, not as encoded text.
- An outbox whose `deliver` raises prints one line and still delivers the next message.
- `make_server` with no outbox gives a `KeptOutbox`.

**`RealServerTest`** (new methods at the end)
- `POST /email` without a cookie gets 401; with a cookie, 201 and one message in `server.outbox.sent`.
- `POST /email-confirmations` with the right token and **no cookie** gets 200.
- The address is not in `GET /posts`.
- A reply sent while the outbox's `deliver` takes 2 seconds still gets its 201 in well under a
  second.

**`JourneyTest`** (new method at the end): Aiko signs up, `POST /email`; the test reads the token
out of the kept confirm email and sends `POST /email-confirmations` without a cookie; SQL shows
`confirmed = 1` and `check_hash IS NULL`. Ben replies to Aiko's post: exactly one email, to Aiko's
address. Aiko replies to her own post: no new email. Aiko sends `DELETE /reply-emails`; Ben replies
again: no new email. Aiko sends `DELETE /email`: the row is gone. After every step, the address is in
no answer except Aiko's own `GET /email`.

**`PageAndServerAgreeTest`** (new methods at the end): the page's `MAX_EMAIL` and `EMAIL` pattern are
the model's; every email route the page names is one the server answers; the keys the page sends
(`email`, `token`) are the keys the server reads. (The words tests from `japanese` already check the
new codes and keys.)

**Checked by hand:** `make run`, sign up, add an address; copy the link from the terminal into the
browser; reply from a second window; read the framed email in the terminal.

## 7. Docs to update

- `AGENTS.md`: the file table gets `with-backend/outbox.py` and `with-backend/email_words.py`; the
  model and view lists get the new functions; a new section "Email" says: deciding is the model,
  writing is the view, carrying out is `outbox.py`; the running server prints emails and sends none;
  tests always use `KeptOutbox`; the confirm route works from the token alone.
- `DESIGN.md`: a new section "Reply emails": the `emails` table, the six routes, the confirm link
  and why it needs no cookie, why the outbox runs on a thread, and what happens when it fails.
- `README.md`: a new section "Emails": where to see them (the terminal), and how to confirm an
  address by copying the link.

## 8. Not in this plan

- **Really sending email.** That is a later plan. It would add an `SmtpOutbox` to `outbox.py`, which
  hands the same `EmailMessage` to a mail server with Python's `smtplib` over an encrypted
  connection, chosen when settings such as `TIMELINE_SMTP_HOST` are given from the terminal. The
  password would come only from those settings, never from the code or git, and a `From:` address
  and an absolute link address (`base_url`) would become settings too.
- HTML emails, and pictures in emails.
- Trying again after a failure, or keeping unsent emails across a restart (D5).
- One email that collects several replies (a digest), or a limit on reply emails per hour.
- Emails for likes, or for anything other than a reply.
- Password reset by email (it could reuse `outbox.py` later).
- Links that work from another computer: the server listens on `127.0.0.1` only.

## 9. Size

**L**, about 650 lines: `outbox.py` about 60; `email_words.py` about 40; `server.py` about 170
(model 100, controller 45, view 25); `words.js` about 25; `app.js` about 100; `index.html` 20; CSS
20 (twice); tests about 230.
