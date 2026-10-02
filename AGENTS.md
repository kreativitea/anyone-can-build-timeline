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
| `with-backend/app.js` | Asks the server who is logged in, sends sign-ups, logins, log-outs, posts, likes and likes taken back, and asks for new posts and new like counts every second. Remembers the Colours choice in `localStorage`. It keeps a half-written post in this browser's `localStorage`, one per account, removed after posting or logging out. It shows who liked each post, and asks for the names only when a count changes. It searches posts (`GET /search`) and shows the results in their own view. It asks for the newest page of posts, older pages on scroll, and holds new posts behind a "3 new posts" button while you read lower down. It sends bookmarks and bookmarks taken back, and asks for your bookmarks (never every second). It remembers the last place typed (`timeline-place`), forgotten on log out. |
| `with-backend/server.py` | The backend, in three labelled parts: **controller**, **model**, **view**. |
| `with-backend/words.js` | Every word the page shows, by key (`WORDS`). English only for now; Japanese comes later. |
| `with-backend/test_server.py` | The checks for `server.py`, and for the page and the server agreeing. |
| `with-backend/timeline.db` | The database, in eight tables. The server creates it when it starts, and brings an older one up to date. It is not in git. |
| `Makefile` | Short commands: `make run`, `make test`, `make reset`, `make worktree BRANCH=name`. |

The Colours choice (Auto, Light or Dark) is the only thing the page keeps in `localStorage`
(storage in the browser that stays after the tab closes). It never goes to the server.

The three parts of `server.py`:

- **Controller** (`TimelineHandler`): reads each request and picks what to do. `POST` adds, `DELETE`
  removes: the method says what happens, so the controller never has to guess. It reads who is
  asking from the session cookie, and answers `401` when nobody is logged in. It never reads a
  name from the JSON. A request with a body must say `Content-Type: application/json`.
- **Model** (`check_name`, `check_display_name`, `check_place`, `check_password`, `check_text`, `check_post_id`,
  `hash_password`, `hash_token`, `create_account`, `log_in`, `user_for_session`, `log_out`,
  `start_session`, `account_for`, `save_post`, `posts_after`, `posts_before`, `check_id_bound`,
  `add_like`, `remove_like`,
  `like_count_for`, `likes_for`, `who_liked`, `check_post_ids`, `like_summaries`, `utc_now`,
  `utc_text`, `use_allowance`, `forget_attempts`, `clock`, `check_query`, `escape_like`, `tags_in`,
  `has_tag`, `search_posts`, `picture_kind`, `check_picture`, `check_alt_text`, `picture_for`,
  `not_blocked_sql`, `find_account`, `add_block`, `remove_block`, `blocks_for`,
  `check_not_blocked_by_author`, `check_parent_id`, `check_reply_parent`, `save_reply`,
  `has_replies`, `visible_replies`, and `create_tables` with its upgrades):
  the rules, and the database, in eight tables:
  - `users`: each person once. `name` is the account name (unique, capitals ignored),
    `display_name` is the name shown, and `password_salt`, `password_hash`, `password_rounds` hold
    a hash of the password. The password itself is never kept.
  - `posts`: each post points at its author by `author_id`. `posted_at` is the time in UTC; a post
    from before timestamps has only `old_clock_time` (`HH:MM`) instead. `place` is where the
    writer said they were ("Osaka"), or NULL for no place (never `''`). A place is a detail of one
    post, so it is a column on `posts`, never on `users`. A reply points at the post it answers by
    `parent_id` (NULL for a normal post).
  - `likes`: one row for each person who liked each post.
  - `sessions`: one row for each logged-in window. It keeps only a hash of the token, the user's id,
    and when it ends. Logging out deletes the row.
  - `attempts`: one row for each allowed attempt that a rate limit counts. No password, no post text.
  - `bookmarks`: one row for each post a person saved, `PRIMARY KEY (user_id, post_id)`, both ids
    `ON DELETE CASCADE`. It is **private**: never counted, never shown to anyone but its owner, and
    never polled. `check_bookmark_post_id`, `add_bookmark`, `remove_bookmark` and `bookmarks_for`
    (read through `select_posts`) take the user id from the cookie, never a name, and never add a
    user. `GET /bookmarks` is 401 when signed out. The view is `bookmark_to_json`.
  - `pictures`: at most one picture for each post (`post_id` is the primary key, `ON DELETE
    CASCADE`): its `kind` (`png`, `jpeg`, `gif` or `webp`), its `alt_text` and its `bytes`.
  - `blocks`: one row for each person who blocked another (`blocker_id`, `blocked_id`).
    `PRIMARY KEY (blocker_id, blocked_id)` stops the same block twice, and
    `CHECK (blocker_id <> blocked_id)` stops anyone blocking themselves. Unblocking deletes the row.

  A name is kept once, in `users`; never copy it into another table. Only sign-up
  (`create_account`) adds a user: posting, liking and reading never do. A like count is never kept
  anywhere: it is counted from the rows in `likes`, so a count and its likes can never disagree.
  Taking a like back deletes its row; nothing is marked as undone. A time is saved as UTC text by
  `utc_text`, and shown by `timeElement` in `app.js`. Errors: `RuleBroken` becomes
  `400`, `NotSignedIn` becomes `401`, `TooFast` becomes `429`. All three are a `Problem`, made
  from a code in `PROBLEMS` (the table of every refusal and its English sentence), never from a
  sentence.

  `who_liked` and `like_summaries` only read: they must never add a user, a like or a session.
  A person's popularity (likes on their own posts from other people) is counted from `likes`
  every time, never stored.
