Status: built on branch rate-limit, awaiting merge

# Rate limit

## 1. What it does

The server stops a person who does one thing too many times too quickly: too many posts in a
minute, too many likes in a minute, too many wrong passwords for one account, or too many new
accounts. The server answers "Too many posts. Please try again in 42 seconds.", and the page
shows those words and keeps the button turned off until the wait is over. A person who uses the
app normally never sees this. Reading the timeline is never limited.

A **rate limit** is a rule of the form "at most N times in S seconds". This plan adds four of them.

## 2. Decisions for the owner

1. **Where are the counts kept?**
   - (a) In a new database table, `attempts`. It survives a restart of the server. SQLite already
     handles many threads at once, so no extra lock is needed.
   - (b) In memory, in a Python dictionary inside the server. A little faster, but it needs a
     **lock** (a way to let only one thread change it at a time, because the server is a
     `ThreadingHTTPServer` and answers many requests at the same moment). It is lost on every
     restart, so stopping and starting the server clears every limit, including the
     wrong-password limit.
   - **Recommendation: (a).** One place for every fact, like the rest of the app, and restarting
     the server must not reset the password limit.

2. **The numbers.** "How many" in "how many seconds":

   | Action | Counted for | Limit (recommended) |
   |---|---|---|
   | post | each signed-in user | 5 in 60 seconds |
   | like (pressing the heart either way) | each signed-in user | 30 in 60 seconds |
   | login | each account name | 5 tries in 10 minutes |
   | sign-up | each address (see 4) | 10 in 60 minutes |

   - **Recommendation: these numbers.** They are written once, in one table in the model
     (`LIMITS`), so changing one is a one-line change.

3. **What is a login attempt counted against?**
   - (a) The account name that was typed (`aiko`). A stranger cannot try more than 5 passwords for
     Aiko in 10 minutes. But a stranger *can* type 5 wrong passwords on purpose and stop Aiko
     from logging in for 10 minutes. A window where Aiko is already logged in is not affected.
   - (b) The address the request came from. Today every request comes from `127.0.0.1` (see 4),
     so 5 wrong passwords by anyone would stop **everyone** from logging in.
   - **Recommendation: (a).** It is the only one that protects one account without locking out
     the whole app, and the lock-out it allows is short.

4. **What is a sign-up counted against?** The server listens on `127.0.0.1` only, so today every
   request has the same **IP address** (the number that says which computer sent a request).
   Counting by address is therefore the same as one count for the whole server.
   - (a) By address. Today: at most 10 new accounts in an hour on this server, from everyone
     together. Correct by itself if the server ever listens to other computers.
   - (b) No sign-up limit.
   - **Recommendation: (a).** Each sign-up costs about 0.07 s of hashing and adds a row, so an
     unlimited loop could both slow the server and fill the database. The address is read from the
     connection itself (`self.client_address[0]`), never from a header like `X-Forwarded-For`,
     because a header can say anything.

5. **Does an attempt that is refused for being too fast also count?**
   - (a) No. Only allowed attempts are counted. Someone who keeps pressing gets in again as soon
     as the oldest counted attempt is old enough.
   - (b) Yes. Pressing during the wait makes the wait longer.
   - **Recommendation: (a).** It is simple to explain, and the wait the server names is then
     true.

6. **Does the page count too?**
   - (a) No. The page cannot see other windows, so its own count would often be wrong. It obeys
     the server: on a `429` it shows the server's words and turns off the button for the seconds
     the server says.
   - (b) Yes, the page also counts posts in this window and refuses the sixth itself.
   - **Recommendation: (a).** The page and the server agree on what `429` means and on the key
     `retry_after`; `PageAndServerAgreeTest` checks it.

## 3. Design

### Why the model owns this rule

Counting requests feels like a job for the controller, because it is about requests. It is
not. "At most 5 posts a minute" is a rule about what a person may do, the same kind of rule as
"at most 280 characters". It must be true for every way a post can be saved, including ones
added later (a reply, a post with a picture). If the check sits in `save_post`, any new route
that saves a post gets it for free. If it sits in the controller, each new route must remember
it. And the counts are rows in the database, and in this app only the model touches the
database. So the controller does only two small things: it passes the address in for sign-up
(as it already passes the session token in), and it turns the model's `TooFast` into a `429`.

### Database (upgrade `upgrade_to_rate_limit(connection)`)

Written like `upgrade_to_accounts`: `BEGIN`, the change, the `PRAGMA user_version` line (the
orchestrator chooses the number), `commit`.

