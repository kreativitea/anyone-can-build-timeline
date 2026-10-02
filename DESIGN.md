# Design doc — Timeline

*Every name and example row here is made up.*

---

*The product spec*

## 1. The problem

When two people use the same app, each needs to see what the other posted. A page that keeps
everything in the browser cannot do that: each person's device keeps its own copy. Timeline is a
small Twitter-like app built to show the difference. One version keeps everything in the page, and
the other has a backend that every window shares.

## 2. Not in this version

- No password reset (it needs email), no changing a password or a display name, and no deleting an
  account.
- No limit on login attempts. That is its own feature, `rate-limit`.
- No HTTPS. The server listens on `127.0.0.1` only, so the password never leaves the computer.
- No login in `page-only/`. It is a demo of a page with no server, so it has nothing to log in to.
- No follows, replies, deleting or editing. They are left for whoever extends the app.
- Pictures came later: see "Pictures" below. A table of bytes in the database turned out to be
  enough; no second kind of storage was needed.
- No realtime connection (no WebSockets). The page asks for new posts once a second.
- Nothing reachable from another machine. The server listens on `127.0.0.1` only.
- No libraries, no install, no build step.

## 3. Screens

One screen in `with-backend/`:

- **Signed out.** A *Log in* form (account name, password) and a *Sign up* form (account name,
  display name, password), side by side. The account name box has an `@` in front of it, so nobody
  has to type it. The timeline is below, so anyone can read it. Pressing a heart says *Please log in
  to like a post.*
- **Signed in.** *Signed in as Aiko Tanaka @aiko · Log out*, then a *What is happening?* box with a
  live count (*x / 560*) and a **Post** button, and the timeline below it, newest first (display
  name, `@`account name, time, text, and a heart with the number of people who pressed it). A heart
  you have pressed is shown in a different colour, and pressing it again takes the like back.

When the page opens, it asks the server who is logged in, then shows one of the two. Whenever the
server answers *401* (nobody is logged in), the page shows the signed-out view and the server's
reason, and empties the post box.

A **Colours** switch sits just under the title, for everyone, signed in or not. It has three
choices: *Auto* follows the computer's light or dark setting, *Light* and *Dark* stay the same
whatever the computer says. The choice is remembered in this browser (`localStorage`), not on the
server, so another browser or device has its own choice. A tiny script in `<head>` uses the saved
choice before the page is drawn, so the page never flashes the wrong colours.

`page-only/` is a demo with its own simpler screen: two name boxes, the post box and the timeline,
with no login and no hearts.

Large type and high contrast, so that it can be read from across a room.

---

*The engineering design*

## 4. The three parts

```
the browser                          the server                   the store
index.html · style.css · app.js  ──  server.py  ──────────────────  timeline.db
      a new post, a like, "anything new?" ▶    save this, give me the newest ▶
      ◀ saved, the newest posts, the counts      ◀ the rows
```

