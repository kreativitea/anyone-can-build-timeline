Status: built on branch edit-delete, awaiting merge

# Edit and delete

## 1. What it does

A signed-in person sees **Edit** and **Delete** on their own posts, and only on their own. Edit
changes the words of the post; the post keeps its place, its time and its likes, and shows
"· edited". Anyone can press "· edited" to see every earlier version. Delete removes the post, its
likes and its old versions, after one "Are you sure?". Every window that is already open sees the
new words, or sees the post disappear, within about one second.

This plan also builds the **changes feed**: a list, kept by the server, of "this post changed".
Other plans reuse it (`report` hides a post; `block` may too; a rename could later). See the end of
section 3.

## 2. Decisions for the owner

1. **Delete: remove the rows, or mark them?** (a) *Hard delete*: the `posts` row, its `likes` rows
   and its old versions are deleted. (b) *Soft delete*: the row stays with a `deleted_at` mark, and
   every query must skip marked rows. *Recommendation: (a).* `AGENTS.md` already does this for a
   like ("taking a like back deletes its row; nothing is marked"). With (b), every later plan
   (`search`, `replies`, `bookmarks`, …) must remember to skip deleted posts, and one that forgets
   shows a deleted post again. With (a), a deleted post is simply not there. The cost of (a) is
   problem 1 below (ids reused), which this plan fixes.
2. **When a post is deleted, are its old versions deleted too?** *Recommendation: yes.* The person
   wanted the post gone, so no copy of its words stays. "Every old version is kept" holds while the
   post exists. Only a row in `changes` stays (a post id and the word `deleted`, no text).
3. **Who can see the old versions?** (a) everyone, (b) only the author, (c) nobody: kept in the
   database only. *Recommendation: (a).* The point of keeping them is honesty: a post with 20 likes
   cannot quietly become a different post. Reading is open to everyone already.
4. **Do the likes stay after an edit?** *Recommendation: yes.* The old versions show what was liked.
5. **A time limit on editing** (for example, one hour)? *Recommendation: no limit.* The history
   makes a late edit visible anyway, and a limit is one more rule to keep the same on both sides.
6. **What other windows show.** An edited post: the new words, and "· edited" after the time. It
   does not move to the top. A deleted post: it disappears (no "This post was deleted" in its
   place). *Recommendation: as written.*
7. **The routes.** `PATCH /posts` to edit, `DELETE /posts` to delete, with `post_id` in the JSON
   body, the same way `/likes` already works. *PATCH* means "change part of this thing": only the
   text changes; the author, the time and the likes stay. (*PUT* means "replace the whole thing",
   which is not what happens.) *Recommendation: PATCH and DELETE, as written.*

## 3. Design

### Three problems found in review, and the answers

**Problem 1: SQLite gives a deleted id out again.** `posts.id` is `INTEGER PRIMARY KEY`. Without
the word `AUTOINCREMENT`, SQLite gives a new row the largest id **plus one**. Delete the newest post
(id 3), and the next post is id 3 again. Every window asks `GET /posts?after=3`, so the new post 3
never appears anywhere. With `AUTOINCREMENT`, SQLite remembers the largest id it ever gave (in its
own table, `sqlite_sequence`) and never gives it again. SQLite cannot add `AUTOINCREMENT` to a
table that exists, so the upgrade **rebuilds** `posts` (below).

**Problem 2: `?after=` only brings new posts.** An edit or a delete makes no new post, so open
windows would never hear of it. Answer: a new table `changes`, one row for each "this post
changed", with its own id that only grows. Each window remembers the newest change id it has seen
and asks `GET /changes?after=<that id>` every second, next to the question it already asks.

**Problem 3: a post has rows that point at it.** Foreign keys are ON, so the database refuses to
delete a post while a `likes` row or an old version still points at it. Answer: `delete_post`
deletes those rows first, then the post, all in one transaction (*transaction*: a group of changes
that all happen, or none do).

### Database: `upgrade_to_edit_delete(connection)`

Written like `upgrade_to_accounts`. The orchestrator picks its `user_version` number, written `N`
here. `create_tables` gets one more line: `if version < N: upgrade_to_edit_delete(connection)`. The
version-0 `CREATE TABLE IF NOT EXISTS posts (...)` in `create_tables` does **not** change, so a new
database and an old one take the same steps.

Steps, in this order:

1. `PRAGMA foreign_keys = OFF`. This must come **before** `BEGIN`: inside a transaction SQLite
   ignores it. While `posts` is dropped and made again, `likes` points at a table that is briefly
   not there; with foreign keys on, that would fail or delete rows.