- **View** (`post_to_json`, `picture_to_json`, `posts_to_json`, `account_to_json`, `like_to_json`, `likes_to_json`,
  `likers_to_json`, `summaries_to_json`, `search_to_json`, `blocks_to_json`, `problem_to_json`, `session_cookie`, `post_to_log_line`): turns database rows into the JSON the page reads, the
  cookie, and the one line printed for each new post.

The database knows its own version (`PRAGMA user_version`). An older `timeline.db` from before
accounts is upgraded when the server starts, and keeps every row. Its old users have no password:
the first person to sign up with an old name claims it, and its old posts.

## The shared pieces (groundwork)

These pieces exist so that a feature adds a few lines in its own place, instead of changing the
same functions as every other feature. Use them; do not go around them.

**The page (`with-backend/app.js`).**

- A post is built by `makePostItem(post)`. It makes one `<li class="post">` with four **slots**
  (named places inside the post), in this order: `head` (names and time), `body` (the text),
  `foot` (the heart) and `menu` (the "⋯" menu). Then it calls each **part** in `POST_PARTS`, in
  order: `part(post, slots, item)`. A part fills slots, and may return what it wants to keep. To add
  something to every post, write a part and call `addPostPart(yourPart)`. Never edit
  `makePostItem`.
- `placePost(item, post, where)` puts a built post on the page: `"top"` or `"bottom"`.
  `showPost` builds a post and puts it at the top.
- `postParts[id]` keeps, for each post on the live timeline, its `item`, its `slots`, and what the
  parts kept (the heart keeps `likeButton` and `likeCount`). `removePost(id)` takes a post off the
  page. `redrawPost(post)` builds it again and swaps it in, in the same place.
- Every button in a post says what it does with `data-action` (the heart is
  `data-action="like"`), and carries `data-post-id`. The one click handler, `clickOnTimeline`,
  calls `ACTIONS[action](postId, button)`. To add a button, add `ACTIONS.yourAction = yourFunction`.
  Never edit `clickOnTimeline`.
- `addMenuItem(slots, action, words)` adds a button to a post's "⋯" menu. A menu with nothing in it
  is hidden, so today no post shows "⋯".
- A **view** is a `<section data-view="name">`. `addView(name, words)` adds one, with its button
  in `<nav id="views">`; `showView(name)` shows it and hides the others. The nav stays hidden while
  there is only one view (the timeline).
- Build the page with `textContent`, never `innerHTML`.

**The model (`with-backend/server.py`).**

- **Every list of posts goes through `select_posts`, so `visible_to` always applies.**
  `visible_to(viewer_id)` says which posts this viewer may see, as a piece of SQL (today: all of
  them). `select_posts(connection, conditions, params, viewer_id, order, limit=None)` adds it to
  every query. `posts_after` uses it. `post_by_id` reads one post with no filter, only for the person
  who just wrote it. A test fails if `POSTS_WITH_AUTHORS` is used anywhere else.
- `insert_post(connection, user_id, text, **more)` is the only place that adds a post. An extra
  column must be named in `POST_EXTRA_COLUMNS`; any other name raises `ValueError`. A column name
  never comes from a request.
- `rebuild_table(connection, table, change_sql, user_version=None, prepare=None)` changes a table that SQLite
  cannot change in place. `change_sql` is a function: it gets the table's `CREATE TABLE` text and
  returns the new text. Every row, index and trigger is kept. It is all one transaction, foreign
  keys are checked before it is saved, and if anything is wrong nothing changes. `prepare`, if
  given, makes a small change first in the same transaction (timestamps renames a column with it).
