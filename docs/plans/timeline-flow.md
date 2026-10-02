Status: approved

# Timeline flow

Planned against the `accounts` branch (`.claude/worktrees/accounts/with-backend/server.py` and
`app.js`): `do_GET`, `user_or_none`, `likes_for(db_path, user_id)`, `posts_after`,
`POSTS_WITH_AUTHORS`, and `checkForNewPosts` / `showPost` / `sendPost` in the page.

## 1. What it does

When new posts arrive while you are reading further down, the list no longer jumps. A button,
**"3 new posts"**, appears at the top of the timeline instead; press it and the new posts appear
and the page goes to the top. If you are already looking at the top of the list, new posts just
appear, as today. The page also stops loading every post ever written when it opens: it loads the
newest 20, and loads 20 older ones each time you scroll near the bottom, until it says
**"No older posts."**

## 2. Decisions for the owner

1. **When do new posts appear without a press?**
   - (a) Never: the button always appears, even at the top.
   - (b) At once when the top of the list is on screen; otherwise the button.
   - **Recommend (b).** It is checked every second, so if you scroll back up yourself, the waiting
     posts appear within a second and the button goes away. Nothing moves under your eyes, because
     a post is only added above what you read when you can see the top.
2. **Your own post, while other posts are waiting?**
   - (a) It waits behind the button too. (b) Pressing **Post** shows every waiting post, yours
     included, and goes to the top.
   - **Recommend (b).** You just wrote it; you expect to see it. Showing only yours would put it
     above older waiting posts and break the newest-first order.
3. **How many posts in one page?** 10, 20 or 50.
   - **Recommend 20.** The server decides (`PAGE_SIZE` in the model). The page has the same number
     only to know when it has reached the end; a test checks the two agree. The page cannot ask for
     more, so nobody can ask for a million posts at once.
4. **How are older posts loaded?**
   - (a) A "Show older posts" button only. (b) Automatically when the bottom comes near, with an
     `IntersectionObserver` (a browser feature that tells the page when an element comes on
     screen), and the same button kept as a fallback.
   - **Recommend (b).** The observer is called only when the bottom comes into view, not hundreds
     of times a second like a scroll listener. The button stays for keyboard and screen-reader
     users, and for the rare browser where the observer does not fire.
5. **Which like counts does the page ask for each second?**
   - (a) All posts, as today. The answer grows with every liked post in the database.
   - (b) Only posts from the oldest one on screen up: `GET /likes?from=<oldest shown id>`.
   - **Recommend (b).** One number, so the address stays short however far you scroll. Leaving it
     out keeps today's answer, so nothing else breaks.
6. **After pressing "3 new posts", where does the page go?**
   - **Recommend:** to the top of the list, and keyboard focus moves to the list, so a
     screen-reader user hears where they are instead of losing their place on a hidden button.

## 3. Design

### Database