```sql
CREATE TABLE attempts (
    action TEXT NOT NULL,   -- 'post', 'like', 'login' or 'signup'
    key    TEXT NOT NULL,   -- a user id, a lower-case account name, or an address
    at     REAL NOT NULL    -- when, in seconds (time.time())
);
CREATE INDEX attempts_by_key ON attempts (action, key, at);
```

One row is one allowed attempt. A count is never kept: it is counted from the rows, like the
like count. Old rows are deleted as they stop mattering (see `use_allowance`). Nothing points at
this table, and it holds no passwords and no post text.

### Model

```python
# How many times, in how many seconds. One place for every limit.
LIMITS = {"post": (5, 60), "like": (30, 60), "login": (5, 600), "signup": (10, 3600)}
WHAT = {"post": "posts", "like": "likes", "login": "wrong passwords for this account",
        "signup": "new accounts"}

class TooFast(Exception):
    """Too many attempts too quickly. retry_after says how many seconds to wait."""
    def __init__(self, message, retry_after): ...

def clock():
    """The time now, in seconds. The tests replace this, so they never wait for real."""
    return time.time()

def use_allowance(db_path, action, key):
    """Count one attempt at `action` by `key`, or raise TooFast if there have been too many."""

def forget_attempts(db_path, action, key):
    """Delete every counted attempt at `action` by `key`. Used after a right password."""
```

`TooFast` is **not** a kind of `RuleBroken`, so it can never be sent as a `400` by mistake.

`use_allowance` opens its own connection, so a caller adds one line and never has to close
anything when it raises. Inside, it does this:

1. `BEGIN IMMEDIATE`. This takes the database's write lock at once, so two requests at the same
   moment take turns. Without it, two posts sent together could both count 4 and both be
   allowed, making 6.
2. Delete this action's rows older than its window (tidying up).
3. Count this key's rows in the window. If there are already N: roll back and raise `TooFast`.
   `retry_after` is the oldest row's `at` + the window − now, rounded **up** to whole seconds,
   and at least 1. The message is `f"Too many {WHAT[action]}. Please try again in {n} seconds."`
4. Otherwise insert one row with `at = clock()`, and commit.

The lock is held for a few small statements only, never during password hashing.

Changes to existing model functions, each as small as possible:

- `save_post`: after `check_text`, one line: `use_allowance(db_path, "post", str(user_id))`.
  An empty post is refused first and is not counted.
- `add_like` and `remove_like`: after `check_post_id`, one line:
  `use_allowance(db_path, "like", str(user_id))`. Liking and taking back share one count, so the
  heart cannot be flipped without end.
- `log_in`: after the name is trimmed and before anything else (and so **before any hashing**):
  `use_allowance(db_path, "login", name.lower())`. Every attempt is counted as a failure until it
  is proved right; after a right password, `forget_attempts(db_path, "login", name.lower())`.
  This way a refused attempt costs the server no hashing at all, and many attempts sent at the
  same moment cannot slip past the count while the first one is still hashing. A name with no
  account is counted the same way, so the limit does not tell a stranger which names exist.
  Hashing work is bounded: at most 5 hashes per real account per 10 minutes. (A name with no
  account is never hashed, so it costs nothing.)
- `create_account(db_path, name, display_name, password, address="local")`: a new last argument
  with a default, so every existing call still works. After the three checks and **before**
  hashing: `use_allowance(db_path, "signup", address)`. A sign-up refused for a bad name is not
  counted; one refused because the name is taken is counted (it was hashed).

`clock()` is used only by the rate limit. Sessions keep using `time.time()`, so moving the test
clock forward never ends a login.

### Routes

No new routes. Five existing requests can now also answer `429 Too Many Requests`:
`POST /posts`, `POST /likes`, `DELETE /likes`, `POST /sessions`, `POST /accounts`.

```
HTTP/1.0 429 Too Many Requests
Retry-After: 42
Content-Type: application/json; charset=utf-8

{"error": "Too many posts. Please try again in 42 seconds.", "retry_after": 42}
```

`Retry-After` is the standard header that says, in whole seconds, when to try again. The same
number is in the JSON, because the page reads JSON. The order of answers is: not signed in →
`401`; a broken rule → `400`; too fast → `429`. A `429` for login replaces the `401`: once the
limit is reached, even the right password waits.

Reading is never limited: `GET /posts`, `GET /likes` and `GET /sessions` are asked every second
by every window. `DELETE /sessions` (log out) is not limited.

