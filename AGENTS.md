# AGENTS.md — for the AI agent working in this repository

The person asking you may be new to programming, and may read English as a second language. Explain in short, plain sentences, and define a technical word the first time you
use it. When you change code, say which file changed and why.

## What this is

Timeline is a small app where people post short messages, and everyone's posts appear on one
timeline, newest first. Each post has a heart: each name can like a post once, and pressing the
heart again takes the like back. It comes in two versions with the same screen:

- `page-only/` runs only in the browser. It has no server, so nothing is shared between windows.
- `with-backend/` has a small Python server and a database, so every window sees every post.

## What each file does

| File | Its one job |
|---|---|
| `page-only/index.html` | The parts of the screen: name, post box, Post button, timeline. |
| `page-only/style.css` | How the screen looks. |
| `page-only/app.js` | Checks the rules and keeps the posts in this window's `sessionStorage`. There are no likes in this version. |
| `with-backend/index.html` | The same screen as `page-only/index.html`. |
| `with-backend/style.css` | The same look as `page-only/style.css`. |
| `with-backend/app.js` | Sends each post, each like and each like taken back to the server, and asks the server for new posts and new like counts every second. |
| `with-backend/server.py` | The backend, in three labelled parts: **controller**, **model**, **view**. |
| `with-backend/test_server.py` | The checks for `server.py`. |
| `with-backend/timeline.db` | The database, in three tables. The server creates it when it starts. It is not in git. |
| `Makefile` | Short commands: `make run`, `make test`, `make reset`. |

The three parts of `server.py`:

- **Controller** (`TimelineHandler`): reads each request and picks what to do. `POST` adds, `DELETE`
  removes: the method says what happens, so the controller never has to guess.
- **Model** (`check_rules`, `save_post`, `posts_after`, `user_id_for`, `check_like_rules`,
  `add_like`, `remove_like`, `like_count_for`, `likes_for`): the rules a post and a like must follow, and the
  database, in three tables: `users` (each person once), `posts` (each post points at its author
  by `author_id`) and `likes` (one row for each person who liked each post). A name is kept once,
  in `users`; never copy it into another table. A like count is never kept anywhere: it is counted
  from the rows in `likes`, so a count and its likes can never disagree. Taking a like back deletes
  its row; nothing is marked as undone. Never call `user_id_for` when only reading or removing: it
  adds a user, and asking about likes or taking one back must never invent a person.
- **View** (`post_to_json`, `posts_to_json`, `like_to_json`, `likes_to_json`): turns database rows
  into the JSON the page reads.

## How to run it

- Page-only: open `page-only/index.html` in a browser. Nothing to start.
- With a backend: `make run`, then open <http://localhost:8009>. Press Ctrl+C to stop.
- Start again with an empty timeline: `make reset`.
- See what is saved:
  `sqlite3 with-backend/timeline.db 'select * from users; select * from posts; select * from likes'`

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
  answers. The page's own JavaScript is never run by the tests: that would need a browser or Node,
  and this project needs only `python3`.

## The one rule

**Keep the three parts of `server.py` separate. A new rule goes in the model.** The controller does
not check rules and does not touch the database. The view does not decide anything. Where a rule can
be given to the database itself, give it to the database: `likes` has
`PRIMARY KEY (post_id, user_id)`, so a second like from the same person is refused even if every
check in the code is got around. If a feature
needs a new rule, write it in the model, and check it in the page too, because the page and the
server must agree. The server always checks, even when the page already did, because a user can change anything that
runs on their own device.