No change, and no upgrade function. `posts.id` is the table's own row number (`INTEGER PRIMARY
KEY`), so "the 20 largest ids below 300" is read straight from its index. `likes` already has
`PRIMARY KEY (post_id, user_id)`, which serves `WHERE post_id >= ?`.

**Why ids and not page numbers.** A page is asked as "posts with an id below 300", not "page 3"
(`OFFSET 40`). With page numbers, a new post arriving between two pages pushes every post down one
place, so one post is shown twice. With ids, a new post cannot change which posts are below 300.

### Model

| Name | Add/change | What it does |
|---|---|---|
| `PAGE_SIZE = 20` | add | How many posts one page has. |
| `check_id_bound(value, name)` | add | Turns `"300"` into `300`. Refuses anything that is not a whole number 0 or more, with `RuleBroken("'before' must be a whole number, 0 or more.")` (the name is filled in). |
| `posts_before(db_path, before)` | add | `before = check_id_bound(before, "before")`. Returns at most `PAGE_SIZE` posts with `posts.id < before`, **newest first**: `POSTS_WITH_AUTHORS + " WHERE posts.id < ? ORDER BY posts.id DESC LIMIT ?"`. `before` 0 means "from the very newest", the same way `after=0` means "from the very first"; then the `WHERE` is left out. |
| `likes_for(db_path, user_id, from_id=0)` | change | `from_id = check_id_bound(from_id, "from")`. Both of its queries gain `WHERE post_id >= ?` (`counts`) and `AND post_id >= ?` (`mine`). The default 0 gives today's answer, so every caller that passes two arguments is unchanged. |

`posts_after` and `POSTS_WITH_AUTHORS` are **not** changed. The check of `after` stays where it is
in the controller; moving it into the model is not part of this plan.

**Order of each answer.** `after` stays oldest first, `before` is newest first. Each is the order
the page puts them on screen: new posts go on top one by one (`prepend`), older posts go at the
bottom one by one (`append`).

### Routes

| Request | Answer |
|---|---|
| `GET /posts?before=0` | 200, the newest `PAGE_SIZE` posts, newest first. `[]` if there are none. |
| `GET /posts?before=300` | 200, up to `PAGE_SIZE` posts with an id below 300, newest first. |
| `GET /posts?before=abc` or `before=-1` | 400 `{"error": "'before' must be a whole number, 0 or more."}` |
| `GET /posts?before=300&after=12` | 400 `{"error": "Ask for 'before' or 'after', not both."}` |
| `GET /posts?after=12` | unchanged. |
| `GET /likes?from=300` | 200, `{counts, mine}` for posts with id 300 or more only. |
| `GET /likes` | unchanged (as if `from=0`). |
| `GET /likes?from=abc` | 400 `{"error": "'from' must be a whole number, 0 or more."}` |

Reading needs no login, as before. Each post in a `before` answer has the same JSON as today
(`post_to_json`), so plans that add fields to a post get them in both answers for free.

**Controller, `do_GET`:**
- The `/posts` branch: read `parse_qs(url.query)` once. If it has both `before` and `after`,
  answer 400 (which request this is, is the controller's job). If it has `before`, call
  `posts_before` inside `try / except RuleBroken` → 400, and answer `posts_to_json(rows)`.
  Otherwise the existing `after` lines run unchanged.
- The `/likes` branch: pass `query.get("from", ["0"])[0]` to `likes_for` as a third argument,
  inside `try / except RuleBroken` → 400.
- `log_message` needs no change: `/posts?before=…` and `/likes?from=…` already start with
  `/posts` and `/likes`, so they stay out of the terminal.

### View

No change. `posts_to_json` and `likes_to_json` are used as they are.

### Page: `index.html`

- Just before `<ol id="timeline">`:
  `<button type="button" id="new-posts" class="new-posts" hidden></button>`
- `<ol id="timeline">` gains `tabindex="-1"`, so the page can move focus to it (decision 6). A
  `tabindex` of -1 means "the page may focus this, but Tab skips it".
- Just after `</ol>`:
  `<p id="older-posts" class="older-posts"><button type="button" id="load-older" class="link-button">Show older posts</button></p>`

### Page: `app.js`

New constants and state, beside the others:

```js
const PAGE_SIZE = 20;            // the same as PAGE_SIZE in server.py
let oldestId = 0;                // the oldest post on screen; 0 means none yet
let firstPageLoaded = false;     // has the newest page come in?
let loadingOlder = false;        // one page at a time
let noOlderPosts = false;        // the server has no posts older than oldestId
const waitingPosts = [];         // new posts not shown yet, oldest first
```

`lastId` keeps its name, but its comment changes: it is now the newest post this window has
**received**, shown or waiting. It must count the waiting ones too, or the same posts would come
back every second.

**New functions:**

- `readerIsAtTop()`: `timeline.getBoundingClientRect().top >= 0`. True when the top of the list
  is not above the screen, so adding a post there cannot move what the person is reading.
- `receiveNewPosts(posts)`: for each post, skip it if `post.id <= lastId` (two checks that ran at
  the same moment both got it), else set `lastId` and push it onto `waitingPosts`. Then, if
  `readerIsAtTop()`, call `showWaitingPosts()`; otherwise `updateNewPostsButton()`.
- `showWaitingPosts()`: `showPost` each waiting post, oldest first, so the newest ends up on top.
  Empty the list, hide the button.
- `updateNewPostsButton()`: hidden when nothing waits; otherwise "1 new post" or "N new posts".
- `pressNewPosts()`: `showWaitingPosts()`, then `timeline.scrollIntoView()` and
  `timeline.focus()`.
- `loadOlderPosts()`: if `loadingOlder` or `noOlderPosts`, return. Ask
  `fetch("/posts?before=" + oldestId)`. `showPost(post, true)` for each, in the order they come.
  Set `oldestId` to the last one's id; the first time, also set `lastId` to the first one's id and
  `firstPageLoaded = true`. If fewer than `PAGE_SIZE` came back, set `noOlderPosts` and write
  "No older posts." in `#older-posts` (or nothing at all if the timeline is empty: there is
  nothing older than nothing). While asking, the button says "Loading…". On a network error,
  `showStatus(CANNOT_REACH)` and leave the button so the person can try again. In `finally`,
  `loadingOlder = false`, and then **watch the bottom again** (`olderObserver.unobserve(…)` then
  `.observe(…)`): an observer only speaks when something *changes*, so on a tall screen where
  `#older-posts` is still visible after a page, nothing would ever load the next page. Watching
  again makes it look once more.
