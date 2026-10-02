Status: merged

# Groundwork

Written by the orchestrator, from what the other 18 plans asked for. Approved by the owner.

## 1. What it does

Nothing a person can see. It builds the shared pieces that many features would otherwise each
build for themselves, in different ways, in the same few lines. After it lands, a feature adds a
few lines in its own place instead of cutting `showPost` or `posts_after` apart again. Every test
that passes before passes after, and the page looks and works exactly the same.

It is built right after `accounts`, and before `japanese` Part A and every feature.

## 2. Decisions

All made: the owner approved this plan as the orchestrator proposed it. Small choices are made in
section 3 and explained there.

## 3. Design

### 3.1 The page builds a post from slots (`app.js`)

Today `showPost` builds every part of a post and puts it at the top, in one function. Ten plans
change it. Instead:

- **`makePostItem(post)`** builds one `<li class="post">` with four empty **slots** (named places
  inside the post), in this order, and returns `{ item, slots }`:
  - `head`: display name, `@name`, time (then `place` adds its part here)
  - `body`: the text (`links-and-tags`, `long-posts`, `pictures` work here)
  - `foot`: the heart and its count (`who-liked`, `bookmarks`, `replies` add here)
  - `menu`: the "⋯" menu (3.2)

  Then it calls every function in **`POST_PARTS`**, in order: `part(post, slots, item)`.
  Groundwork registers the parts that exist today (names, time, text, heart) with
  `addPostPart(fn)`. A feature adds its part with one `addPostPart(...)` call in its own block of
  code, and never edits `makePostItem`.
- **`placePost(item, post, where)`** puts a built post on the page: `"top"` (today's
  behaviour), or `"bottom"` (for `timeline-flow`). `replies` will add `"under-parent"`.
- **`showPost(post)`** keeps its name and its job (skip a post already shown, build it, put it at
  the top), now in three lines that call the two functions above.
- **`postParts`** replaces `likeParts`: `postParts[id] = { item, slots, ...what each part keeps }`.
  The heart part keeps `{ likeButton, likeCount }` there, and `showLike` reads it from there.
- **`removePost(id)`** takes a post off the page and out of `postParts`. **`redrawPost(post)`**
  builds it again with `makePostItem` and swaps it in place. `edit-delete`, `block` and `report`
  use these two instead of each writing their own.

Search results and the bookmarks list build their posts with `makePostItem` too, but in their own
list, and they are not put in `postParts` (only the live timeline is kept up to date).

### 3.2 One "⋯" menu per post, and one click handler for every button

- The `menu` slot is a `<details class="post-menu">` with `<summary aria-label="More actions for
  this post">⋯</summary>` and an empty list. A post whose menu is empty shows no "⋯" at all.
  `block`, `report`, `edit-delete` and `replies` add items with `addMenuItem(slots, action, words)`.
- **Every button in a post says what it does with `data-action`**, for example
  `data-action="like"`, and carries `data-post-id`. The one click handler on the timeline,
  `clickOnTimeline`, now looks up `ACTIONS[button.dataset.action]` and calls it with the post id
  and the button. The heart becomes `ACTIONS.like = pressHeart`. A feature adds
  `ACTIONS.block = pressBlock` in its own block, and never edits `clickOnTimeline`.
- The same handler is used on the search and bookmarks lists, so their buttons work the same way.

### 3.3 One switch between views (`index.html`, `app.js`)

- `<nav id="views" hidden>` under the title, and the timeline wrapped in
  `<section data-view="timeline">`. **`showView(name)`** shows that section and hides the others,
  and marks its button `aria-current="page"`. **`addView(name, words)`** adds a button and its
  section. The nav stays hidden while there is only one view, so nothing changes on screen now.
- `search` adds "Search results", and `bookmarks` adds "My bookmarks".

### 3.4 One visibility filter for every list of posts (`server.py`, model)