| Part | `page-only/` | `with-backend/` |
|---|---|---|
| **Frontend** (runs on the user's device) | `index.html` · `style.css` · `app.js` | the same three files; `app.js` talks to the server instead of the browser |
| **Backend** (runs on the server) | none: the rules run in `app.js` | `server.py`, Python 3 standard library (`http.server`), written in three labelled parts: **controller · model · view** |
| **Data** (runs on the server) | the browser's `sessionStorage` | `timeline.db`, one SQLite file with four tables, `users`, `posts`, `likes` and `sessions`, created by the server when it starts |

**Technologies, and why each one.**

- **Plain HTML, CSS and JavaScript.** Three files, each with one job: structure, looks, behaviour.
- **Python 3 standard library only** (`http.server`, `sqlite3`, `json`). Python ships on a Mac, so
  there is nothing to install. The code avoids anything newer than Python 3.9.
- **SQLite.** One file, no database server of its own, and the `sqlite3` command can open it.
- **Polling, once a second.** `fetch('/posts?after=<last id>')` and `fetch('/likes')`
  on a timer: each window asks the server *anything new?* It is the simplest thing that works.
- **`hashlib.pbkdf2_hmac`, from the standard library, for passwords.** It hashes the password with a
  random salt 600000 times, so a stolen copy of the database is slow to guess from.
- **A session cookie, `HttpOnly` and `SameSite=Strict`.** The page's JavaScript cannot read it, and
  the browser sends it only with requests from this site.
- **`sessionStorage`, not `localStorage`, for the page-only version.** Two normal windows of one
  browser share `localStorage`, which would make the page-only version look shared. `sessionStorage`
  belongs to one window, as each person's phone has its own storage, and it survives a reload.

**The interfaces.** Who is asking always comes from the session cookie. A name in the JSON is
never read. Every request with a body must say `Content-Type: application/json`.

| Request | What goes in | What comes out |
|---|---|---|
| `POST /accounts` | `{"account_name": "aiko", "display_name": "Aiko Tanaka", "password": "…"}` | `201`, the cookie, and `{"account_name", "display_name"}` · or `400` with the rule it broke |
| `POST /sessions` | `{"account_name": "aiko", "password": "…"}` | `201`, the cookie, and `{"account_name", "display_name"}` · or `401` |
| `GET /sessions` | the cookie | `200` and `{"account_name", "display_name"}` · or `401` if nobody is logged in |
| `DELETE /sessions` | the cookie | `200`, and the cookie is cleared |
| `POST /posts` | `{"text": "the library is open late tonight"}` | the saved post, with its `id` and `posted_at` · or `400` with the rule it broke · or `401` |
| `GET /posts?after=12` | the last `id` this window has | every post with a larger `id`, oldest first |
| `POST /likes` | `{"post_id": 7}` | `{"post_id": 7, "like_count": 3}` · or `400` with the rule it broke · or `401` |
| `DELETE /likes` | `{"post_id": 7}` | the same answer, with the count one lower · or `400` if there was no such like · or `401` |
| `GET /likes` | the cookie, if there is one | `{"counts": {"7": 3}, "mine": [7]}`: how many likes each post has, and which posts this person has liked (`mine` is empty when nobody is logged in) |
| `GET /` and the page files | nothing | the page (`index.html`, `style.css`, `words.js`, `app.js`) |
| any refusal (`4xx`) | — | `{"error": "The post must be 280 characters or fewer.", "code": "text_too_long", "values": {"limit": 280}}`: the English, the rule's code, and the values that fill in its words |

Pressing a heart is one idea to a person, but two requests: the **method** says which, so `POST`
adds a like and `DELETE` takes one back. The page decides which to send by looking at the heart it
is showing, because "a second press" is a thing on a screen, not a rule. The server is told plainly
which of the two to do, and never guesses.

A like changes no post, so `after` would never carry one: a like on an old post makes no new post
row. That is why the counts have a request of their own, and why it returns *all* of them each
time. `mine` is what lets a window show the right hearts as pressed after a reload, instead of the
page having to remember.

**The model's rules:** an account name is letters, numbers and `_` only, at most 40 characters, and
unique even if the capitals differ · a display name is at most 50 characters and has no line
breaks, control characters or marks that turn text around (empty means "use the account name") · a
password is 8 to 200 characters and is never trimmed · text is not empty after trimming · text is at
most 560 characters · a like says which post it is for, and that post exists · the same person
cannot like the same post twice · a like cannot be taken back if it was never there · posting and
liking need a login. The server checks them even though the page checks them too, because a user
can change anything that runs on their own device.

### Drafts

A half-written post is kept in the browser, so it comes back after a reload, a closed tab or a
restart. It never goes to the server: `server.py` and `timeline.db` know nothing about drafts.

- **`localStorage` here, `sessionStorage` in `page-only/`.** In `page-only/` the storage *is* the
  timeline, and `localStorage` would make two windows look shared. Here the timeline lives on the
  server, and a draft is one person's private note. `sessionStorage` is emptied when the tab is
  closed, which is the main case drafts are for, so this page uses `localStorage`.
- **One draft for each account**, under the key `timeline-draft:<account name>`, so two people on
  one computer never see each other's words.
- **Logging out deletes the draft**, and the box is emptied. `localStorage` is plain text on the
  disk, and logging out means "I am leaving this computer". When the login ends by itself (the
  session runs out), the draft is kept: the person did not choose to leave.
- **Posting deletes the draft**, but only after the server says the post is saved. A refused post
  keeps it.
- If the browser blocks or fills its storage, drafts quietly do nothing and posting still works.

### Languages

The page holds every word it shows; the server holds none of them.

- **The server sends a code, and the page chooses the words.** Every refusal names its rule by a
  code (`text_too_long`) and the values that fill in its sentence (`{"limit": 280}`). `PROBLEMS`
  in the model keeps one English sentence for each code, sent as `"error"`, for the terminal, the
  tests, and anyone using `curl`.
- **`words.js`** holds every word of the page, by key: the codes, with exactly the same English as
  `PROBLEMS`, and the page's own words (buttons, labels, the status line). `index.html` names each
  word with `data-words="key"`; `app.js` uses `say("key", values)`. `make test` checks the two
  tables agree, and that no word is written anywhere else.
- **People's own words are never translated:** posts, display names, account names.
- For now there is only English, and the language button is hidden. Japanese comes later, as one
  `ja:` line under each entry.

## 5. The data model

Four tables:

| `users` | |
|---|---|
| `id` | integer, primary key, given by SQLite |
| `name` | text, the account name (`aiko`): letters, numbers and `_` only, unique, and unique again with capitals ignored (`users_name_any_case`) |
| `display_name` | text, the name shown on each post (*Aiko Tanaka*), up to 50 characters, not unique |
| `password_salt` | text, 16 random bytes as hex, different for every user |
| `password_hash` | text, the password hashed with the salt, as hex. Never the password itself |
| `password_rounds` | integer, how many times it was hashed (600000), so the number can be raised later |

| `posts` | |
|---|---|
| `id` | integer, primary key, given by SQLite |
| `author_id` | integer, foreign key: the `id` of a row in `users` |
| `text` | text |
| `posted_at` | text, ISO 8601 in UTC, to the second (`2026-10-02T07:42:10Z`). NULL only for a post from before timestamps |
| `old_clock_time` | text, `HH:MM`: the only time a post from before timestamps has. NULL for every newer post. Exactly one of the two has a value |

| `likes` | |
|---|---|
| `post_id` | integer, foreign key: the `id` of a row in `posts` |
| `user_id` | integer, foreign key: the `id` of a row in `users` |
| | `PRIMARY KEY (post_id, user_id)`: the two together, so each pair can appear only once |

| `sessions` | |
|---|---|
| `token_hash` | text, primary key: the SHA-256 hash of the token in the cookie. Never the token itself |
| `user_id` | integer, foreign key: the `id` of a row in `users` |
| `expires_at` | integer, seconds since 1970: 30 days after the login |

| `attempts` | (rate limits) |
|---|---|
| `action` | text: `post`, `like`, `login` or `signup` |
| `key` | text: a user id (post, like), a lower-case account name (login), or an address (sign-up) |
| `at` | real, seconds since 1970 (`clock()`): when the attempt was allowed |
| | index `attempts_by_key (action, key, at)`. One row is one allowed attempt; a count is `COUNT(*)` |

Example rows: `users` `1 · aiko · Aiko Tanaka · 9f3a… · 5c1e… · 600000` · `2 · ben · Ben Ito · …` ·
`posts` `1 · 1 · the library is open late tonight · 2026-10-02T07:42:10Z · NULL` (an older post: `… · NULL · 15:42`) · `likes` `1 · 2` (Ben liked post 1) ·
`sessions` `a41b… · 1 · 1793520000`.

Only sign-up adds a user. Each name is kept once, and each post points at its author by number. A
like works the same way: it points at a post and at a user, both by number, and nothing else. A
session is the same again: logging out deletes its row, and an old one stops working when
`expires_at` has passed.

**Upgrading an older file.** A `timeline.db` made before accounts has `users (id, name)` only. SQLite
keeps a version number inside the file (`PRAGMA user_version`). When the server starts it makes the
tables as they were at version 0, then runs each upgrade the file has not had yet. Version 1,
`upgrade_to_accounts`, adds the new columns and `sessions` in one transaction, and keeps every row.
An old user's display name starts as their name, and they have no password, so nobody can log in as
them. The first person to sign up with an old name (capitals ignored) claims it, and its old posts
and likes. A name that breaks the account-name rule, such as one with a space, can never be claimed:
its posts stay, with no owner.

**There is no count column.** One row in `likes` means "this person liked this post", and a count is
`COUNT(*)` over those rows, worked out whenever it is asked for. A stored count would be a second
copy of a fact the rows already hold, and two copies can drift apart.

Because the like *is* the row, taking it back is a `DELETE` of that row: nothing is marked as
undone, and no count is lowered by hand. The count simply reads one less, because there is one row
fewer to count. Liking the same post again afterwards works, because nothing was left behind.

**What stops a second like, and where.** Three places, and only the last one is a guarantee:

| Where | What it does | Can it be got around? |
|---|---|---|
| the page, `app.js` | will not send a like for a heart it already shows as pressed | yes: a user controls their own device |
| the model, `add_like` | looks for the row, and refuses with a sentence the page can show | it is the rule, but on its own it could lose a race |
| the database, `PRIMARY KEY (post_id, user_id)` | refuses to keep a second row for the same pair | no |

The database is doing real work here, not repeating the model. `server.py` uses
`ThreadingHTTPServer`, so two requests really do run at the same moment: both could look, both could
see nothing, and both could try to insert. The primary key is what makes one of those two fail, and
the model turns that failure into the same sentence a person would have seen anyway.

Taking a like back has the same race and no constraint to catch it, because removing nothing twice
breaks no rule of the database. So `remove_like` does not look and then delete. It deletes, and asks
the `DELETE` how many rows it removed (`cursor.rowcount`): if the answer is none, there was no such
like. One statement, so there is no gap for a second request to slip into. The page has the same
problem one level up — two fast presses would both read the heart before the first answer comes
back — and solves it with a flag that allows one press at a time.

## 6. How I will know it works

1. When a person signs up, they should be logged in at once, with a cookie the page cannot read. The
   database should hold a salted hash of the password, never the password itself, and two people
   with the same password should get two different hashes.
2. When a person logs in with the right password they should get in. A wrong name and a wrong
   password should get the same message. Logging out should delete the session row, and an expired
   session should not work.
3. When a post is sent by a signed-in person, it should come back with an `id` and a time, and be
   theirs, even if the JSON names someone else. Without a login, posting and liking should get `401`.
4. When a window asks for posts after an `id`, it should get only newer posts, oldest first.
5. When two windows are open, a post from one should appear in the other within a second, and a
   heart pressed in one should change the count in the other within a second.
6. When a heart is pressed a second time, the like should be taken back: the row should be gone, the
   count one lower, and liking it again should work. When a window that has the heart wrong presses
   it, the server should refuse and say why, and the page should ask again rather than guess.
7. When an older `timeline.db` is opened, every user, post and like should still be there, and the
   first sign-up with an old name should claim it, once.
8. **And when it goes wrong:** when a post is empty, or longer than 560 characters, the server
   should refuse it and say which rule it broke. An account name with a space or a symbol, a name
   already taken (in any capitals), a display name over 50 characters or with a hidden character, or
   a password under 8 characters should be refused the same way. A request that is not JSON should
   be refused. When the server is stopped, the page should say *Cannot reach the server*, and
   recover by itself when the server starts again.

Sentences 1, 2, 3, 4, 6 and 7, and the first half of 8, are checked by `make test`. Sentence 5 and
the second half of 8 are browser behaviour, and are checked by hand, in two windows (one of them
private, so each has its own cookie).

`make test` also walks one whole journey end to end, in `JourneyTest`: two people sign up, post,
like and unlike through the real server over real HTTP, each with a cookie jar of their own, as two
browsers would. One tries to post as the other and fails; one logs out and cannot like, then logs
in again and can. After every step the database file is opened and read with SQL, so a step is
believed only if the rows agree with what the page was told. Every request it sends is one `app.js`
really sends, with the same method and the same JSON. The page's own JavaScript is not run by it —
that would need a browser or Node, and this project needs only `python3` — so
`PageAndServerAgreeTest` reads `app.js` instead. It checks that every request the page names is
one the server answers, that the JSON names the page sends are exactly the ones the server reads,
and that the page has the model's limits and patterns.

---

## 7. Adversarial review

| Objection | About | Decision | Why | What changed |
|---|---|---|---|---|
| Two normal windows share `localStorage`, so the page-only version looks shared. | design | accept | It hides the one thing the app exists to show. | The page-only version uses `sessionStorage`. |
| The error message says "280" even if the limit is changed. | design | accept | A rule should be written in one place. | The message reads the limit from the rule. |
| The author's name is copied into every post, so a rename would break old posts. | design | accept | One fact, one place, even without accounts. | A `users` table; each post points at its author by `author_id`. |
| The server could translate, using the browser's `Accept-Language`. | japanese | reject | Then the words live in two places, and the server must know the reader. | The server sends a code; the page holds the words. |
| `words.js` could be inside `app.js`. | japanese | reject | One file that only grows by adding is easier to merge, and easier for a translator. | `words.js` is its own file, loaded before `app.js`. |
| Pictures would make posts more realistic. | product | reject | A picture needs file storage as well as the database. | Nothing; section 2 says so. (Later built: see "Pictures".) |
| A picture should be sent as a multipart form, the usual way to send a file. | design | reject | Python's `cgi` module, which read those, is gone since 3.13, and splitting the parts by hand is fiddly. | The picture is base64 inside the JSON of `POST /posts`: one request, and the JSON-only protection still covers it. |
| Pictures should be files in a folder, as big sites keep them. | design | reject | A file and its row could disagree, and a file path could be tricked into reading another file. | A `pictures` table with the bytes in a BLOB; `GET /pictures/<id>` reads only digits. |
| A phone photo can carry the place it was taken (EXIF GPS). | security | accept | Sharing a place should be a choice, never an accident. | The page draws a JPEG again on a canvas before sending, which leaves EXIF behind. GIFs are sent as they are. |
| The page should check every rule, not only an empty post. | design | reject | The server is where the rules count, and a long post shows the server refusing it. | Nothing. |
| A `like_count` column on `posts` would save counting the rows every time. | design | reject | Two copies of one fact can drift apart, and this timeline is far too small for that to cost anything. | Nothing; the count is `COUNT(*)`. |
| `GET /posts?after=<id>` never carries a like, so other windows would never see one. | design | accept | It would have looked like a bug in the polling, when it is really what `after` means. | A request of its own, `GET /likes`, asked for in the same once-a-second tick. |
| A model check alone cannot stop two likes that arrive at the same moment. | design | accept | The server is threaded, so the race is real, not theoretical. | `PRIMARY KEY (post_id, user_id)`, so the database refuses the second row. |
| Without accounts, a person can like twice by typing another name. | product | accept | Honest about what "one like each" can mean with no sign-in. | Accounts: a like belongs to a signed-in user, found from the cookie. |
| Anyone can post as anyone by typing their name. | security | accept | It is the reason accounts exist. | Who is asking comes only from the session cookie; a name in the JSON is never read. |
| Anyone can claim an old name from before accounts, by signing up with it first. | security | accept (owner's decision) | The old names never had passwords, so there is no way to tell who they belonged to. The timeline is small and the people know each other. | The first sign-up claims it, in one `UPDATE … WHERE password_hash IS NULL`, so only one can win. |
| Sign-up says "That account name is taken", so it shows which names exist. | security | accept | Every name is shown next to every post anyway. Login still gives one message for a wrong name and a wrong password. | Nothing. |
| There is no limit on login attempts, so a password can be guessed over and over. | security | accept for now | 600000 rounds make each guess slow, and the server listens on `127.0.0.1` only. | Nothing here; it is its own feature, `rate-limit`. |
| A copy of `timeline.db` would give away every password and every login. | security | accept | A file can be copied. | Only a salted, slow hash of each password, and only a hash of each session token, are kept. |
| A form on another website could post with a signed-in person's cookie. | security | accept | That is how cross-site request forgery works. | `SameSite=Strict` on the cookie, and every request with a body must be `application/json`, which another site cannot send without the server agreeing. |
| A display name with a line break or a direction mark could fake a line in the terminal or look like someone else. | security | accept | Both are invisible on screen. | `check_display_name` refuses them, and the log line puts the post's text in quotes. |
| One `POST /likes` that flips the like would be half the code of a second route. | design | reject | It can do the opposite of what was meant: a heart that looks unpressed because the same person liked it in another window would be *unliked* by a press meant to like it. | Nothing; `DELETE` says what happens. |
| Taking back a like that is not there could just succeed, since the end state is the same. | design | reject | A refusal with a sentence is how every other rule here answers, and the page already stops the press that would cause it. | Nothing; it is refused. |
| `remove_like` could look for the row and then delete it. | design | accept | Two presses at once would both look, both see the row, and both try to delete it. | One `DELETE`, and `cursor.rowcount` says whether it was there. |
| Two fast presses send two requests, because the first answer has not come back yet. | design | accept | The heart is the page's own idea of the truth, so the page has to hold it still. | A flag in `app.js`: one press at a time. |
| A draft on a shared computer is private text left behind. | security | accept | `localStorage` is plain text that anyone at this browser can read. | The draft is deleted on log out, and the box is emptied whenever nobody is logged in. |
| Save the draft only after the person stops typing ("debounce"). | design | reject | A draft is a few hundred characters, and saving it takes far less than a millisecond. A timer would lose the last words if the tab closed. | Nothing; it is saved on every change. |
| Keep drafts on the server, so they follow you to another device. | product | reject | A new table and a new route, for a rare need. | Nothing; a draft stays in this browser. |
| Keep the rate-limit counts in memory, in a Python dictionary. | design | reject | It needs a lock, and a restart would clear every limit, including the wrong-password one. | A table, `attempts`; `BEGIN IMMEDIATE` makes two requests at once take turns. |
| Count wrong logins by address, not by account name. | security | reject | Every request comes from `127.0.0.1` today, so five wrong passwords by anyone would stop everyone. | Counted by the lower-case account name. A stranger can hold one account for 10 minutes; a window already logged in is not touched. |
| Rate limiting is about requests, so it belongs in the controller. | design | reject | "At most 5 posts a minute" is a rule about what a person may do, like "at most 280 characters", and the counts are rows. | `use_allowance` in the model, called from `save_post`, `add_like`, `remove_like`, `log_in` and `create_account`. |
| Pressing during the wait should make the wait longer. | design | reject | Then the wait the server names would not be true. | Only allowed attempts are counted, and a mistake (an empty post, no such post) is refused before counting. |
| Use SQLite's full-text search (FTS5) for search. | design | reject for now | A second copy of every post, three triggers to keep it in step with edits and deletes, an upgrade, and its `trigram` mode cannot find two-character Japanese words like 東京. | `LIKE` in one model function, `search_posts`; moving to FTS5 later changes only that function. |
| Keep tags in a `tags` table. | design | reject | A tag is already in the text: one fact, one place. | `tags_in` finds them in the text; `has_tag` checks them inside the SQL. |
| A search for `100%` would find every post, because `%` means "anything" in `LIKE`. | design | accept | The person meant the sign. | `escape_like`, and `ESCAPE '\'` in the SQL. |
| Print each search in the terminal, like each post. | security | reject | A search can say what a person is worried about, and the terminal is shown on a screen in class. | `GET /search` is not printed. |
| Filter tags in Python after the SQL. | design | reject | Then 50 `#catalog` posts would use up the limit and hide a real `#cat`. | The tag rule is a SQL function, so the `LIMIT` counts only real matches. |

## Groundwork

Many planned features change the same few places: how a post is drawn, the click handler, the
query that lists posts, and the `INSERT` that adds one. Groundwork gives each of those one shared
shape first, so each feature adds a few lines in its own place. **Nothing a person can see
changes.**

- **The page builds a post from slots.** `makePostItem` makes four empty slots (`head`, `body`,
  `foot`, `menu`) and runs each registered part to fill them. The slots take no room on screen, so a
  post looks exactly as before. Every button says what it does with `data-action`, and one click
  handler looks it up in `ACTIONS`. Each post has a "⋯" menu, hidden while it is empty. Views
  (`showView`, `addView`) switch between sections of the page; the switch is hidden while there is
  one view.
- **One filter for every list of posts.** `select_posts` is the only place that reads a list of
  posts, and it always adds `visible_to(viewer)`. Today that allows every post. Later, blocking and
  reporting each add one condition there, and every list obeys it.
- **One place that adds a post.** `insert_post`, with extra columns only from a fixed list.
- **A safe way to change a table.** `rebuild_table` makes a table again from its own `CREATE` text,
  keeping every row, index and trigger, in one transaction, with the foreign keys checked.
- **Post ids are never reused.** `posts.id` now has `AUTOINCREMENT` (database version 2). Without
  it, deleting the newest post would give its id to the next post, and windows that had already
  seen that id would never show the new one.
- **Two small controller fixes.** A body over 4 MB gets `413` before it is read, and an unknown
  path gets one sentence: "There is nothing to {method} at {path}."

## Long posts

A post can be up to 560 characters (140, then 280, then 560: each step doubles).

- **The limit is written in two places only:** `MAX_TEXT` in `server.py` and `MAX_TEXT` in
  `app.js`. A test fails if they differ. The count under the box is written by the page from
  `MAX_TEXT`, so `index.html` holds no number.
- **One character is one code point on both sides.** A *code point* is one Unicode number.
  Python's `len()` counts these. JavaScript's `.length` counts something else (UTF-16 units), so
  the page uses `characterCount(text)`, which is `[...text].length`. So 😀 is 1 on both sides, and
  the family emoji 👨‍👩‍👧 is 5 on both sides. The count never says "fine" for a post the server
  will refuse.
- **A post taller than 6 lines folds.** It is measured by height on the page, not by counting
  characters, because each line break starts a new line and a phone fits fewer words on a line.
  The CSS class `collapsed` uses line clamp, which cuts between two lines and ends with "…".
  A **Show more** button opens it, and becomes **Show less**. A short post has no button.
- **How it fits the groundwork.** A post part (`expandablePart`) folds the text after the text
  part has filled it, and the button has `data-action="expand"`, handled by `ACTIONS.expand`.
  Neither `showPost` nor `clickOnTimeline` changed. A height can be measured only on the page, and
  a part runs before the post is placed, so a `ResizeObserver` (the browser calls a function when an
  element changes size) measures each text when it first appears, when the window is resized, and
  when a hidden view is shown.
- **For a screen reader**, the text is only clipped, never hidden, so the whole post is read. The
  button is a real `<button>` with `aria-expanded` and `aria-controls`.
- `page-only/` keeps its own limit of 280. Its `style.css` has the new rules only to stay a copy.

## Who liked a post

Under every post with likes, one line says who liked it: *You, Anika, and 10 others liked this
post*. Clicking the line, or the number by the heart, opens everyone who liked it.

- **No database change.** A like is a row that points at a user, not a number, so the names were
  already there. If the app had kept only `like_count = 3`, this feature could never say who.
- **Two new routes**, both open to anyone, signed in or not:
  `GET /likers?post_id=7` gives everyone who liked one post, A to Z by account name (capitals
  ignored), at most 50, plus the total. `GET /likesummary?post_ids=3,7,9` gives the line for up to
  100 posts at once: the count, whether *you* liked it, and the names to show. They are new paths,
  not a second shape of `GET /likes`: one path, one shape of answer.
- **Why A to Z, and not newest first:** `likes` has no time, and SQLite's hidden `rowid` can change
  when the file is tidied (`VACUUM`), so it is not an order to rely on.
- **Who is named:** the two most *popular* people who liked it. Popular means how many likes their
  own posts have received from other people, counted from `likes` each time and never stored.
  Not how many posts they wrote (posting a lot is not popularity), and not their likes on their own
  posts. Ties go A to Z. If you liked the post, *You* comes first, then one more name. The server
  decides who is named; the page only puts it into words.
- **How the page asks:** no new polling. When `GET /likes` (asked every second already) shows that
  a post's count, or your heart, changed, the page asks for all the changed lines in one request.
  An open list is asked for again at the same moment.
- **Every sentence is one template** (*{first}, {second}, and {count} others liked this post*),
  never joined from pieces, so another language can put the names in its own order.

## Times

- **The server saves every time in UTC** (Coordinated Universal Time, the one clock the whole
  world agrees on), as text to the second: `2026-10-02T07:42:10Z`. The `Z` means "this is UTC".
  As text it sorts in time order, and a person can read it in `sqlite3`. The time comes from the
  server's own clock (`utc_now`), never from the request.
- **The page shows it in the reader's own time zone and language.** A post says "just now",
  "5 minutes ago", "yesterday" or "3 days ago", and after a week the date ("2 Oct"). The words are
  written again every 30 seconds. Holding the mouse over the time shows the full date and time.
- **The order never uses the time.** The timeline, and `GET /posts?after=`, use the post id. Ids
  only go up; a clock can jump backwards, and two posts can share a second.
- **Old posts have no date.** Before this, a post kept only `HH:MM`. That cannot become a real date
  honestly, so the upgrade (database version 3) moves it to `old_clock_time` and leaves `posted_at`
  empty. The page shows "15:42 · date unknown". It never guesses a date.

## Search

A search box at the top finds every post with a word (`library`) or a tag (`#cat`). Anyone can
search, signed in or not. The results show newest first in their own view, **Search results**,
with a **Back to the timeline** button.

- **One route:** `GET /search?q=library%20late` answers `200 {"posts": [...], "more": false}`, each
  post exactly as `GET /posts` gives it. An empty search, one over 100 characters, or one of more
  than 5 words gets `400` and the rule it broke. It is its own path, not a second meaning of
  `GET /posts?after=`, which every window asks every second.
- **At most 50 results, no paging.** `"more": true` says there were more, and the page says
  "Showing the newest 50 posts with …".
- **`LIKE`, not a search index.** `LIKE '%word%'` asks SQLite "does the text contain this?". It reads
  every post each time, but this timeline is far too small for that to matter, and it needs no new
  table, no upgrade, and nothing to keep in step when a post is edited or deleted. In a `LIKE`
  pattern `%` means "any characters" and `_` means "any one character", so `escape_like` puts `\`
  in front of `%`, `_` and `\` itself, and the SQL says `ESCAPE '\'`: a search for `100%` finds
  "100%". Every word must appear, in any order. A–Z ignore capitals.
- **Tags are found in the text, not kept in a table.** A tag is already in the post, so a table
  would be a second copy of one fact. `TAG` (in `server.py`, and the same text in `app.js`) says
  what a tag is: `#` and then letters, digits, `_`, or Japanese (hiragana, katakana, kanji, `々`,
  half-width katakana). A tag search `#cat` uses `LIKE '%#cat%'` and then the SQL function `has_tag`
  (the Python `tags_in` rule, given to SQLite), so `#cat` does not find `#catalog`, and the 50-post
  limit counts only real matches.
- **Japanese works** because `LIKE` looks for characters, not words: `東京` is found inside
  `東京は雨です`. A Japanese full-width space splits words. It is exact otherwise: full-width `ＡＢＣ`
  is not `ABC`, and hiragana is not katakana.
- **Every list goes through `select_posts`**, so `visible_to` applies to search too. Searching only
  reads: it never adds a user or changes a row.
- **The address says the search:** `/?q=%23cat`. The browser's Back and Forward work, and a link to
  a search opens with the search done. `links-and-tags` will make each `#tag` a link to that address,
  and call `searchFor("#cat")` on a click.
- **Results do not update by themselves**, and their hearts are greyed out ("Open the timeline to
  like"): a heart is kept up to date only on the live timeline. Searches are not printed in the
  server's terminal, because what a person searched for is their own business.

## Timeline flow

New posts that arrive while you read lower down no longer push the list down. They wait behind a
sticky **"3 new posts"** button at the top; pressing it shows them, goes to the top of the list and
moves keyboard focus there. If the top of the list is on screen, new posts appear at once, as
before. Pressing **Post** shows every waiting post. The page also loads only the newest 20 posts
when it opens, and 20 older ones each time the bottom comes near, until it says
**"No older posts."**

- **`before` and `after`.** `GET /posts?after=12` gives every post newer than 12, oldest first.
  `GET /posts?before=300` gives at most `PAGE_SIZE` (20) posts older than 300, newest first;
  `before=0` means "from the very newest". Each order is the order the page puts them on screen:
  new posts go on top one by one, older posts at the bottom one by one. Asking for both is `400`.
- **Why ids and not page numbers.** With page numbers (`OFFSET 40`), a new post arriving between
  two pages pushes every post down one place, so one post is shown twice. With ids, a new post
  cannot change which posts are below 300. `posts.id` is the table's own row number, so this is read
  straight from its index.
- **The server decides the size.** The page cannot ask for more than `PAGE_SIZE`. It has the same
  number only to know that a short page is the last one.
- **`/likes?from=`.** Every second the page asks for like counts only from the oldest post on
  screen up, so the answer does not grow with every liked post in the database. Leaving `from` out
  gives every post, as before.
- **Loading older posts** uses an `IntersectionObserver` (a browser feature that tells the page
  when an element comes on screen), 400 pixels early. The "Show older posts" button stays for
  keyboard and screen-reader users, and for a browser where the observer does not fire.
- **Checked by hand:** two windows, 45 posts. In window A scroll down; in B post twice. A's list
  does not move and the button says "2 new posts". Press it: both appear, at the top. Scroll to the
  bottom of A: older posts load, and at the end it says "No older posts." Scroll back to the top
  while a post waits: it appears within a second. Tab to "Show older posts" and press Enter.

## Bookmarks

A signed-in person presses ☆ on a post to save it (★), and presses again to take it back.
"My bookmarks" shows only the posts they saved, newest post first.

| | Likes | Bookmarks |
|---|---|---|
| One row per person per post; the database refuses a second | yes | yes |
| `POST` adds, `DELETE` removes; a removed row is deleted, never marked | yes | yes |
| Who is asking comes from the cookie, never from the JSON | yes | yes |
| A public count | yes | **no count anywhere** |
| Who can read it | anyone | **only you**: `GET /bookmarks` is 401 when signed out |
| Asked for every second | yes | **no** |
| Primary key | `(post_id, user_id)` | `(user_id, post_id)`: always read for one person |
| Answer to a press | `{post_id, like_count}` | `{post_id, bookmarked}` |

- **Private.** `post_to_json`, `POSTS_WITH_AUTHORS` and `likes_to_json` never mention bookmarks, so
  the public answers have nowhere to carry one. A test checks that `GET /posts` and `GET /likes`
  give the same bytes before and after a bookmark. `GET /bookmarks` reads no query string:
  `?user=aiko` is ignored. No terminal line is printed for a bookmark.
- **Not polled.** Bookmarks change only when you press a ☆, and the answer says what is now true.
  The page asks `GET /bookmarks` when someone logs in, when "My bookmarks" opens, and after a
  refused press (a second tab may have changed it).
- **The list goes through `select_posts`**, so a post hidden from you (block, report) is left out.
- **A deleted post leaves the list.** Both ids are `ON DELETE CASCADE`: if a post or a user row is
  deleted, the database deletes its bookmarks too.
- In the data model: `bookmarks (user_id, post_id)`, both pointing at their rows, nothing else.

## Place

- **A post can say where it was written.** Optional. The writer types it ("Osaka", "home"), up to
  40 characters, with no line breaks or hidden characters. Everyone sees it after the time:
  *Aiko Tanaka @aiko 15:42 · Osaka*. The box's label says "anyone can see this".
- **Typed, not found by geolocation.** The browser can find where a device is, often to a few
  metres. Shown to everyone, that would tell people where someone lives, and turning the numbers
  into a town name would need someone else's service. A typed place is a label the writer chooses.
- **A column on `posts`, not on `users`.** `posts.place` is text or NULL; NULL means no place,
  never `''`. The database has `CHECK (place IS NULL OR length(place) BETWEEN 1 AND 40)`. A place
  belongs to one post: on `users` it would change every old post, and keep where each person is.
- **Remembered only in this browser.** The page keeps the last place in `localStorage`
  (`timeline-place`), never on the server, and forgets it on Log out, for shared computers.

## Pictures

- **One picture on a post**, a PNG, JPEG, GIF or WebP file, up to 2 MB, with a description (alt
  text, 1 to 200 characters) for people who cannot see it. A post still needs its words.
- **It travels as base64 inside the JSON of `POST /posts`.** Base64 writes any bytes as plain
  letters. It is about a third bigger, which fits in the 4 MB request limit. Not a multipart form:
  Python's `cgi` module, which read those, is gone, and the JSON-only rule already stops another
  website from posting as you.
- **The kind comes from the first bytes** (the "magic number"), never from the file's name or the
  type the browser says. WebP needs `RIFF` and then `WEBP`, because a WAV sound also starts with
  `RIFF`. SVG is never accepted: it is text, and it can hold a script.
- **It is kept in the database**, in a `pictures` table: the post's id (its primary key, so one
  picture per post), the kind, the description and the bytes (a BLOB). `ON DELETE CASCADE` removes
  it with its post. CHECKs keep the kind to four words and the size to 2 MB, even if the code is
  got around. Database version 7 adds the table.
- **`GET /pictures/<post id>`** reads only digits from the address, and no part of the request is
  ever a file name. It sends the type the server found, `X-Content-Type-Options: nosniff` (the
  browser must not guess another type), and `Content-Security-Policy: default-src 'none'; sandbox`
  (nothing in it can run, even opened on its own). It looks for the post through `select_posts`,
  so a post this viewer may not see has no picture either: 404.
- **The page draws a JPEG again before sending it**, on a `<canvas>`. Only the picture is drawn,
  so the hidden EXIF notes, and any GPS place in them, are left behind. The browser turns the photo
  the right way up as it draws. A big photo is made smaller until it fits 2 MB. A GIF is never drawn
  again, so it still moves. The server checks every picture anyway.

## 8. Build or borrow

- **Built:** the page, the server and the data model.
- **Borrowed:** Python and its standard library, SQLite (which comes with Python), and the browser.

---

## Files

```
README.md            what it is, how to run it, things to try
AGENTS.md            what each file does, for an AI agent working here
DESIGN.md            this document
Makefile             make run · make test · make reset
.claude/launch.json  starts the backend version from the Claude Code desktop app
page-only/           open index.html; nothing to start
  index.html  style.css  app.js
with-backend/        make run, then http://localhost:8009
  index.html  style.css  app.js
  server.py          controller · model · view, labelled
  test_server.py     unittest: the rules, accounts and sessions, the upgrade of an older
                     file, saving, "after", likes and unlikes, real round trips, one whole
                     journey through all three levels, and the page and server agreeing
```

`timeline.db` is created next to `server.py` and is git-ignored. `make reset` deletes it.
