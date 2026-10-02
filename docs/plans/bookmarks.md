Status: merged

# Bookmarks

## 1. What it does

A signed-in person can press a bookmark button (☆) on any post to save it, and press it again
(★) to take the bookmark back. A "My bookmarks" button shows only the posts they saved. A bookmark
is **private**: nobody else can ever see who bookmarked what, and no post shows a bookmark count.

## 2. Decisions for the owner

1. **Is `GET /bookmarks` asked for every second, like `/likes`?**
   - (a) Yes, in `checkForNewPosts`. Two windows of the same person always agree.
   - (b) **No.** Ask once when the person signs in, once each time they open "My bookmarks", and
     again after a refused press.
   - **Recommendation: (b).** Likes are polled because *other people* change them. Bookmarks change
     only when *you* press a button, and the answer to that press already tells this window the new
     state. Polling would double the requests every window makes for almost nothing. The cost is
     small: if you bookmark in one tab, a second tab of yours is out of date until you open "My
     bookmarks" there. If you press a stale star there, the server refuses it (400) and the page asks
     again, the same way the heart recovers today. It also keeps `checkForNewPosts` untouched, which
     `timeline-flow` is changing.

2. **In what order is the bookmarks list?**
   - (a) **Newest post first**, the same order as the timeline. No new column.
   - (b) Most recently bookmarked first. Needs a `saved_at` column in `bookmarks`.
   - **Recommendation: (a).** It keeps `bookmarks` shaped exactly like `likes` (two ids, nothing
     else), and does not depend on how `timestamps` decides to store time. (b) can be added later.

3. **What happens to a bookmark when its post is deleted (`edit-delete`)?**
   - (a) **The bookmark goes away quietly.** The post leaves "My bookmarks" the moment it is
     deleted.
   - (b) The list keeps a line saying "This post was deleted."
   - **Recommendation: (a).** A deleted post should be gone for everyone, and its author chose to
     delete it. In the database the row is removed by `ON DELETE CASCADE` if `edit-delete` really
     deletes the post row, and the list leaves it out if `edit-delete` only marks it (see section 5).

4. **Bookmarking the same post twice: an error, or nothing happens?**
   - (a) **400 "You have already bookmarked that post."**, the same as a second like.
   - (b) Answer 201 and do nothing (an "idempotent" request: sending it twice is the same as once).
   - **Recommendation: (a).** Same as likes, so there is one pattern to learn. The 400 is also what
     tells a stale window to ask again.

5. **What does a signed-out person see?**
   - (a) The ☆ is shown on every post, like the heart. Pressing it says "Please log in to bookmark
     a post." The "My bookmarks" button is hidden.
   - (b) No ☆ at all until signed in.
   - **Recommendation: (a).** It matches the heart, and shows people the feature exists.

## 3. Design

### What is the same as likes, and what is deliberately different

| | Likes | Bookmarks |
|---|---|---|
| One row per person per post, the database refuses a second | yes | yes |
| `POST` adds, `DELETE` removes, a removed row is deleted (never marked) | yes | yes |
| Who is asking comes from the session cookie, never from the JSON | yes | yes |
| A public count | yes, `like_count` on every post | **no count anywhere** |
| Who can read it | anyone (`GET /likes` works signed out) | **only you**; `GET /bookmarks` is 401 when signed out |
| Asked for every second | yes | **no** (decision 1) |
| Primary key order | `(post_id, user_id)`: likes are counted per post | **`(user_id, post_id)`**: bookmarks are always read per person, so this order makes that lookup fast with no extra index |
| Answer to a press | `{post_id, like_count}` | `{post_id, bookmarked}`: no count, so nothing about anyone else |

### Database: `upgrade_to_bookmarks(connection)`

Written like `upgrade_to_accounts`: `BEGIN`, the change, `PRAGMA user_version = <n>`, `COMMIT`. The
orchestrator chooses `<n>` and adds the `if version < <n>: upgrade_to_bookmarks(connection)` line
to `create_tables`. Every old row is kept; the upgrade only adds a table.

```sql
CREATE TABLE bookmarks (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, post_id)
)
```

- `PRIMARY KEY (user_id, post_id)`: the database itself refuses a second bookmark of the same post
  by the same person, even if every check in the code is got around.