### Controller

- `do_POST`: wrap the four-way dispatch (`sign_up` / `log_in` / `take_like` / `take_post`) in
  one `try … except TooFast as problem: self.send_too_fast(problem)`. The model raises before
  any answer is sent, so this is safe.
- `do_DELETE`: the `/likes` branch catches `TooFast` the same way, next to its `RuleBroken`.
- `sign_up`: passes `address=self.client_address[0]` to `create_account`.
- New method `send_too_fast(problem)`: sends `429`, the `Retry-After` header and
  `too_fast_to_json(problem)`. It is a new method so that `send_json` and `send_answer` are not
  changed.

### View

- New `too_fast_to_json(problem)` → `{"error": str(problem), "retry_after": problem.retry_after}`.

### Page (`with-backend/app.js`)

- New function `holdForm(form, seconds)`: turns off the form's submit button, and turns it on
  again after `seconds` (one `setTimeout`).
- `sendPost`, `logIn`, `signUp`: in the existing `if (!response.ok)` branch, which already shows
  `answer.error`, add one line:
  `if (response.status === 429) holdForm(postForm /* or loginForm, signupForm */, answer.retry_after);`
- `pressHeart`: nothing new. Its `!response.ok` branch already shows the server's words and asks
  the server what is true. The hearts are not turned off.
- No change to `index.html` or `style.css` (a turned-off button already looks turned off).

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | MODEL: `LIMITS`, `WHAT`, `TooFast`, `clock`, `use_allowance`, `forget_attempts` | add |
| `with-backend/server.py` | MODEL: `upgrade_to_rate_limit` | add |
| `with-backend/server.py` | MODEL: `create_tables` (one `if version < N` line) | change |
| `with-backend/server.py` | MODEL: `save_post`, `add_like`, `remove_like` (one line each) | change |
| `with-backend/server.py` | MODEL: `log_in` (two lines), `create_account` (new `address` argument, one line) | change |
| `with-backend/server.py` | CONTROLLER: `send_too_fast` | add |
| `with-backend/server.py` | CONTROLLER: `do_POST` (try around the dispatch), `do_DELETE` (`/likes` branch), `sign_up` (pass the address) | change |
| `with-backend/server.py` | VIEW: `too_fast_to_json` | add |
| `with-backend/app.js` | `holdForm` | add |
| `with-backend/app.js` | `sendPost`, `logIn`, `signUp` (one line each in the `!response.ok` branch) | change |
| `with-backend/test_server.py` | new methods at the end of `ModelTests`, `RealServerTest`, `JourneyTest`, `PageAndServerAgreeTest`, and a `FakeClock` helper | add |
| `AGENTS.md` | new section "Rate limits"; one row in the model's function list | add |
| `DESIGN.md` | new rows at the end of section 7; the `attempts` table in section 5 | add |
| `README.md` | one line: what a `429` means | add |

## 5. Depends on, and collides with

- **Depends on `accounts`.** It needs the signed-in user id, `log_in`, `create_account` and
  `upgrade_to_accounts` as the pattern. It closes the "limiting login attempts" gap that
  `accounts` section 8 leaves open.
- **`timestamps`, `replies`, `pictures`, `edit-delete`:** they likely change `save_post` too.
  This plan adds one line at its top, after `check_text`; a rebase should be easy. If `replies` or
  `pictures` save posts through a new function instead of `save_post`, that function must call
  `use_allowance(db_path, "post", …)` as well (say so in review). An edit is not a new post and is
  not limited here.
- **`who-liked`:** may change `add_like` / `remove_like`. One line here.
- **Every plan with an upgrade:** each adds one line to `create_tables`. The orchestrator numbers
  them.
- **`drafts`, `pictures`, `replies`, `timestamps`:** may change `sendPost` in `app.js`. This plan
  adds one line inside its `!response.ok` branch.
- **`report`, `block`, `bookmarks`, `search`:** not touched. `report` may want its own entry in
  `LIMITS` later; it is one line plus one `use_allowance` call.

## 6. Tests

Each test that needs time to pass uses a `FakeClock`: a small object whose `now` the test sets,
put in place with `unittest.mock.patch.object(server, "clock", fake)` (part of Python's standard
library) and removed with `addCleanup`. The real server in `RealServerTest` and `JourneyTest`
runs in a thread of the same process, so it sees the fake clock too. No test sleeps.

**ModelTests**
- Five posts in one minute are saved; the sixth raises `TooFast` with `retry_after == 60` at the
  same moment, and is not in `posts`.