2. `BEGIN`.
3. Read the `CREATE TABLE` text of `posts` from `sqlite_master`, and the `CREATE` text of every
   index and trigger on `posts` (`type IN ('index', 'trigger') AND tbl_name = 'posts' AND sql IS
   NOT NULL`). Other plans may have added a column, an index or a trigger before this one is
   merged; this keeps all of them.
4. If the text already has `AUTOINCREMENT`, skip to step 6. Otherwise, it must match
   `^CREATE TABLE "?posts"? \(id INTEGER PRIMARY KEY,`. Replace that start with
   `CREATE TABLE posts_new (id INTEGER PRIMARY KEY AUTOINCREMENT,`. If it does not match, roll
   back, turn foreign keys on, and stop with `SystemExit("timeline.db has a posts table this
   upgrade does not know. Run make reset, then start again.")`.
5. Make `posts_new` from that text. `INSERT INTO posts_new SELECT * FROM posts` (the same text
   means the same columns in the same order, so every id, and every column another plan added,
   is copied). `DROP TABLE posts`. `ALTER TABLE posts_new RENAME TO posts`. Run the saved index
   and trigger text again. SQLite sets `sqlite_sequence` to the largest copied id by itself.
   `likes` says `REFERENCES posts(id)` by name, so it now points at the new table.
6. Make the two new tables:
   ```sql
   -- Each earlier version of a post: the words it had, and when they were replaced.
   CREATE TABLE post_versions (
     id INTEGER PRIMARY KEY,
     post_id INTEGER NOT NULL REFERENCES posts(id),
     text TEXT NOT NULL,
     replaced_at INTEGER NOT NULL)          -- seconds since 1970, UTC, like sessions.expires_at
   CREATE INDEX post_versions_by_post ON post_versions (post_id)

   -- One row for each "this post changed". No foreign key: a deleted post is gone, and its
   -- change must stay so that open windows hear about it. AUTOINCREMENT, so a change id is
   -- never given twice, even if old changes are cleared out one day.
   CREATE TABLE changes (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     post_id INTEGER NOT NULL,
     kind TEXT NOT NULL,
     changed_at INTEGER NOT NULL)
   ```
   `kind` has no `CHECK`: SQLite cannot change a `CHECK` without rebuilding the table, and `report`
   and `block` will add kinds. The model checks it instead (`CHANGE_KINDS`).
7. `PRAGMA foreign_key_check`. If it returns any row, roll back and stop with a `SystemExit` that
   says so. (It checks what step 1 turned off.)
8. `PRAGMA user_version = N`, `COMMIT`, then `PRAGMA foreign_keys = ON`.

Any `sqlite3.Error` during steps 2 to 8: roll back, `PRAGMA foreign_keys = ON`, close, stop with a
`SystemExit` message. Nothing is half done.

This rebuild was tried on a copy in memory, with an extra column and an index added the way another
plan would add them: every row, the column and the index were kept; `foreign_key_check` was empty;
after deleting the newest post (id 3), the next post was id 4.

**Every new table that points at `posts`** (in this plan or a later one) says what happens when the
post is deleted: `ON DELETE CASCADE` (delete my row too) or `ON DELETE SET NULL` (keep my row, forget
the post). Then `delete_post` never has to change. `likes` is older and has neither, so
`delete_post` deletes its rows by hand. `post_versions` is deleted by hand too, so the order of
steps can be read in one place.

### Model

New error: `class NotAllowed(Exception)`: the person is signed in, but this is not theirs → 403.

New constant: `CHANGE_KINDS = ("edited", "deleted")`. `report` and `block` add to it.

Changed (small):
- `POSTS_WITH_AUTHORS` gains one column, worked out and never stored:
  `EXISTS (SELECT 1 FROM post_versions WHERE post_versions.post_id = posts.id) AS edited`.
  A post is "edited" exactly when it has an old version, so the two can never disagree.
- `check_post_id`: its message "The like must say which post it is for." becomes "The request
  must say which post it is for.", because edit and delete use it too.

New:
- `post_as_shown(connection, post_id)`: the post as `GET /posts` would show it now
  (`POSTS_WITH_AUTHORS + " WHERE posts.id = ?"`), or `None`. **This is the one place that says
  whether a post is shown.** `report` (hidden posts) changes only this and `posts_after`.
- `own_post(connection, user_id, post_id)`: the post's row, or raise `RuleBroken("That post does
  not exist.")`, or raise `NotAllowed("You can only change your own posts.")`.
