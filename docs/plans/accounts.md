# Accounts

Status: built on branch accounts, awaiting merge

## 1. What it does

People sign up with an account name (`@aiko`), a display name (*Aiko Tanaka*) and a password, then
log in and log out. Only a signed-in person can post or like, and the server knows who they are, so
nobody can post as someone else. Anyone can still read the timeline.

## 2. Decisions (made by the owner)

- **Old users from before accounts:** kept. The first person to sign up with an old name claims it
  and its old posts. Names that break the account-name rule (for example `Daniel Radcliffe`, which
  has a space) can never be claimed; their posts stay, with no owner.
- **`page-only/`:** a demo. No login there.
- **Reading:** open to everyone. Posting and liking need sign-in.

## 3. Design

**Passwords.** `hashlib.pbkdf2_hmac("sha256", …, 600000 rounds)` with a 16-byte random salt per
user, compared with `hmac.compare_digest`. The round count is saved with each hash. A password is
never trimmed; it is 8 to 200 characters.

**Sessions.** After sign-up or login the server makes a random token (`secrets.token_urlsafe(32)`),
keeps only its SHA-256 hash in `sessions`, and sends the token in a cookie:
`session=…; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict`. A session lasts 30 days. Logging
out deletes the row.

**Database (upgrade `upgrade_to_accounts`, `user_version` 1).**
- `users` gains `display_name` (starts as the name), `password_salt`, `password_hash`,
  `password_rounds` (all three NULL for an unclaimed old user), and a unique index on
  `name COLLATE NOCASE`.
- New table `sessions (token_hash PRIMARY KEY, user_id, expires_at)`.

**Model.** `check_name`, `check_display_name` (refuses control characters and direction marks),
`check_password`, `check_text`, `check_post_id`, `hash_password`, `hash_token`, `create_account`
(claims an old name in one `UPDATE … WHERE password_hash IS NULL`), `log_in`, `user_for_session`,
`log_out`, `start_session`, `account_for`. `save_post`, `add_like`, `remove_like` and `likes_for`
take a `user_id`. `user_id_for` is removed: only sign-up creates a user. Errors: `RuleBroken` → 400,
`NotSignedIn` → 401. One message for a wrong name or a wrong password.

**Routes.**

| Request | JSON in | Answer |
|---|---|---|
| `POST /accounts` | `account_name`, `display_name`, `password` | 201 + cookie, `{account_name, display_name}` |
| `POST /sessions` | `account_name`, `password` | 201 + cookie, or 401 |
| `DELETE /sessions` | — | 200, cookie cleared |
| `GET /sessions` | — | 200 `{account_name, display_name}`, or 401 |
| `POST /posts` | `text` | 201, or 401 |
| `POST` / `DELETE /likes` | `post_id` | 201 / 200, or 401 |
| `GET /likes` | — | counts for everyone; `mine` from the cookie |

Every request with a body must say `Content-Type: application/json`, so a form on another website
cannot use a signed-in person's cookie.

**View.** `account_to_json`, `session_cookie`, and `post_to_log_line` puts the post's text in quotes,
so a line break in a post cannot fake a second line in the terminal.

**Page.** Log in and Sign up forms when signed out (`type="password"`, `autocomplete` set so
password managers work); "Signed in as … · Log out" and the post form when signed in. The page asks
`GET /sessions` when it opens, never sends a name with a post or a like, and shows the login form
whenever the server answers 401.

## 4. Files touched

`with-backend/server.py` (all three parts), `with-backend/app.js`, `with-backend/index.html`,
`with-backend/style.css` and its copy `page-only/style.css`, `with-backend/test_server.py`,
`AGENTS.md`, `DESIGN.md`, `README.md`.

## 6. Tests

- Model: different salts give different hashes; the plain password is in no table; a password is
  not trimmed; the same message for a wrong name and a wrong password; an expired session is
  refused; logging out deletes the row; `Aiko` is refused when `aiko` exists; an old name can be
  claimed once, and a name with a space cannot be; the upgrade keeps every old row.
- Real server: sign-up sets an `HttpOnly` cookie; a post without a cookie gets 401; a request
  that is not JSON is refused.
- Journey: two people sign up, post and like; one sends `"author": "aiko"` and the post is still
  theirs; logging out stops liking; logging in again works; no plain password anywhere.
- Agree: the page asks only for routes the server answers; the JSON keys the page sends are
  exactly the keys the server reads; the page has the same limits and patterns as the model;
  both `style.css` files are the same.

## 8. Not in this plan

Password reset (needs email), changing a password or display name, deleting an account, limiting
login attempts (`rate-limit`), HTTPS. The server listens on `127.0.0.1` only.