- `watchTheBottom()`: makes `olderObserver = new IntersectionObserver(…, { rootMargin: "400px" })`
  on `#older-posts`, calling `loadOlderPosts()` when it is on screen or within 400 pixels of it, so
  the next page is usually there before the person reaches the end.

**Changed, kept small:**

- `showPost(post)` → `showPost(post, atBottom)`. Two places only:
  1. The guard at the top: `if (post.id <= lastId) { return; } lastId = post.id;` becomes
     `if (likeParts[post.id] !== undefined) { return; }` with the comment "Skip a post this window
     already shows." `lastId` is now kept by `receiveNewPosts` and `loadOlderPosts`, because an
     older post has a *smaller* id and would always be skipped by the old guard.
  2. The last line: `timeline.prepend(item);` becomes
     `if (atBottom) { timeline.append(item); } else { timeline.prepend(item); }`.
  Everything that builds the post in between is untouched, so other plans can change it freely.
- `checkForNewPosts()`. Three places only:
  1. First lines inside `try`: if `!firstPageLoaded`, `await loadOlderPosts()`, and return if it
     is still not loaded (the server did not answer; the next tick tries again). This replaces the
     old first request, `after=0`, which brought every post ever.
  2. `for (const post of posts) { showPost(post); }` becomes `receiveNewPosts(posts);`.
  3. `fetch("/likes")` becomes `fetch("/likes?from=" + oldestId)`. The loop over `likeParts`
     stays: every post on screen has an id of `oldestId` or more, so each still gets its count.
- `sendPost()`: one line after `await checkForNewPosts();`: `showWaitingPosts();` (decision 2).
- Event wiring at the end: `newPostsButton.addEventListener("click", pressNewPosts)`,
  `loadOlderButton.addEventListener("click", loadOlderPosts)`, and `watchTheBottom();` before
  `keepChecking();`.

**Waiting posts and hearts.** A waiting post is not in `likeParts` yet, so its heart is not
updated while it waits. When it is shown, its count is the one from when it arrived; the next
check, within a second, writes the true count.

### Page: `style.css` (and its copy `page-only/style.css`)

At the end, under `/* timeline-flow */`, using only the existing colour variables:

- `.new-posts`: `position: sticky; top: 0.5rem; z-index: 1;` centred, `var(--button)` background,
  `var(--button-text)` text, rounded. Sticky means it stays in view at the top of the screen while
  the person reads further down.