- **Post ids are never reused.** `posts.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, so a deleted
  post's id is never given to a new post. `upgrade_to_groundwork` (database version 2) made this
  change with `rebuild_table`.

**The controller.**

- A request body bigger than `MAX_REQUEST_BYTES` (4 MB) gets `413` before it is read.
- A path the server does not know gets `404` with one sentence: "There is nothing to {method} at
  {path}."

## Search

`GET /search?q=…` finds every post that holds every word of the search (at most 5 words, 100
characters), newest first, at most `SEARCH_LIMIT` (50), with `"more": true` when there were more.
Anyone may search. Searches are never printed in the terminal.

- **Model:** `search_posts` uses `LIKE '%word%'`, with `escape_like` so `%`, `_` and `\` mean
  themselves. It reads through `select_posts`, so `visible_to` applies. A word that is a whole tag
  (`#cat`) must be that tag: `has_tag`, a SQL function made from `tags_in`, checks it inside the
  SQL, so the limit counts only real matches.
- **`TAG` is the one tag rule.** It is in `server.py` and, as exactly the same text, in `app.js`
  (a test checks they match). It covers English letters, digits, `_` and Japanese. `tags_in(text)`
  gives the set of tags in a text, in small letters, without the `#`. Never write a second tag
  pattern: use these.
- **The contract for `links-and-tags`** (and any feature that wants to open a search):
  - Call `searchFor(query)` in `app.js`, for example `searchFor("#cat")`. It puts the search in the
    box, changes the address, asks the server, and shows the **Search results** view.
  - The address of a search is `/?q=` + `encodeURIComponent(query)`, for example `/?q=%23cat`. A tag
    link is `<a href="/?q=%23cat">` made with `createElement`; its click calls
    `event.preventDefault()` and then `searchFor`. Opening the address in a new tab runs the search
    too (`searchFromAddress`), and Back and Forward work (`popstate`).
- **Page:** results are built with `makePostItem` into their own list, `#results-list`, never into
  `postParts`, and shown with `showView("search")`. Their hearts are disabled: liking is done on the
  timeline. The results list uses `clickOnTimeline` too, so other buttons in a post work there.

## Timeline flow (pages of posts)

- The page asks for the newest `PAGE_SIZE` (20) posts with `GET /posts?before=0`, then each older
  page with `before=<the oldest id it shows>`, newest first. `after` stays oldest first. Asking for
  both is `400`. `PAGE_SIZE` is in the model and in `app.js`; a test checks they agree.
- `GET /likes?from=<the oldest id it shows>` gives the counts for those posts only. Without `from`
  it gives every post, as before.
- A filter on which posts the timeline shows goes in `visible_to` (or the SQL of both `posts_after`
  and `posts_before`), never in Python afterwards: a filtered page would be shorter than
  `PAGE_SIZE`, and the page would wrongly say "No older posts."
- In `app.js`, new posts go through `receiveNewPosts` (they wait in `waitingPosts` while the reader
  is lower down), and every post is put on the page by `putPost(post, "top" | "bottom")`, which
  skips a post already in `postParts`. `lastId` is the newest post received, shown or waiting.

## Blocking

A signed-in person can block another account (`POST /blocks`, `DELETE /blocks`, `GET /blocks`, all
with `{"account_name"}` and a login). The block's condition, `not_blocked_sql(viewer_id)`, is one
line in the list of conditions inside `visible_to`, so **every list of posts leaves out the people
the viewer blocked**: the timeline (`after` and `before`), search, bookmarks and pictures. A new
list of posts gets this for free by using `select_posts`. A block is never checked only in the
page: the server leaves the posts out.

- A blocked person can still read the blocker's posts (reading is open to everyone), but cannot
  like them: `add_like` calls `check_not_blocked_by_author(connection, post_id, user_id)`, and
  cannot reply to them: `save_reply` calls it with `what="reply"` (`BLOCKED_CODES`).
- Like counts still include blocked people. `who_liked` and `like_summaries` leave the blocked
  people's *names* out for the person who blocked them; the count stays the same.
- `find_account` only reads: blocking a name that does not exist never adds a user.
- The page: "Block @name" is a "⋯" menu item (`blockPart`, `ACTIONS.block`), only on other
  people's posts when signed in. `hidePostsBy` takes their posts off the page at once.
  `reloadTimeline` draws the timeline again from the newest page (after an unblock, a login or a
  log-out), and starts every timeline-flow mark again.

## Rate limits

