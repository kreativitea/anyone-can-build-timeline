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

- No accounts, passwords or sign-in. Each window types a display name. A person is their name, so
  a like can only be *one like per name*, not one per person: someone who types another name can
  like the same post again. Real one-per-person likes need sign-in, which is why that is the first
  thing this list gives up.
- No follows, replies, deleting or editing. They are left for whoever extends the app.
- No pictures. A picture needs a second kind of storage for its files, which is a design of its own.
- No realtime connection (no WebSockets). The page asks for new posts once a second.
- Nothing reachable from another machine. The server listens on `127.0.0.1` only.
- No libraries, no install, no build step.

## 3. Screens

One screen, the same in both versions:

- **The timeline.** A name field at the top, a *What is happening?* box with a live count
  (*x / 280*) and a **Post** button, and the timeline below it, newest first (author, text, time,
  and a heart with the number of people who pressed it). Its one job: show everyone's posts, and
  take a new one. A heart you have pressed is shown in a different colour, and pressing it again
  takes the like back.

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
| **Data** (runs on the server) | the browser's `sessionStorage` | `timeline.db`, one SQLite file with three tables, `users`, `posts` and `likes`, created by the server when it starts |

**Technologies, and why each one.**

- **Plain HTML, CSS and JavaScript.** Three files, each with one job: structure, looks, behaviour.
- **Python 3 standard library only** (`http.server`, `sqlite3`, `json`). Python ships on a Mac, so
  there is nothing to install. The code avoids anything newer than Python 3.9.
- **SQLite.** One file, no database server of its own, and the `sqlite3` command can open it.
- **Polling, once a second.** `fetch('/posts?after=<last id>')` and `fetch('/likes?author=<name>')`
  on a timer: each window asks the server *anything new?* It is the simplest thing that works.
- **`sessionStorage`, not `localStorage`, for the page-only version.** Two normal windows of one
  browser share `localStorage`, which would make the page-only version look shared. `sessionStorage`
  belongs to one window, as each person's phone has its own storage, and it survives a reload.

**The interfaces.**

| Request | What goes in | What comes out |
|---|---|---|
| `POST /posts` | `{"author": "Aiko", "text": "the library is open late tonight"}` | the saved post, with its `id` and `posted_at` · or `400` with the rule it broke |
| `GET /posts?after=12` | the last `id` this window has | every post with a larger `id`, oldest first |
| `POST /likes` | `{"author": "Ben", "post_id": 7}` | `{"post_id": 7, "like_count": 3}` · or `400` with the rule it broke |
| `DELETE /likes` | `{"author": "Ben", "post_id": 7}` | the same answer, with the count one lower · or `400` if there was no such like |
| `GET /likes?author=Ben` | the name this window has typed | `{"counts": {"7": 3}, "mine": [7]}`: how many likes each post has, and which posts this name has liked |
| `GET /` and the three files | nothing | the page |

Pressing a heart is one idea to a person, but two requests: the **method** says which, so `POST`
adds a like and `DELETE` takes one back. The page decides which to send by looking at the heart it
is showing, because "a second press" is a thing on a screen, not a rule. The server is told plainly
which of the two to do, and never guesses.

A like changes no post, so `after` would never carry one: a like on an old post makes no new post
row. That is why the counts have a request of their own, and why it returns *all* of them each
time. `mine` is what lets a window show the right hearts as pressed after a reload, instead of the
page having to remember.

**The model's rules:** text is not empty after trimming · text is at most 280 characters · author
is not empty, at most 40 characters · a like says which post it is for, and that post exists · the
same name cannot like the same post twice · a like cannot be taken back if it was never there. The server checks them even though the page checks for an
empty post too, because a user can change anything that runs on their own device.

## 5. The data model

Three tables:

| `users` | |
|---|---|
| `id` | integer, primary key, given by SQLite |
| `name` | text, the display name, unique |

| `posts` | |
|---|---|
| `id` | integer, primary key, given by SQLite |
| `author_id` | integer, foreign key: the `id` of a row in `users` |
| `text` | text |
| `posted_at` | text, `HH:MM`, local time |

| `likes` | |
|---|---|
| `post_id` | integer, foreign key: the `id` of a row in `posts` |
| `user_id` | integer, foreign key: the `id` of a row in `users` |
| | `PRIMARY KEY (post_id, user_id)`: the two together, so each pair can appear only once |

Example rows: `users` `1 · Aiko` · `2 · Ben` · `posts` `1 · 1 · the library is open late tonight ·
15:42` · `2 · 2 · thanks! · 15:42` · `likes` `1 · 2` (Ben liked post 1).