- `record_change(connection, post_id, kind)`: checks `kind in CHANGE_KINDS`, inserts one `changes`
  row with `int(time.time())`. It does not commit: it is always part of the caller's transaction,
  so a change is recorded **if and only if** the thing itself happened.
- `edit_post(db_path, user_id, post_id, text)`: `check_post_id`, `check_text` (the same rules as a
  new post). Then `BEGIN IMMEDIATE` (*take the write lock at the start*, so nobody can edit or
  delete between "is it yours?" and the write). `own_post`. If the new text equals the old text:
  `RuleBroken("The post is the same as before.")`, so the history has no empty steps. Insert the
  old text into `post_versions`, `UPDATE posts SET text = ?`, `record_change(…, "edited")`,
  commit. Returns `post_as_shown`.
- `delete_post(db_path, user_id, post_id)`: `check_post_id`, `BEGIN IMMEDIATE`, `own_post`, then
  `DELETE FROM likes WHERE post_id = ?`, `DELETE FROM post_versions WHERE post_id = ?`,
  `DELETE FROM posts WHERE id = ?`, `record_change(…, "deleted")`, commit. If another table still
  points at the post (a plan that forgot `ON DELETE`), SQLite raises `IntegrityError`, everything is
  rolled back, and the post is not deleted: a safe failure, which the tests catch.
- `changes_after(db_path, after)`: returns `(latest, rows)`. `latest` is the newest change id
  (`0` if none). `after` of `None` means "just tell me where you are": `rows` is empty. Otherwise
  `rows` is every change with an id above `after`, oldest first, each paired with
  `post_as_shown(post_id)`. Read in one transaction, so `latest` and `rows` agree.
- `versions_of(db_path, post_id)`: `check_post_id`; the old versions of a post, oldest first
  (`text`, `replaced_at`). An unknown post gives an empty list. Reading needs no sign-in.

Why a change id can be trusted to only grow, with `ThreadingHTTPServer`: SQLite lets only one
transaction write at a time, so change 8 is committed before change 9 is even made. A window can
never see 9 and miss 8.

### Routes

| Request | JSON in | Answer |
|---|---|---|
| `PATCH /posts` | `post_id`, `text` | 200 the post (`post_to_json`). 400 a broken rule, 401 not signed in, 403 not yours |
| `DELETE /posts` | `post_id` | 200 `{post_id}`. 400, 401, 403 as above |
| `GET /changes` | — | 200 `{latest, changes: []}`: where the feed is now |
| `GET /changes?after=7` | — | 200 `{latest, changes: [{id, post_id, kind, post}]}`. 400 if `after` is not a whole number |
| `GET /versions?post_id=3` | — | 200 `[{text, replaced_at}]`, oldest first. 400 if `post_id` is not a whole number |

Both `PATCH` and `DELETE` need `Content-Type: application/json`, through the existing `read_json`.
200 and not 201 for both, because nothing new is created.

Controller:
- New `do_PATCH`: only `/posts` (else 404), `read_json`, then `take_edit(data)`.
- `do_DELETE` gains a `/posts` branch that calls `take_delete(data)`, and its 404 message names
  `/posts` too.
- `do_GET` gains `/changes` and `/versions`.
- New `take_edit(data)`, `take_delete(data)`: `signed_in_user`, call the model, map `RuleBroken`
  → 400, `NotAllowed` → 403.
- `log_message`: `GET /changes` is asked every second, so it is not printed either.

### View

- `post_to_json` gains `"edited": bool(row["edited"])`.
- New `change_to_json(change, post_row)` → `{id, post_id, kind, post}`, where `post` is
  `post_to_json(post_row)` or `None`.
- New `changes_to_json(latest, rows)` → `{"latest": latest, "changes": [...]}`.
- New `deleted_to_json(post_id)` → `{"post_id": post_id}`.
- New `version_to_json(row)` → `{text, replaced_at}`; `versions_to_json(rows)`.

### The changes feed: the contract other plans reuse

A change says only **which post** changed. `post` is that post **as `GET /posts` would show it
right now**, or `null` if `GET /posts` would not show it. So the page needs one rule, whatever the
kind: **`post` is there → draw it again; `post` is `null` → remove it.** `kind` is for people,
logs and tests; the page never looks at it.

- `report`: when a post is hidden, call `record_change(connection, post_id, "hidden")` in the same
  transaction, add `"hidden"` to `CHANGE_KINDS`, and make `post_as_shown` and `posts_after` skip
  hidden posts. No page change.