- `.older-posts`: centred, `var(--quiet)` text, some space above and below.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | MODEL: `PAGE_SIZE`, `check_id_bound`, `posts_before` | add |
| `with-backend/server.py` | MODEL: `likes_for` (new `from_id=0` argument, two `WHERE`s) | change |
| `with-backend/server.py` | CONTROLLER: `do_GET`, the `/posts` branch (`before`) and the `/likes` branch (`from`) | change |
| `with-backend/app.js` | constants and state: `PAGE_SIZE`, `oldestId`, `firstPageLoaded`, `loadingOlder`, `noOlderPosts`, `waitingPosts`, `newPostsButton`, `olderPosts`, `loadOlderButton`; `lastId` comment | add / change |
| `with-backend/app.js` | `readerIsAtTop`, `receiveNewPosts`, `showWaitingPosts`, `updateNewPostsButton`, `pressNewPosts`, `loadOlderPosts`, `watchTheBottom` | add |
| `with-backend/app.js` | `showPost`: the guard (first lines) and `prepend` (last line) only | change |
| `with-backend/app.js` | `checkForNewPosts`: first-page lines, the `for … showPost` loop, the `/likes` address | change |
| `with-backend/app.js` | `sendPost`: one added line | change |
| `with-backend/app.js` | event wiring at the end | change |
| `with-backend/index.html` | `#new-posts` before the list; `tabindex="-1"` on `#timeline`; `#older-posts` after it | add / change |
| `with-backend/style.css`, `page-only/style.css` | `/* timeline-flow */` at the end | add |
| `with-backend/test_server.py` | new methods at the end of `ModelTests`, `RealServerTest`, `PageAndServerAgreeTest`; new method `test_the_whole_journey_of_scrolling` in `JourneyTest` | add |
| `AGENTS.md`, `DESIGN.md` | new sections / rows (see 7) | add |

## 5. Depends on, and collides with

- **`accounts`** (depends): planned against its `do_GET`, `likes_for(db_path, user_id)`,
  `user_or_none`, and its `checkForNewPosts` / `sendPost`. Build after it merges.
- **`edit-delete`** (collides in `checkForNewPosts`; must agree on two things):
  - Its way of telling windows about changes must also look in `waitingPosts` (array of post
    JSON, by id): an edited waiting post is replaced there, a deleted one is removed, before it is
    ever shown. A post removed from the screen must also be removed from `likeParts`, which is now
    how `showPost` knows a post is on screen.
  - **Ids must never be reused.** Without `AUTOINCREMENT`, SQLite gives a new post the id of the
    newest post if that one was deleted. A window whose `lastId` already passed that id would then
    never see the new post (this is true of `after` today, too). If posts are really deleted, use
    `AUTOINCREMENT` or keep the row and mark it; if marked, the same filter goes in `posts_before`.
  - This plan adds no change feed and does not block one.
- **`block`, `report`, `replies`, `search`** (collide in the model): any filter on which posts the
  timeline shows must go in **both** `posts_after` and `posts_before`, and in the SQL `WHERE`, not
  in Python afterwards. A filter in Python would make a page shorter than `PAGE_SIZE`, and the page
  would wrongly say "No older posts." Whichever branch merges second adds its filter to the other
  function. `search`, if it replaces the list with results, should stop `receiveNewPosts` and the
  observer while results are shown.
- **`who-liked`** (collides): both change `likes_for` and the `/likes` branch of `do_GET`. Small;
  the second to merge keeps the other's argument.
- **`timestamps`, `links-and-tags`, `pictures`, `who-liked`, `replies`, `edit-delete`**: they edit
  the *body* of `showPost`. This plan touches only its first lines and last line.
- **`drafts`, `pictures`, `rate-limit`**: they edit `sendPost`. This plan adds one line after
  `await checkForNewPosts();`.
- **`japanese`**: new words to translate: "1 new post" / "N new posts" (two forms, picked in
  `updateNewPostsButton`), "Show older posts", "Loading…", "No older posts.".
- **`dark-mode`**: the new CSS uses only the existing colour variables, so it follows the theme.

## 6. Tests

**`ModelTests`** (new methods at the end):
- `test_before_0_gives_the_newest_page_newest_first`: save 25 posts; `posts_before(db, 0)` gives
  ids 25 down to 6, which is `PAGE_SIZE` posts.