- `ON DELETE CASCADE`: if a post row (or a user row) is ever deleted, the database deletes its
  bookmarks too. "Cascade" means the delete flows on to the rows that point at it. It works because
  `connect` already turns on `PRAGMA foreign_keys`.
- No count column, no time column, no name: a name lives only in `users`.

### Model (all new functions)

- `check_bookmark_post_id(post_id)`: returns the post id as a number, or raises
  `RuleBroken("The bookmark must say which post it is for.")`. It is a new function, not a change to
  `check_post_id`, whose message talks about a like.
- `add_bookmark(db_path, user_id, post_id)` → `post_id`. Checks the id, checks the post exists
  ("That post does not exist."), checks there is no bookmark yet ("You have already bookmarked that
  post."), then `INSERT`. An `sqlite3.IntegrityError` (two presses at the same moment) gives the same
  message, exactly as in `add_like`.
- `remove_bookmark(db_path, user_id, post_id)` → `post_id`. One `DELETE … WHERE user_id = ? AND
  post_id = ?`; `rowcount == 0` raises `RuleBroken("You have not bookmarked that post.")`. It can
  only ever delete the asking person's own row, because `user_id` is in the `WHERE`.
- `bookmarks_for(db_path, user_id)` → the bookmarked posts, newest first:
  `POSTS_WITH_AUTHORS + " JOIN bookmarks ON bookmarks.post_id = posts.id WHERE bookmarks.user_id = ?
  ORDER BY posts.id DESC"`. It reuses `POSTS_WITH_AUTHORS` without changing it, so any filter
  another plan adds there (a deleted, blocked or hidden post) applies to the list too.

None of them takes a name, and none of them adds a user.

### Routes

| Request | JSON in | Answer |
|---|---|---|
| `GET /bookmarks` | — | 200, a list of posts (the same shape as `GET /posts`), newest first. 401 if not signed in. |
| `POST /bookmarks` | `post_id` | 201 `{post_id, bookmarked: true}`; 400 with a reason; 401 |
| `DELETE /bookmarks` | `post_id` | 200 `{post_id, bookmarked: false}`; 400 with a reason; 401 |

`GET /bookmarks` reads **no** query string. `?user=aiko` or `?author=aiko` is ignored: the only way
to say who you are is the cookie. The `POST` and `DELETE` bodies are read only for `post_id`; a
`user_id` or `author` key is ignored.

**Controller** (`TimelineHandler`):
- `do_GET`: a new `elif url.path == "/bookmarks":` branch: `signed_in_user()`, then
  `bookmarks_for`, then `send_json(200, posts_to_json(rows))`.
- `do_POST`: add `"/bookmarks"` to the list of paths, and one `elif path == "/bookmarks":
  self.take_bookmark(data)`.
- `do_DELETE`: one new `if path == "/bookmarks": self.drop_bookmark(); return` before the likes
  code, and add "or a bookmark at /bookmarks" to the 404 message.
- New methods `take_bookmark(data)` and `drop_bookmark()`, written like `take_like` and the likes
  part of `do_DELETE`. They check no rule and touch no database; they call the model.
- `log_message` is not changed: `GET /bookmarks` is not polled, so it is not noisy. The printed line
  shows only the path, never who asked. No terminal line is printed for a bookmark (unlike a post):
  the terminal must not show what someone saved.

### View

- New `bookmark_to_json(post_id, bookmarked)` → `{"post_id": …, "bookmarked": …}`.
- The list reuses `posts_to_json`, unchanged, so a bookmarked post looks the same as on the
  timeline, and a field another plan adds to `post_to_json` shows up in the list by itself.
- `post_to_json`, `POSTS_WITH_AUTHORS` and `likes_to_json` are **not** changed. That is the privacy
  rule in code: the public answers have nowhere to carry a bookmark.

### Page

**`index.html`**
- Inside `#signed-in` (so it hides by itself when signed out), after the post form: a small
  `<nav id="views" class="views" aria-label="Which posts">` with two buttons, `#show-timeline`
  ("Timeline", `aria-pressed="true"`) and `#show-bookmarks` ("My bookmarks").
- After `#timeline`: `<ol id="bookmark-list" class="timeline" aria-label="Your bookmarks, newest
  post first" hidden></ol>` and `<p id="bookmarks-empty" class="status" hidden>You have no
  bookmarks yet. Press ☆ on a post to save it.</p>`.

**`app.js`**
- State: `const bookmarked = new Set()` (the post ids this person bookmarked) and
  `const bookmarkButtons = {}` (each ☆ on the timeline, by post id, like `likeParts`).
- `makePostItem(post)` (*new, moved out of `showPost`*): builds the `<li>` with display name,
  `@handle`, time and text, and returns it. `showPost` calls it, then adds the like row as now. This
  is a pure move with no change in behaviour. It lets the bookmark list show a post exactly as the
  timeline does, and gives every later plan that changes how a post looks (`timestamps`,
  `links-and-tags`, `pictures`, `replies`, `place`) one place to change.
- `makeBookmarkButton(postId)` (*new*): a `<button class="bookmark" data-post-id=…>` with
  `aria-pressed` and an `aria-label` ("Bookmark this post" / "Remove bookmark"). `showPost` appends it
  to the like row and saves it in `bookmarkButtons`.
- `showBookmark(postId, on)` (*new*): updates the set and the button (☆ or ★, `aria-pressed`,
  label), like `showLike`.
- `loadBookmarks()` (*new*): `GET /bookmarks`. On 200: fill the set, update every ☆ on the
  timeline, and draw the list. On 401: `clearBookmarks()`.
- `clearBookmarks()` (*new*): empties the set and the list, turns every ★ back to ☆, and shows the
  timeline view. Nothing private stays on screen after logging out on a shared computer.
- `showBookmarkList(posts)` (*new*): empties `#bookmark-list` and adds one `makePostItem(post)` per
  post, each with its own ★ "Remove bookmark" button. Shows `#bookmarks-empty` when there are none.
- `pressBookmark(postId)` (*new*): written like `pressHeart`: signed-out message, one press at a
  time (`busy`), `POST` or `DELETE /bookmarks` with `{post_id}` only. On 401: `showSignedOut`. On
  400: show the reason and `loadBookmarks()`. On success: `showBookmark(postId, answer.bookmarked)`,
  and if the list is open, remove or redraw that post.
- `showView(which)` (*new*): shows `#timeline` or `#bookmark-list`, sets `aria-pressed` on the two
  buttons, and calls `loadBookmarks()` when opening the list.
- Small changes to shared functions: `showPost` (use `makePostItem`, append the ☆),
  `clickOnTimeline` (also route `.bookmark` clicks to `pressBookmark`), `showSignedIn` (one line:
  `loadBookmarks()`), `showSignedOut` (one line: `clearBookmarks()`). New listeners for the two view
  buttons and a click listener on `#bookmark-list`.
- `checkForNewPosts` and `keepChecking` are **not** changed (decision 1).
- The page never sends a name or a user id with a bookmark.

**`style.css`** (and its copy `page-only/style.css`): new rules at the end under
`/* bookmarks */`: `.bookmark`, `.bookmark.bookmarked`, `.views`, `.views button[aria-pressed="true"]`.
Colours come from the existing variables, so `dark-mode` works without change.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | module docstring and MODEL comment ("four tables" → five) | change |
| `with-backend/server.py` | `create_tables`: one `if version < n: upgrade_to_bookmarks(connection)` line | change |
| `with-backend/server.py` | `upgrade_to_bookmarks` | add |
| `with-backend/server.py` | `check_bookmark_post_id`, `add_bookmark`, `remove_bookmark`, `bookmarks_for` | add |
| `with-backend/server.py` | `TimelineHandler.do_GET`: `/bookmarks` branch | change |
| `with-backend/server.py` | `TimelineHandler.do_POST`: path list and one branch | change |
| `with-backend/server.py` | `TimelineHandler.do_DELETE`: `/bookmarks` branch and 404 message | change |
| `with-backend/server.py` | `TimelineHandler.take_bookmark`, `TimelineHandler.drop_bookmark` | add |
| `with-backend/server.py` | `bookmark_to_json` | add |
| `with-backend/app.js` | `makePostItem` (moved out of `showPost`) | add |
| `with-backend/app.js` | `showPost`: call `makePostItem`, append the ☆ | change |
| `with-backend/app.js` | `makeBookmarkButton`, `showBookmark`, `loadBookmarks`, `clearBookmarks`, `showBookmarkList`, `pressBookmark`, `showView`, state `bookmarked`, `bookmarkButtons` | add |
| `with-backend/app.js` | `clickOnTimeline`, `showSignedIn`, `showSignedOut`, the listeners at the end | change |
| `with-backend/index.html` | `#views` nav in `#signed-in`; `#bookmark-list` and `#bookmarks-empty` after `#timeline` | add |
| `with-backend/style.css`, `page-only/style.css` | `/* bookmarks */` section at the end | add |
| `with-backend/test_server.py` | new tests at the end of `ModelTests`, `RealServerTest`, `PageAndServerAgreeTest`; new `BookmarkJourneyTest` class after `JourneyTest` | add |
| `with-backend/test_server.py` | `PageAndServerAgreeTest`: the set of routes the page fetches gains `/bookmarks` | change |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (section 7) | add |

## 5. Depends on, and collides with

- **`accounts`** (depends on): needs `user_for_session`, `signed_in_user`, `showSignedIn`,
  `showSignedOut` and the session cookie. Build after `accounts` merges.
- **`edit-delete`** (collides, and decides decision 3 together): both change `do_DELETE` routing
  and `showPost`. If `edit-delete` deletes the post row, `ON DELETE CASCADE` removes its bookmarks
  (`likes` has no cascade, so `edit-delete` must handle likes itself). If it only marks a post as
  deleted, it should add that filter to `POSTS_WITH_AUTHORS` (or to `posts_after`); `bookmarks_for`
  then needs the same filter. Whichever merges second adds one test: "a deleted post leaves
  'My bookmarks', and its row is gone or hidden".
- **`showPost` group**: `timestamps`, `links-and-tags`, `pictures`, `replies`, `place`,
  `who-liked`, `timeline-flow`, `edit-delete` all change `showPost`. This plan moves its first half
  into `makePostItem`. Merge `bookmarks` early, or let whichever of these merges first do the same
  move, so the rest rebase onto one shape.
- **`timeline-flow`** (small): it changes `checkForNewPosts`; this plan does not touch it. Because
  the list comes from the server, not from the posts already on screen, it still works when older
  posts are loaded only on scroll. A post loaded later gets the right ☆ from the `bookmarked` set.
- **`block`, `report`**: should a blocked person's post, or a hidden one, stay in your bookmarks?
  If those plans filter in `POSTS_WITH_AUTHORS`, the list follows automatically. If they filter only
  in `posts_after`, they should also filter `bookmarks_for`.
- **`search`**: also a "show only some posts" view. It should use the same `#views` nav, or the two
  plans should agree which one adds it first.
- **`who-liked`**: both add a `do_GET` branch next to `/likes`. Two separate lines; easy rebase.
- **`japanese`**: new words to translate: "Bookmark this post", "Remove bookmark", "Timeline",
  "My bookmarks", the empty-list line, and the four error messages.
- **Every plan with an upgrade** (`timestamps`, `edit-delete`, `replies`, `pictures`, `block`,
  `report`, …): the `user_version` number and the `create_tables` line are given by the
  orchestrator in merge order.
- **`rate-limit`**: bookmarks are private and cannot spam anyone, so no limit is needed here.

## 6. Tests

**`ModelTests`** (a database made only for the test; two signed-up users, Aiko and Ben)
- A bookmark is one row with the two ids, and nothing else.
- Bookmarking the same post twice is refused, and there is still one row.
- A raw `INSERT` of a second identical row raises `sqlite3.IntegrityError` (the database itself
  refuses it).
- A bookmark for a post that does not exist is refused; a bookmark without a post id is refused,
  with the bookmark message, not the like message.
- Taking a bookmark back deletes the row; taking it back twice is refused; taking back one you never
  made is refused.
- **Privacy:** Aiko and Ben bookmark different posts; `bookmarks_for(aiko)` holds only Aiko's, and
  `bookmarks_for(ben)` only Ben's. Ben's `remove_bookmark` on a post only Aiko bookmarked is refused
  and Aiko's row is still there.
- **Privacy:** `posts_after(0)` and `likes_for(None)` give exactly the same rows before and after a
  bookmark. No post row has a bookmark column.
- `bookmarks_for` gives the posts newest first, with both names and the like count.
- Deleting a post row (with likes removed first) removes its bookmark (the cascade works).
- Bookmarking does not add a user, and does not change a like.
- `upgrade_to_bookmarks` on a database at the version before it keeps every user, post, like and
  session, and adds an empty `bookmarks` table.

**`RealServerTest`**
- `GET /bookmarks` with no cookie gets 401. `POST` and `DELETE /bookmarks` with no cookie get 401,
  and no row is made.
- Signed in: `POST /bookmarks` gets 201 `{post_id, bookmarked: true}`; `GET /bookmarks` lists it;
  `DELETE` gets 200 `{post_id, bookmarked: false}`.
- A second bookmark of the same post gets 400 and a reason.
- `POST /bookmarks` that is not JSON is refused (the cross-site rule from `accounts`).

**`BookmarkJourneyTest`** (new class after `JourneyTest`, same helpers: real server, real HTTP,
each person with their own cookie, the database file read with SQL after each step)
1. Aiko and Ben sign up. Aiko posts twice; Ben posts once.
2. Save the exact bytes of `GET /posts?after=0` and `GET /likes` as seen by Ben and by a window with
   no cookie.
3. Aiko bookmarks Ben's post. `select * from bookmarks` is one row: Aiko's id, that post's id.
4. **Privacy:** `GET /posts?after=0` and `GET /likes` for Ben and for the no-cookie window are
   byte-for-byte the same as in step 2. Ben's `GET /bookmarks` is `[]`. The no-cookie
   `GET /bookmarks` is 401. Ben's `GET /bookmarks?user=aiko` is still `[]`.
5. Ben sends `POST /bookmarks` with `{"post_id": …, "user_id": <Aiko's id>, "author": "aiko"}`: the
   new row is Ben's, not Aiko's.
6. Ben sends `DELETE /bookmarks` for the post Aiko bookmarked (Ben never did): 400, and Aiko's row
   is still in the table.
7. Aiko's `GET /bookmarks` lists exactly her one post. She takes it back: 200, and the row is gone
   (deleted, not marked).
8. Aiko logs out: `GET /bookmarks` with her old cookie is 401.

**`PageAndServerAgreeTest`**
- The routes the page fetches now include `/bookmarks` (change to the existing set).
- The server answers `GET`, `POST` and `DELETE /bookmarks` (not 404 or 501).
- The page sends `post_id` with a bookmark and no `author`, `user` or `user_id` key.
- The body of `checkForNewPosts` (cut out of `app.js` by a regular expression) does not name
  `/bookmarks`: bookmarks are not polled (decision 1).
- Both `style.css` files are still the same.

## 7. Docs to update

- `AGENTS.md`: the file table (`app.js` also sends bookmarks; `timeline.db` has one more table); a
  new paragraph under the model: `bookmarks` (one row per person per post, `PRIMARY KEY (user_id,
  post_id)`, private: never counted, never shown to anyone else, never polled), and the new model
  and view function names; the `sqlite3` line gains `select * from bookmarks`.
- `DESIGN.md`: a new "Bookmarks" section: the table from section 3 (same as likes, and where
  different, and why), the privacy rule, and why it is not polled. Add `bookmarks` to the data model
  section.
- `README.md`: one line in the features or "things to try" list: "Press ☆ on a post, then open
  My bookmarks. Log in as someone else: they cannot see it."

## 8. Not in this plan

- Folders, tags or notes on a bookmark.
- Sharing a bookmark list, or a public "saved by" count.
- Bookmarks in `page-only/` (it has no accounts).
- Ordering by when a post was bookmarked (decision 2, option b).
- Live sync of bookmarks between two windows of the same person (decision 1, option a).
- A `Cache-Control: no-store` header on private answers. `send_answer` has no way to add a header
  yet; worth a small plan of its own for `/sessions` and `/bookmarks` together.

## 9. Size

**M**, about 500 lines: `server.py` ~90, `app.js` ~130, `index.html` ~12, `style.css` ~30 (twice),
`test_server.py` ~180, docs ~30.

## Changes made at approval (orchestrator)

- All five decisions approved as recommended.
- `makePostItem`, `addView` and the one click handler (`ACTIONS`) come from `groundwork`; this plan
  does not move `showPost` itself. The ☆ button is added to the `foot` slot with `addPostPart`.
- The bookmarks list is read through `select_posts`, so `block` and `report` apply to it.