- `block` is different: what is shown depends on *who* is asking. That plan would give
  `changes_after` and `post_as_shown` a `viewer_id`. This plan does not add an unused parameter.
- A rename (a later plan) changes many posts at once; it would record one change per post, or add
  a new kind of change. Not decided here.

### Page (`with-backend/app.js`)

New state: `let lastChangeId = null;` (`null`: "not asked yet") and `const postItems = {};` (for
each post on screen: its `<li>`, its text `<p>`, and its "· edited" button, kept by id, like
`likeParts`).

Changed (small):
- `showPost`: `item.dataset.postId = post.id;` and `item.dataset.author = post.author;`; the text
  is written through a new `showPostText(textElement, text)` (one line, `textContent`), so
  `links-and-tags` has one place to change; and one call, `addPostTools(post, item, text)`, before
  `timeline.prepend(item)`.
- `checkForNewPosts`: first line inside `try`: `await checkForChanges();`. Changes are asked for
  **before** posts. Then a post edited or deleted between the two questions is still right: an edit
  to a post not yet on screen is ignored, and the post then comes in with its new words; a post
  made and deleted in between is never drawn.
- `showSignedIn` and `showSignedOut`: one line each, `showMyTools();`.
- `clickOnTimeline`: one line at the top, `if (clickOnPostTools(event)) { return; }`.

New:
- `addPostTools(post, item, textElement)`: adds a "· edited" button (`link-button show-versions`,
  hidden unless `post.edited`), and Edit and Delete buttons (`edit-post`, `delete-post`, class
  `owner-only`), and fills `postItems`. Then `showMyTools()` for this post.
- `showMyTools()`: shows the `owner-only` buttons only on posts where `item.dataset.author` is the
  signed-in `account.account_name`; hides them everywhere when signed out. The server checks again.
- `checkForChanges()`: `GET /changes` the first time, then `GET /changes?after=<lastChangeId>`;
  calls `applyChange` for each; sets `lastChangeId = answer.latest`.
- `applyChange(change)`: `change.post === null` → `removePost(change.post_id)`; otherwise
  `redrawPost(change.post)`. A post not on screen is ignored.
- `redrawPost(post)`: new words through `showPostText`; shows "· edited"; if the old-versions list
  is open, closes it (it is out of date).
- `removePost(postId)`: removes the `<li>`; deletes `postItems[postId]` and `likeParts[postId]`,
  so the like polling stops asking about it. `lastId` is not changed: thanks to `AUTOINCREMENT`, the
  next post always has a larger id.
- `startEdit(postId)`: swaps the text for a `<textarea>` holding the current words, with Save and
  Cancel. Only one edit open at a time.
- `sendEdit(postId, text)`: `textProblem(text.trim())` first (the same rule as a new post), then
  `PATCH /posts`. 200 → `redrawPost(answer)`. 401 → `showSignedOut(answer.error)`. 400 / 403 →
  `showStatus(answer.error)`. A `busy` flag, like `pressHeart`, so two fast clicks send one request.
- `deletePost(postId)`: `confirm("Delete this post? This cannot be undone.")`, then
  `DELETE /posts`. 200 → `removePost(postId)`. Errors as in `sendEdit`.
- `toggleVersions(postId)`: `GET /versions?post_id=…`, then shows an `<ol class="versions">` under
  the post: each old text (with `textContent`, never `innerHTML`) and when it was replaced
  (`new Date(replaced_at * 1000).toLocaleString()`). Pressed again, it closes.
- `clickOnPostTools(event)`: finds `.edit-post`, `.delete-post`, `.save-edit`, `.cancel-edit` or
  `.show-versions` and calls the right function. Returns `true` if it handled the click.

`with-backend/index.html` does not change: the new buttons are made by `app.js` for each post.