- After the clock moves 61 seconds, a post is allowed again.
- `retry_after` counts down: 20 seconds later it is 40.
- Aiko's limit does not affect Ben.
- An empty post raises `RuleBroken` and is not counted.
- A refused (too fast) attempt is not counted: no new row in `attempts`.
- Liking and taking back share one count: 15 likes and 15 take-backs, then the next is refused.
- Login: 5 wrong passwords, then the **right** password raises `TooFast`, and `hash_password` was
  called only 5 times (wrap it with `mock.patch.object(server, "hash_password", wraps=…)`).
- Login: the count is the same for `Aiko` and `aiko`, and for a name with no account (no hint
  that the name exists).
- A right password deletes that name's login rows.
- Sign-up: the 11th from one address is refused before hashing; another address is allowed;
  `create_account` without an address still works.
- Ten threads post as Aiko at the same moment: exactly 5 posts are saved (the write lock works).
- Old rows are deleted: after the clock moves past the window, the table has only new rows.
- `upgrade_to_rate_limit` on a database made by accounts keeps every user, post, like and session.

**RealServerTest**
- The sixth `POST /posts` answers `429`, with a whole-number `Retry-After` header of at least 1,
  and JSON with `error` and `retry_after` that agree with the header.
- `POST /sessions` with a wrong password: `401` five times, then `429`.
- `GET /posts` and `GET /likes` asked 100 times never answer `429`.
- A post with no cookie is still `401`, not `429`.

**JourneyTest** (`test_too_fast_journey`)
Aiko and Ben sign up. Aiko posts 5 times; the sixth is `429`; SQL shows 5 posts and 5 `post`
rows in `attempts`. Ben posts once and it works. A third window types 5 wrong passwords for
`aiko`; the sixth try is `429`; Aiko's own window can still post after the clock moves 61
seconds, because her session is not touched. The clock moves 10 minutes; Aiko logs in from a new
window, and SQL shows no `login` rows for `aiko` are left. No row in `attempts` holds a password
or post text.

**PageAndServerAgreeTest**
- `app.js` checks `response.status === 429` and reads `answer.retry_after`, and
  `too_fast_to_json` writes exactly the key `retry_after`.
- Every request in `app.js` that can be refused with `429` (the five above) is one the server
  limits, and `app.js` never sends a `429`-able request without a `!response.ok` branch.

## 7. Docs to update

- `AGENTS.md`: a new short section "Rate limits": the `LIMITS` table, that the rule lives in the
  model in `use_allowance`, that tests move `clock` instead of sleeping, and that a new way of
  saving a post must call `use_allowance`. Add the new model functions to the model's list, and
  the `attempts` table to the database line and the `sqlite3` command.
- `DESIGN.md`: the `attempts` table in section 5; new rows at the end of section 7 (database vs
  memory; account name vs address for login; why the model owns the rule; why refused attempts
  are not counted).
- `README.md`: one line, "If the app says *Too many …*, wait the seconds it names."

## 8. Not in this plan

- Limits by IP address that mean something. Today every request is from `127.0.0.1`. If the
  server is ever put on a real network, the address keys need a second look, and a proxy in front
  would make every address the proxy's.
- Making a login for a name with no account take as long as one with a wrong password (today it
  is faster, so a stranger can time it to learn which names exist). That belongs to `accounts`.
- A **CAPTCHA** (a puzzle to prove a person is typing), emailing the owner after many wrong
  passwords, or a lock-out that grows longer each time.
- Limits on editing, reporting, blocking or bookmarking. Each later plan can add one row to
  `LIMITS`.
- Limiting reading (`GET`) requests.
- A page-side countdown that changes every second. The message names the wait once.

## 9. Size

**M.** About 60 lines in `server.py`, 15 in `app.js`, 170 in `test_server.py`, 30 in the docs:
roughly 275 lines.

## Changes made at approval (orchestrator)

- **Rules first, then the count.** A post or like that breaks a rule (empty, too long, no such
  post) is refused before `use_allowance` is called, so a mistake never uses up the allowance.
- **Old rows are cleaned up.** `use_allowance` deletes rows older than the longest window in
  `LIMITS`, the way `start_session` deletes old sessions.
- **Sign-ups: 30 per hour**, not 10. Every request comes from `127.0.0.1` today, so this limit is
  shared by everyone using the server.
- Posts stay at 5 per minute. `reply-email` adds one row to `LIMITS` for confirm emails.