- **`visible_to(viewer_id)`** returns `(sql, params)`: the part of a `WHERE` that decides which
  posts this viewer may see. In groundwork it allows every post: `("1 = 1", [])`. `block` and
  `report` each add one condition inside it, joined with `AND`.
- **`select_posts(connection, conditions, params, viewer_id, order, limit=None)`** is the only
  place that reads a list of posts. It joins the feature's conditions with `visible_to`, always.
  `posts_after(db_path, after, viewer_id=None)` now calls it, and `timeline-flow`, `search`,
  `bookmarks` and `replies` call it too. Every filter is in the SQL, never in Python, so a page of
  20 posts really has 20 posts (`timeline-flow` asked for this).
- **`post_by_id(connection, post_id)`** reads one post with no filter, for the person who just
  wrote it (as `save_post` does today).
- Controller: the `/posts` branch passes the viewer, from `user_or_none`.
- A test makes sure `POSTS_WITH_AUTHORS` is used only inside `select_posts` and `post_by_id`, so a
  new query cannot get round the filter.

### 3.5 One place that adds a post (`server.py`, model)

- **`insert_post(connection, user_id, text, **more)`** does the `INSERT INTO posts` and returns the
  new id. `more` is extra columns from other plans (`posted_at` from `timestamps`, `place`,
  `parent_id`), checked against a fixed list of allowed column names, so no column name ever comes
  from a request. `save_post` calls it. `timestamps`, `place`, `replies` and `pictures` each add
  their column here, in one line.

### 3.6 Rebuilding a table safely, and post ids that are never reused (`server.py`, model)

- **`rebuild_table(connection, table, change_sql)`** (the method found by the `edit-delete`
  planner): read the table's own `CREATE` text from `sqlite_master`, apply a change to it, make the
  new table, copy every row with `SELECT *`, drop the old one, rename, and make its indexes and
  triggers again. It runs with `PRAGMA foreign_keys = OFF` (set before `BEGIN`, because SQLite
  ignores it inside a transaction), checks `PRAGMA foreign_key_check` before committing, and turns
  foreign keys back on. Because it starts from the table's own text, columns, indexes and triggers
  added by other plans are kept.
- **`upgrade_to_groundwork`** uses it once: `posts.id` becomes `INTEGER PRIMARY KEY AUTOINCREMENT`.
  Without it, SQLite gives a deleted newest post's id to the next post, and a window that already
  passed that id would never see it. This upgrade is `user_version` 2. `timestamps` uses
  `rebuild_table` for its own change; `edit-delete` no longer needs to rebuild anything.

### 3.7 Small shared fixes in the controller

- **A size limit on every request.** `read_json` refuses a body over `MAX_REQUEST_BYTES`
  (4 MB, enough for a 2 MB picture as base64) with `413`, before reading it.