**CSS.** At the end of `with-backend/style.css`, under `/* edit-delete */`: `.post-tools`,
`.owner-only`, `.edited`, `.edit-box`, `.versions`. The same lines at the end of
`page-only/style.css`, which must stay a copy.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | controller `do_GET` (`/changes`, `/versions`) | change |
| `with-backend/server.py` | controller `do_DELETE` (`/posts` branch, 404 message) | change |
| `with-backend/server.py` | controller `do_PATCH` | add |
| `with-backend/server.py` | controller `take_edit`, `take_delete` | add |
| `with-backend/server.py` | controller `log_message` (skip `GET /changes`) | change |
| `with-backend/server.py` | model `NotAllowed`, `CHANGE_KINDS` | add |
| `with-backend/server.py` | model `create_tables` (one `if version < N` line) | change |
| `with-backend/server.py` | model `upgrade_to_edit_delete` | add |
| `with-backend/server.py` | model `POSTS_WITH_AUTHORS` (one `edited` column) | change |
| `with-backend/server.py` | model `check_post_id` (message only) | change |
| `with-backend/server.py` | model `post_as_shown`, `own_post`, `record_change`, `edit_post`, `delete_post`, `changes_after`, `versions_of` | add |
| `with-backend/server.py` | view `post_to_json` (`edited`) | change |
| `with-backend/server.py` | view `change_to_json`, `changes_to_json`, `deleted_to_json`, `version_to_json`, `versions_to_json` | add |
| `with-backend/server.py` | module docstring, MODEL banner (six tables) | change |
| `with-backend/app.js` | `showPost` (two `dataset` lines, `showPostText`, `addPostTools` call) | change |
| `with-backend/app.js` | `checkForNewPosts` (one line) | change |
| `with-backend/app.js` | `showSignedIn`, `showSignedOut` (one line each) | change |
| `with-backend/app.js` | `clickOnTimeline` (one line) | change |
| `with-backend/app.js` | `lastChangeId`, `postItems`, `showPostText`, `addPostTools`, `showMyTools`, `checkForChanges`, `applyChange`, `redrawPost`, `removePost`, `startEdit`, `sendEdit`, `deletePost`, `toggleVersions`, `clickOnPostTools` | add |
| `with-backend/style.css` | end, `/* edit-delete */` | add |
| `page-only/style.css` | end, the same copy | add |
| `with-backend/test_server.py` | new methods at the end of each class (section 6) | add |
| `with-backend/test_server.py` | `PageAndServerAgreeTest`: the list of routes and methods the page may name | change |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (section 7) | add |

## 5. Depends on, and collides with

- **Depends on `accounts`**: `user_for_session`, `signed_in_user`, `account.account_name` on the
  page, and the JSON-only `read_json`.
- **Should merge early.** It rebuilds `posts`, and it sets the `ON DELETE` rule for every later table
  that points at `posts`. The rebuild copies whatever columns, indexes and triggers exist, so it
  still works if merged later, but earlier is less to check.
- **`report`, `block`**: build on the changes feed (`record_change`, `CHANGE_KINDS`,
  `post_as_shown`). They depend on this plan.
- **`replies`, `bookmarks`, `who-liked`, `pictures`, `reply-email`**: any table or column pointing at
  `posts` must say `ON DELETE CASCADE` or `ON DELETE SET NULL`. Otherwise deleting such a post is
  refused (safely, but refused). `replies` chooses what a reply to a deleted post shows. `pictures`
  must also remove the picture file; that plan adds it to `delete_post`.
- **`timestamps`**: both touch `POSTS_WITH_AUTHORS` and `post_to_json` (one line each; easy to
  rebase). `replaced_at` and `changed_at` are already UTC seconds; `timestamps` may show them its
  way.
- **`search`**: if it adds triggers or an index on `posts`, the rebuild keeps them. An edit is an
  `UPDATE` of `posts.text`, so a search index kept by triggers stays right.
- **`links-and-tags`**: changes `showPostText` only, and both new posts and edited posts get links.
- **`timeline-flow`**: both change `checkForNewPosts` and `showPost`. Its "3 new posts" count must
  not count a post that was then removed (`removePost`).
- **`long-posts`**: none. An edit uses `check_text` and `textProblem`, so the new limit applies.
- **`rate-limit`**: may want to limit edits too. Its choice.
- **`japanese`**: new words on screen (Edit, Delete, Save, Cancel, edited, the confirm question).
- **`dark-mode`**: the new CSS uses the existing colour variables, if there are any.

## 6. Tests

**`ModelTests`**
- The author can edit: the text changes, the old text is one row in `post_versions`, `edited` is
  true, the likes are still there.
- An edit follows `check_text`: empty and too long are refused, and nothing is saved.
- Another user's edit raises `NotAllowed`; the text and `post_versions` are unchanged.
- The same text again is refused. Editing a post that does not exist is refused.
- The author can delete: no `posts` row, no `likes` rows, no `post_versions` rows; one `deleted`
  change.