- `test_before_gives_the_next_older_page`: `posts_before(db, 6)` gives 5 down to 1, fewer than
  `PAGE_SIZE`; `posts_before(db, 1)` gives `[]`.
- `test_a_new_post_does_not_move_a_page`: take the first page, save a post, ask `before` the
  oldest id: no post is in both pages.
- `test_before_must_be_a_whole_number_0_or_more`: `"abc"`, `"-1"`, `None`, `"1.5"` raise
  `RuleBroken`.
- `test_likes_from_leaves_out_older_posts`: like posts 2 and 9; `likes_for(db, user, 5)` has
  only 9 in `counts` and in `mine`; `likes_for(db, user)` still has both.

**`RealServerTest`**:
- `test_get_posts_before_0`: 200, a list, newest first, at most `PAGE_SIZE`.
- `test_before_that_is_not_a_number_gets_400_and_a_reason`.
- `test_before_and_after_together_get_400`.
- `test_likes_from_that_is_not_a_number_gets_400`.

**`JourneyTest`**, `test_the_whole_journey_of_scrolling` (with the accounts journey's sign-up
helpers): one person signs up and posts 45 times. The page's requests, in order:
`before=0` (20 posts, 45..26), `before=26` (20), `before=6` (5, so the page knows it is the end).
After each, read the database with SQL: together the three pages are exactly
`select id from posts`, with no id twice. Then a second person posts; `after=45` brings exactly
one post, whose id is `select max(id) from posts`. The first person likes post 3;
`GET /likes?from=26` has no count for post 3, `GET /likes?from=1` has the count that
`select count(*) from likes where post_id = 3` gives.

**`PageAndServerAgreeTest`** (new methods; the existing lists are not edited):
- `test_the_page_has_the_same_page_size`: `const PAGE_SIZE = (\d+);` in `app.js` equals
  `server.PAGE_SIZE`.
- `test_the_server_answers_the_paging_requests`: `GET /posts?before=0` and `GET /likes?from=0`
  are not 404 or 501.
- `test_the_page_asks_with_before_and_from`: `app.js` contains `"/posts?before="` and
  `"/likes?from="`.
- `test_the_page_has_the_flow_elements`: `index.html` has `id="new-posts"`, `id="older-posts"`
  and `id="load-older"`, the ids `app.js` looks up.

**Checked by hand** (the tests never run the page's JavaScript): open two windows with 45 posts.
In window A, scroll down; in B, post twice. A's list does not move, and the button says "2 new
posts". Press it: both appear, and the page is at the top. Scroll to the bottom of A: older posts
load, and at the end it says "No older posts.". Scroll back to the top while a post waits: it
appears within a second. Tab to "Show older posts" and press Enter: it works without a mouse.

## 7. Docs to update

- `AGENTS.md`: add `posts_before` and `check_id_bound` to the model's list; in the file table,
  `app.js` "asks for the newest page, older pages on scroll, and holds new posts behind a button".
- `DESIGN.md`: a new section "Timeline flow": `before` and `after`, why ids and not page numbers,
  the order of each answer, `/likes?from=`, and the hand checks above.
- `README.md`: one line under "Things to try" ("scroll down in one window, post in another").

## 8. Not in this plan

- Capping `after`: a window left open while 1,000 posts arrive still gets all 1,000 at once.
- Removing old posts from the screen after long scrolling (keeping the page light).
- Remembering where you were after a reload, or a link to one post.
- Showing the count in the tab title, such as "(3) Timeline".
- A screen-reader announcement when new posts wait (the button is enough for now).
- Any change to `page-only/` except the shared CSS.
- How other windows learn about edits and deletes (`edit-delete`).

## 9. Size

**M**, about 300 lines: `server.py` ~35, `app.js` ~95, `index.html` ~6, CSS ~25 in each of two
files, tests ~120, docs ~20.

## Changes made at approval (orchestrator)

- All six decisions approved as recommended.
- `posts_before` reads through `groundwork`'s `select_posts`, so every filter is in the SQL.
- Older posts are put at the bottom with `placePost(item, post, "bottom")`.
- Build after `edit-delete` if possible, because both change `checkForNewPosts`.