- **One "nothing here" answer.** The `404` sentences that name particular routes ("You can only
  take back a like at /likes, or log out at /sessions") become one sentence: "There is nothing to
  {method} at {path}." It stays true when new routes arrive.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/app.js` | `POST_PARTS`, `addPostPart`, `makePostItem`, `placePost`, `postParts`, `removePost`, `redrawPost` | add |
| `with-backend/app.js` | the four parts that exist today: names, time, text, heart | add (moved out of `showPost`) |
| `with-backend/app.js` | `ACTIONS`, `addMenuItem` | add |
| `with-backend/app.js` | `showView`, `addView` | add |
| `with-backend/app.js` | `showPost` (three lines), `showLike` (reads `postParts`), `clickOnTimeline` (uses `ACTIONS`), `checkForNewPosts` (loops over `postParts`) | change |
| `with-backend/app.js` | `likeParts` | remove (replaced by `postParts`) |
| `with-backend/index.html` | `<nav id="views" hidden>`; `<section data-view="timeline">` around the timeline | change |
| `with-backend/style.css` + `page-only/style.css` | `/* groundwork */` at the end: slots, `.post-menu`, `#views` | add |
| `with-backend/server.py` | model: `visible_to`, `select_posts`, `post_by_id`, `insert_post`, `rebuild_table`, `upgrade_to_groundwork`, `MAX_REQUEST_BYTES` | add |
| `with-backend/server.py` | model: `posts_after` (`viewer_id=None`, calls `select_posts`), `save_post` (calls `insert_post`, `post_by_id`), `create_tables` (one line) | change |
| `with-backend/server.py` | controller: `do_GET` `/posts` branch (passes the viewer), `read_json` (413), the 404 sentences in `do_POST`/`do_DELETE` | change |
| `with-backend/test_server.py` | new methods at the end of all four classes | add |
| `AGENTS.md` | the page's slots and actions; "every list of posts goes through `select_posts`"; `rebuild_table`; the 413 | add |
| `DESIGN.md` | a short "Groundwork" section | add |

## 5. Depends on, and collides with

- **Depends on `accounts`.**
- **Collides with everything once, on purpose, before anything else is built.** After it merges,
  every feature branch starts from it.
- **`japanese` Part A** is built right after it, and turns the few new English words here
  ("More actions for this post") into keys.
- Plans that change because of it (each builder reads this file first): `timestamps` (uses
  `rebuild_table`, `insert_post`, the `head` slot), `edit-delete` (no rebuild of its own; uses
  `removePost`, `redrawPost`, the menu), `block` and `report` (add to `visible_to`, add menu items),
  `search` and `bookmarks` (`makePostItem`, `addView`, `select_posts`), `timeline-flow`
  (`placePost(…, "bottom")`, `select_posts`), `replies` (`insert_post`, `placePost` under a parent,
  `select_posts`), `pictures` (`insert_post`, the 413), `place` (`insert_post`, the `head` slot),
  `who-liked` (the `foot` slot), `links-and-tags` and `long-posts` (the `body` slot).

## 6. Tests

All 65 tests from `accounts` still pass, unchanged except where they named `likeParts`.

- **`ModelTests`**
  - `posts_after` with no viewer gives exactly what it gave before.
  - `visible_to(None)` and `visible_to(user_id)` allow every post.
  - `insert_post` refuses a column name that is not on its list.
  - **Ids are never reused:** add three posts, delete the newest with SQL, add one more: its id
    is 4.
  - `upgrade_to_groundwork` on an accounts database keeps every user, post, like and session,
    sets `user_version` to 2, and leaves `PRAGMA foreign_key_check` empty.
  - `rebuild_table` keeps an extra column, an index and a trigger added for the test.
  - Running `create_tables` twice is harmless.
- **`RealServerTest`**
  - A body over `MAX_REQUEST_BYTES` gets `413` and is not read.
  - An unknown route gets the one "nothing to … at …" sentence.
- **`JourneyTest`** — the existing journeys pass unchanged. That is the proof that nothing a person
  sees has changed.
- **`PageAndServerAgreeTest`**
  - Every `data-action` value in `app.js` has an `ACTIONS` entry.
  - `showPost` calls `makePostItem`.
  - `POSTS_WITH_AUTHORS` appears only inside `select_posts` and `post_by_id` in `server.py`.
  - `MAX_REQUEST_BYTES` is not smaller than what `pictures` needs (a check that `pictures` will
    tighten).
  - Both `style.css` files are the same.

Plus a check in the browser: sign up, post, like, unlike, log out. Everything looks and works as it
did before.

## 7. Docs to update

`AGENTS.md` (section 4), `DESIGN.md` (a short section), and `docs/plans/README.md` (the plans table:
groundwork, built after accounts).

## 8. Not in this plan

Any visible feature. The words table and rule codes (`japanese` Part A). The changes feed
(`edit-delete`). The `ON DELETE` rule for tables that point at `posts` (`edit-delete` decides).

## 9. Size

**M.** About 400 lines: `app.js` about 150 (much of it moved, not new), `server.py` about 120,
tests about 120, CSS and HTML about 20, docs about 30.