- Another user's delete raises `NotAllowed`; nothing is removed.
- **An id is never given twice**: three posts, delete post 3, the next post is 4.
- `changes_after(None)` gives `latest` and no rows; after an edit, `changes_after(latest)` gives one
  change with the new post; after a delete, `post` is `None`; edited then deleted gives two
  changes, both with `post` `None`.
- `record_change` refuses a kind not in `CHANGE_KINDS`.
- **The upgrade**: a database made the old way, with posts, likes and an extra column and index
  added the way another plan would: after `create_tables`, every row, id, column and index is kept;
  the `posts` text has `AUTOINCREMENT`; `PRAGMA foreign_key_check` is empty; `PRAGMA foreign_keys`
  is 1 again; deleting the newest post and adding one gives a larger id. Running `create_tables`
  twice changes nothing.

**`RealServerTest`**
- `PATCH /posts` with no cookie → 401; with another person's cookie → 403; not JSON → 400; by the
  author → 200 with `edited: true`.
- `DELETE /posts` by the author → 200; the same again → 400.
- `GET /changes` → 200 with `latest` and `[]`; `GET /changes?after=x` → 400.
- `GET /versions?post_id=…` with no cookie → 200, oldest first.

**`JourneyTest`** (`test_the_whole_journey_of_an_edit_and_a_delete`)
Aiko and Ben sign up; a third window has no cookie and only watches. Aiko posts; Ben likes it. The
watcher asks `GET /changes` and keeps `latest`. Aiko edits → the watcher's
`GET /changes?after=` brings the post with the new words; SQL: `posts.text` is new, `post_versions`
has the old text, `likes` still has Ben's row. Ben tries to edit and to delete → 403, and SQL shows
nothing changed. Aiko deletes → the watcher gets `post: null`; SQL: no `posts`, `likes` or
`post_versions` rows for it, two `changes` rows. Aiko posts again → its id is larger than the
deleted one, and the watcher's `GET /posts?after=<old last id>` brings it.

**`PageAndServerAgreeTest`**
- The page names `/changes` and `/versions`, and `PATCH` and `DELETE` on `/posts`, and the server
  answers each one (not 404).
- The JSON keys the page sends for an edit are exactly `post_id` and `text`; for a delete,
  `post_id`.
- The keys the page reads (`latest`, `changes`, `post`, `post_id`, `edited`, `replaced_at`) are
  keys the view writes.
- Both `style.css` files are still the same (existing test).

## 7. Docs to update

- `AGENTS.md`: the file table (`app.js` now edits, deletes and asks for changes); the model list
  (new functions; six tables); a short new section **"Changes feed"** with the contract from
  section 3 and the `ON DELETE` rule for tables that point at `posts`; "deleting a post deletes its
  rows, like a like".
- `DESIGN.md`: a new section: the two new tables, why `AUTOINCREMENT`, the rebuild steps, and the
  "where is each rule kept" table for "only the author" (page hides the buttons; model `own_post`;
  the database cannot check it, because it does not know who is asking).
- `README.md`: the `sqlite3` line also shows `post_versions` and `changes`; one line on how to edit
  and delete.

## 8. Not in this plan

- Editing or deleting in `page-only/`.
- Moderators or admins deleting other people's posts (`report` may hide them).
- Clearing out old rows in `changes`. It grows by one row per edit or delete; that is fine for
  this app. `AUTOINCREMENT` makes clearing safe later.
- A limit on how many changes one `GET /changes` returns, for a window that slept for days.
- "Undo delete". A deleted post is gone.
- Per-viewer changes (`block`), and renames.
- Editing anything but the text (a picture, a place).

## 9. Size

**L**, about 650 lines: `server.py` about 200 (the upgrade is about 50 of them), `app.js` about
170, `test_server.py` about 220, CSS about 30, docs about 50.

## Changes made at approval (orchestrator)

- Decisions approved as recommended, with one change to decision 1:
  **a post with replies is not removed.** Deleting it keeps its row, clears its text, and marks it
  so the page shows "This post was deleted", with its replies still under it. A post with no
  replies is removed completely, as planned. (`replies` asked for this.) If `replies` is not merged
  when this is built, the builder writes the rule so that `replies` only has to switch it on.
- **No table rebuild in this plan.** `groundwork` already gave `posts.id` `AUTOINCREMENT` and
  provides `rebuild_table`.
- Use `groundwork`'s `removePost`, `redrawPost`, the "⋯" menu (`addMenuItem`) and `ACTIONS`.
- The changes feed (`GET /changes`) is shared: `report` writes "hidden" and "shown" changes into
  it, and `block` may later read it per viewer.