There are no accounts, so a user is found by name: the first post with a new name adds that person
to `users`, and every later post with the same name points at the same row. Each name is kept once,
and each post points at its author by number. A like works the same way: it points at a post and at
a user, both by number, and nothing else.

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

1. When a post is sent with text, it should come back with an `id` and a time, and the same name
   should always point at the same user.
2. When a window asks for posts after an `id`, it should get only newer posts, oldest first.
3. When two windows are open on the backend version, a post from one should appear in the other
   within a second, and a heart pressed in one should change the count in the other within a second.
4. When a heart is pressed a second time, the like should be taken back: the row should be gone, the
   count one lower, and liking it again should work. When a window that has the heart wrong presses
   it, the server should refuse and say why, and the page should ask again rather than guess.
5. **And when it goes wrong:** when a post is empty, or longer than 280 characters, the server
   should refuse it and say which rule it broke. A like with no name, or for a post that does not
   exist, should be refused the same way. When the server is stopped, the page should say
   *Cannot reach the server*, and recover by itself when the server starts again.

Sentences 1, 2 and 4, and the first half of 5, are checked by `make test`. Sentence 3 and the second
half of 5 are browser behaviour, and are checked by hand, in two windows.

`make test` also walks one whole journey end to end, in `JourneyTest`: two people like and unlike
the same post through the real server over real HTTP, and after every step the database file is
opened and read with SQL, so a step is believed only if the rows agree with what the page was told.
Every request it sends is one `app.js` really sends, with the same method and the same JSON. The
page's own JavaScript is not run by it — that would need a browser or Node, and this project needs
only `python3` — so `PageAndServerAgreeTest` reads `app.js` instead and checks that every request it
names is one the server answers. A route renamed on one side and not the other fails there.

---

## 7. Adversarial review

| Objection | About | Decision | Why | What changed |
|---|---|---|---|---|
| Two normal windows share `localStorage`, so the page-only version looks shared. | design | accept | It hides the one thing the app exists to show. | The page-only version uses `sessionStorage`. |
| The error message says "280" even if the limit is changed. | design | accept | A rule should be written in one place. | The message reads the limit from the rule. |
| The author's name is copied into every post, so a rename would break old posts. | design | accept | One fact, one place, even without accounts. | A `users` table; each post points at its author by `author_id`. |
| Pictures would make posts more realistic. | product | reject | A picture needs file storage as well as the database. | Nothing; section 2 says so. |
| The page should check every rule, not only an empty post. | design | reject | The server is where the rules count, and a long post shows the server refusing it. | Nothing. |
| A `like_count` column on `posts` would save counting the rows every time. | design | reject | Two copies of one fact can drift apart, and this timeline is far too small for that to cost anything. | Nothing; the count is `COUNT(*)`. |
| `GET /posts?after=<id>` never carries a like, so other windows would never see one. | design | accept | It would have looked like a bug in the polling, when it is really what `after` means. | A request of its own, `GET /likes`, asked for in the same once-a-second tick. |
| A model check alone cannot stop two likes that arrive at the same moment. | design | accept | The server is threaded, so the race is real, not theoretical. | `PRIMARY KEY (post_id, user_id)`, so the database refuses the second row. |
| Without accounts, a person can like twice by typing another name. | product | accept | Honest about what "one like each" can mean with no sign-in. | Nothing in the code; section 2 says so. |
| One `POST /likes` that flips the like would be half the code of a second route. | design | reject | It can do the opposite of what was meant: a heart that looks unpressed because the same name liked it in another window would be *unliked* by a press meant to like it. | Nothing; `DELETE` says what happens. |
| Taking back a like that is not there could just succeed, since the end state is the same. | design | reject | A refusal with a sentence is how every other rule here answers, and the page already stops the press that would cause it. | Nothing; it is refused. |
| `remove_like` could look for the row and then delete it. | design | accept | Two presses at once would both look, both see the row, and both try to delete it. | One `DELETE`, and `cursor.rowcount` says whether it was there. |
| Two fast presses send two requests, because the first answer has not come back yet. | design | accept | The heart is the page's own idea of the truth, so the page has to hold it still. | A flag in `app.js`: one press at a time. |

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
  test_server.py     unittest: the rules, saving, "after", likes and unlikes, real round
                     trips, and one whole journey through all three levels
```

`timeline.db` is created next to `server.py` and is git-ignored. `make reset` deletes it.