A **rate limit** is a rule of the form "at most N times in S seconds". They are written once, in
`LIMITS` in the model: posts 5 a minute and likes 30 a minute (each signed-in user), logins 5 tries
in 10 minutes (each account name), sign-ups 30 an hour (each address). The rule lives in the model,
in `use_allowance(db_path, action, key)`, which counts rows in `attempts` and raises `TooFast`. The
controller turns `TooFast` into `429` with a `Retry-After` header and `{"error", "code", "values", "retry_after"}`;
the page shows the words and turns off that form's button for those seconds (`holdForm`).

- Call `use_allowance` **after** the other rules, so a mistake never uses up the allowance.
- A new way of saving a post must call `use_allowance(db_path, "post", ...)` too.
- Tests never sleep: they put a `FakeClock` in place of `server.clock` and move it forward.
- Reading (`GET`) and logging out are never limited.

## Words

Every word the page shows lives in `with-backend/words.js`. The server never translates: it sends
a code, and the page shows the words for that code. Every feature follows these rules
(`docs/plans/japanese.md`, section 3.4). `make test` checks each one.

1. **A new rule in the model raises a code, never a sentence:** `raise RuleBroken("reply_parent_missing")`,
   or with values: `raise RuleBroken("picture_too_big", limit=MAX_PICTURE_MB)`. `NotSignedIn` for
   401. A refusal the controller makes itself: `self.send_problem(404, Problem("nothing_here", ...))`.
   Never `send_json(4xx, {"error": ...})`.
2. **The code goes in `PROBLEMS`** in `server.py`, with its English, at the end, under a comment
   with your feature's name: `# replies`.
3. **The same code goes in `words.js`**, at the end of `WORDS`, under the same comment, with
   exactly the same English in `en:`. Do not write `ja:`: Japanese is written later, all at once.
4. **Naming:** lower case with `_`. First the thing (`text_`, `like_`, `reply_`), then what is wrong
   (`_empty`, `_too_long`, `_missing`). A value is named by what it is (`limit`, `seconds`,
   `count`, `path`); the name inside `{…}` and the Python keyword are the same word.
5. **A word the page shows is a key in `words.js`,** never a string in `app.js` or `index.html`. In
   `index.html`: `data-words="key"` (or `data-words-placeholder`, `data-words-aria-label`,
   `data-words-title`), with the English left inside. In `app.js`: `say("key", values)`,
   `showStatus("key", values)`, `addView(name, "key")`, `addMenuItem(slots, action, "key")`, or set
   `element.dataset.words = "key"` so a language change rewrites it. Words with values of their own
   (a time, names, a count) are written again by a function given to `whenLanguageChanges(fn)`.
   A server refusal: `showProblem(answer)`.
6. **Words with a number** are two keys, `key_one` and `key_other`, shown with
   `sayCount("key", n, values)`. The number is `{count}`; `values` are any others. A refusal
   with a number is two codes in `PROBLEMS` and `words.js`, `code_one` and `code_other`; raise it
   without the ending, with the number as `count`: `TooFast("post_too_fast", count=1)` says
   "1 second", and the page chooses the same way.
7. **One sentence is one key.** Never join pieces (`say("a") + name`): write one sentence with `{name}`.
8. **What people wrote is never a key:** posts, names, tags, place names. Use `textContent`.
9. **A time or a date** uses `Intl.DateTimeFormat(language, …)` or `Intl.RelativeTimeFormat(language, …)`.
10. **No Japanese in `server.py`**, and no `Accept-Language`.

## Place

A post can say where it was written, as a short place the writer types ("Osaka"), up to
`MAX_PLACE` (40) characters, with no hidden characters (`HIDDEN_CHARACTERS`). `check_place` in the
model checks it (codes `place_too_long`, `place_hidden`), `placeProblem` in `app.js` checks the
same, and `posts.place` has a `CHECK` too. The words are `place_label`, `place_example` and
`post_place` ("· {place}") in `words.js`; the place itself is what a person wrote, never a key.
The page never finds the place by itself (no geolocation). The page shows it after the time as
"· Osaka" (`placePart`, in the `head` slot), and remembers the last place in `localStorage`
(`timeline-place`) until Log out. `upgrade_to_place` added the column; old posts have NULL.

## Pictures

A post may carry one PNG, JPEG, GIF or WebP picture, up to 2 MB (`MAX_PICTURE_BYTES`,
`MAX_PICTURE_MB`), with a description of 1 to 200 characters (`MAX_ALT_TEXT`). A post still needs
its text.

- The page sends it in the JSON of `POST /posts`, as base64 text: `picture` and `picture_alt`.
  `save_post` checks every rule first, then saves the post and its picture in one transaction. A post
  with a picture is still one post for the rate limit.
