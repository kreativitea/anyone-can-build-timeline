# AGENTS.md — for the AI agent working in this repository

The person asking you may be new to programming, and may read English as a second language. Explain in short, plain sentences, and define a technical word the first time you
use it. When you change code, say which file changed and why.

## What this is

Timeline is a small app where people post short messages, and everyone's posts appear on one
timeline, newest first. People sign up with an account name (`@aiko`), a display name
(*Aiko Tanaka*) and a password, then log in. Anyone can read the timeline. Only a signed-in person
can post or like. Each post has a heart: each person can like a post once, and pressing the heart
again takes the like back. It comes in two versions:

- `with-backend/` has a small Python server and a database, so every window sees every post. It has
  accounts.
- `page-only/` is a demo. It runs only in the browser, has no server and no login, and nothing is
  shared between windows. Its screen is no longer the same as the backend version.

**A person is a signed-in user.** The server knows who is asking from the session cookie (a small
piece of text the browser keeps and sends back by itself), never from a name in the request.

## What each file does

| File | Its one job |
|---|---|
| `page-only/index.html` | The demo screen: two name boxes, post box, Post button, timeline. No login. |
| `page-only/style.css` | An exact copy of `with-backend/style.css`. Change that one, then copy it here. |
| `page-only/app.js` | Checks the rules and keeps the posts in this window's `sessionStorage`. There are no likes in this version. |
| `with-backend/index.html` | The parts of the screen: Log in and Sign up forms when signed out; "Signed in as …", Log out and the post box when signed in; the timeline. A tiny script in `<head>` that sets the colours before the page is drawn, and the Colours switch. |
| `with-backend/style.css` | How the screen looks. Each colour is written once for light and dark, as `light-dark(LIGHT, DARK)`. |
| `with-backend/app.js` | Asks the server who is logged in, sends sign-ups, logins, log-outs, posts, likes and likes taken back, and asks for new posts and new like counts every second. Remembers the Colours choice in `localStorage`. It keeps a half-written post in this browser's `localStorage`, one per account, removed after posting or logging out. |
| `with-backend/server.py` | The backend, in three labelled parts: **controller**, **model**, **view**. |
| `with-backend/test_server.py` | The checks for `server.py`, and for the page and the server agreeing. |
| `with-backend/timeline.db` | The database, in four tables. The server creates it when it starts, and brings an older one up to date. It is not in git. |
| `Makefile` | Short commands: `make run`, `make test`, `make reset`, `make worktree BRANCH=name`. |

The Colours choice (Auto, Light or Dark) is the only thing the page keeps in `localStorage`
(storage in the browser that stays after the tab closes). It never goes to the server.

The three parts of `server.py`:

- **Controller** (`TimelineHandler`): reads each request and picks what to do. `POST` adds, `DELETE`
  removes: the method says what happens, so the controller never has to guess. It reads who is
  asking from the session cookie, and answers `401` when nobody is logged in. It never reads a
  name from the JSON. A request with a body must say `Content-Type: application/json`.
- **Model** (`check_name`, `check_display_name`, `check_password`, `check_text`, `check_post_id`,
  `hash_password`, `hash_token`, `create_account`, `log_in`, `user_for_session`, `log_out`,
  `start_session`, `account_for`, `save_post`, `posts_after`, `add_like`, `remove_like`,
  `like_count_for`, `likes_for`, and `create_tables` with `upgrade_to_accounts`): the rules, and the
  database, in four tables:
  - `users`: each person once. `name` is the account name (unique, capitals ignored),
    `display_name` is the name shown, and `password_salt`, `password_hash`, `password_rounds` hold
    a hash of the password. The password itself is never kept.
  - `posts`: each post points at its author by `author_id`.
  - `likes`: one row for each person who liked each post.
  - `sessions`: one row for each logged-in window. It keeps only a hash of the token, the user's id,
    and when it ends. Logging out deletes the row.

  A name is kept once, in `users`; never copy it into another table. Only sign-up
  (`create_account`) adds a user: posting, liking and reading never do. A like count is never kept
  anywhere: it is counted from the rows in `likes`, so a count and its likes can never disagree.
  Taking a like back deletes its row; nothing is marked as undone. Errors: `RuleBroken` becomes
  `400`, `NotSignedIn` becomes `401`.
- **View** (`post_to_json`, `posts_to_json`, `account_to_json`, `like_to_json`, `likes_to_json`,
  `session_cookie`, `post_to_log_line`): turns database rows into the JSON the page reads, the
  cookie, and the one line printed for each new post.

The database knows its own version (`PRAGMA user_version`). An older `timeline.db` from before
accounts is upgraded when the server starts, and keeps every row. Its old users have no password:
the first person to sign up with an old name claims it, and its old posts.

## How to run it

- Page-only: open `page-only/index.html` in a browser. Nothing to start.
- With a backend: `make run`, then open <http://localhost:8009>. Press Ctrl+C to stop.
- Start again with an empty timeline: `make reset`.
- See what is saved:
  `sqlite3 with-backend/timeline.db 'select * from users; select * from posts; select * from likes; select * from sessions'`

It needs only `python3` (3.9 or newer). Do not add libraries, packages or a build step.
Write code that runs on Python 3.9: no `match` statements, and no `X | Y` in type hints.

## How to test it

`make test`. Every test must pass before and after a change. A new feature gets a new test in
`with-backend/test_server.py`.

Four kinds of test live there:

- `ModelTests` calls the model directly, with a database made only for the test.
- `RealServerTest` starts the real server and talks to it over HTTP, as the page does.
- `JourneyTest` walks one whole journey through all three levels at once: the requests the page
  really makes, the server that answers them, and the rows in the database file, read with SQL after
  every step. A feature that spans the page, the server and the store belongs here too.
- `PageAndServerAgreeTest` reads `app.js` and checks every request it names is one the server
  answers, that the JSON names it sends are exactly the ones the server reads, that it has the
  model's limits and patterns, and that the two `style.css` files are the same. The page's own
  JavaScript is never run by the tests: that would need a browser or Node, and this project needs
  only `python3`.

`PageDraftTest` also reads `app.js` as text. Drafts never reach the server, so it checks that the
code is wired the agreed way: one draft per account, every use of `localStorage` inside a `try`,
and the draft forgotten only after a saved post or a log out.

## Every branch gets its own worktree

A worktree is a second folder for the same repository, with one branch in it. Every branch gets its
own: `make worktree BRANCH=name` makes `.claude/worktrees/name`. Work there, never in the main
folder, so several people or agents can work at the same time without touching each other's files.
Each worktree has its own `timeline.db`. To run two at once, give one another port:
`make run PORT=8010`.

## The one rule

**Keep the three parts of `server.py` separate. A new rule goes in the model.** The controller does
not check rules and does not touch the database. The view does not decide anything. Where a rule can
be given to the database itself, give it to the database: `likes` has
`PRIMARY KEY (post_id, user_id)`, so a second like from the same person is refused even if every
check in the code is got around, and `users` has a unique index on `name COLLATE NOCASE`, so `@Aiko`
can never be added next to `@aiko`. If a feature
needs a new rule, write it in the model, and check it in the page too, because the page and the
server must agree. The server always checks, even when the page already did, because a user can change anything that
runs on their own device.