- The kind is found from the first bytes (`picture_kind`), never from a name or a type the browser
  says. SVG is never accepted. The refusals are the `picture_` codes in `PROBLEMS`;
  `pictureProblem` in `app.js` checks the same rules with the same codes.
- `GET /pictures/<post id>` sends the bytes, with `nosniff` and a `sandbox` Content-Security-Policy.
  It reads only digits from the address, never a path. `picture_for` finds the post through
  `select_posts`, so a post the viewer may not see answers 404, as an unknown one does.
- Each post in `GET /posts` (and in search and bookmarks) has `"picture": {"url", "alt"}` or
  `"picture": null`. The page uses the `url` as it is, and never builds `/pictures/...` itself.
  The picture is a part in the `body` slot. The description is what the writer typed, never a key.
- The page draws a JPEG again on a `<canvas>` before sending it (`redrawJpeg`), so the EXIF notes
  and any GPS place are not sent. GIFs are sent as they are. The server still checks everything.
- `upgrade_to_pictures` (database version 7) added the table.
- Never `select *` from `pictures` in a terminal: it prints the raw bytes.

## Replies

A **reply** is a post with a `parent_id`: the id of the post it answers. It is sent through
`POST /posts` with `parent_id` (missing or `null` means a normal post). The controller only chooses:
no `parent_id`, `save_post`; a `parent_id`, `save_reply`.

- `save_reply` checks the text, then the post it answers (`check_parent_id`,
  `check_reply_parent`: it exists, it is not a reply, its author has not blocked you), then saves
  through `save_post`, so a reply follows the same rules (text, place, picture) and is counted by
  the same rate limit as a post. Codes: `reply_parent_id_missing`, `post_missing`,
  `reply_to_reply`, `reply_blocked`.
- **One level only.** A reply to a reply is refused by `save_reply`, and by the database's trigger
  `replies_are_one_level`, even if the code is got around. Replying to your own post is allowed.
- `parent_id` is a foreign key to `posts(id)`: the database refuses a reply to a post that does not
  exist, and refuses deleting a post that has replies. **`has_replies(connection, post_id)`** says
  whether a post has any; ask it before deleting a post. Nothing ever changes `parent_id`.
- **A reply count is never kept.** Each post comes with `reply_count`, counted from the rows, and
  `newest_reply_id`, the newest reply in that count. Both count only the replies the viewer may
  see: `POSTS_WITH_AUTHORS` has `VISIBLE_REPLIES` (`1 = 1`) in them, and `select_posts` puts
  `visible_replies(viewer_id)` there, made from `visible_to`. So a new condition in `visible_to`
  applies to the counts too, with nothing more to do.
- Each post also comes with `parent_author`, the account name of the post it answers, looked up in
  `users`, never copied into `posts`.
- **The page.** A reply goes under its post: `placePost(item, post, "under-parent")`, in a
  `<li class="reply-thread">` just after the post (so `redrawPost` keeps it, and `removePost` takes
  it away with the post). `placePost` sends every reply whose post is on the timeline there, and
  `adoptReplies` moves replies that came first (in an older page) under their post when it
  arrives. In `receiveNewPosts`, a reply to a post on the page goes under it at once, and
  `countsAsNewPost` keeps it out of "3 new posts". The page adds one to a count only for a reply
  newer than `newest_reply_id`. Reply is `ACTIONS.reply` (`replyPart`, beside the heart). The reply
  is written in the main post box, under "Replying to @aiko · Cancel" (`#replying-to`). A draft
  remembers the post it answers: it is kept as JSON `{"v": 2, "text", "reply_to"}`, and an older
  plain-text draft still loads (`readDraft`). The words are the `reply_` keys, `replying_to` and
  `replies_label` in `words.js`.
- **The hook for `reply-email`** is `TimelineHandler.after_reply_saved(row)`. `take_post` calls it
  only for a reply, after the `201` answer has gone. It does nothing today.
- `upgrade_to_replies` (database version 9) added the column, the index `posts_by_parent` and the
  trigger.

## How to run it

- Page-only: open `page-only/index.html` in a browser. Nothing to start.
- With a backend: `make run`, then open <http://localhost:8009>. Press Ctrl+C to stop.
- Start again with an empty timeline: `make reset`.
- See what is saved:
  `sqlite3 with-backend/timeline.db 'select * from users; select * from posts; select * from likes; select * from sessions; select * from attempts; select * from bookmarks; select * from blocks; select post_id, kind, length(bytes), alt_text from pictures'`

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
