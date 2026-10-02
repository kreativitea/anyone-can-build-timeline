Status: built on branch block, awaiting merge

# Block

## 1. What it does

A signed-in person can block another account. From then on, the server leaves that account's posts
out of everything it sends to them, so those posts never reach their screen, not even hidden. The
blocked account cannot like the blocker's posts (or reply to them, once `replies` exists). A
"Blocked accounts" list under "Signed in as" shows everyone you have blocked, with an **Unblock**
button for each.

## 2. Decisions for the owner

1. **Does a blocked person still see *your* posts?**
   - (a) Yes. Blocking hides *their* posts from *you*, and stops them liking or replying to yours.
   - (b) No. The server also hides your posts from them while they are signed in.

   **Recommendation: (a).** Reading is open to everyone, signed in or not. A blocked person can
   log out, or open a private window, and read your posts at once. So (b) would only *look* like
   protection. (a) stops the things the server really can stop: their likes and replies on your
   posts. (b) is one more line in the same query, if the owner wants it anyway.

2. **Should like counts include likes from people you have blocked?**
   - (a) Yes. A count is the same number for everyone.
   - (b) No. Each person gets their own counts, without the people they blocked.

   **Recommendation: (a).** A count is a number, not a person's words, and it does not show who
   liked. With (a), `GET /likes` and `likes_for` do not change at all, and every window asks one
   shared question. (b) makes the count on one post differ between two people looking at the same
   screen, which is confusing. (Showing *who* liked is plan `who-liked`. That plan should leave
   blocked names out of the list for the person who blocked them. See section 5.)

3. **When you block someone, what happens to the likes they already gave your posts?**
   - (a) They stay, and are still counted.
   - (b) They are deleted.

   **Recommendation: (a).** Nothing is quietly deleted, and **Unblock** puts everything back
   exactly as it was. After the block, they cannot add new likes to your posts.

4. **Is a blocked person told they are blocked?**
   - (a) Only when they try to like or reply to your post: the server says *"You cannot like this
     post."*
   - (b) Never: the like seems to work, but is not saved.
   - (c) Always: their page marks your posts as "blocked you".

   **Recommendation: (a).** (b) is a lie the page would show, and the next second's count would
   give it away anyway. (c) sends a list of who blocked them to their browser, which is more than
   they need. With (a), the page cannot check this rule before it sends the like (the page does
   not know who blocked you, and should not), so it shows the server's sentence.

5. **Your own other open windows.** If you block someone in one window, another window of yours
   still shows their *older* posts until it is reloaded. (Their *new* posts never arrive there:
   the server already leaves them out.)
   - (a) Accept this. Reloading, or logging in again, fixes it.
   - (b) Every window asks `GET /blocks` every second as well, and hides posts by itself.

   **Recommendation: (a)** for now. (b) adds a third request every second to every window for a
   rare case. If plan `edit-delete` builds a way to tell windows "these posts are gone *for you*",
   block uses it and this goes away (see section 5).

6. **Where is the Block button?**
   - (a) A small text button, **Block**, in each post's row next to the heart. It is shown only
     when you are signed in and the post is not yours. The browser asks *"Block @ben? You will no
     longer see their posts."* before it sends anything.
   - (b) A "···" menu on each post.
   - (c) Only a form: type an account name to block.

   **Recommendation: (a).** It is one plain button, where the person is looking when they decide.
   A menu is more code and harder to reach by keyboard. The confirm question stops a
   mis-tap, because the posts disappear at once. Unblocking happens in the "Blocked accounts" list,
   because the blocked person's posts are no longer there to press anything on.

## 3. Design

### Database: `upgrade_to_block(connection)`

Written like `upgrade_to_accounts`: one transaction, then `PRAGMA user_version`. The orchestrator
chooses the number.

```sql
CREATE TABLE blocks (
  blocker_id INTEGER NOT NULL REFERENCES users(id),   -- the person who pressed Block
  blocked_id INTEGER NOT NULL REFERENCES users(id),   -- the person they blocked
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id <> blocked_id)
)
```

- One row means "this person blocked that person". Unblocking deletes the row. Nothing is marked.
- `PRIMARY KEY (blocker_id, blocked_id)`: the same block cannot be saved twice, even if two
  presses arrive at the same moment (the same reason as `likes`).
- `CHECK (blocker_id <> blocked_id)`: a *check constraint* is a rule the database tests on every
  row it saves. This one means nobody can block themselves, even if the model is got around.
- A block points at a user by `id`, never by name. So a block on an old, unclaimed name (from
  before accounts) still holds after someone claims that name: it is the same row in `users`.
- No column for the time of the block: nothing reads it.

`create_tables` gains one line: `if version < N: upgrade_to_block(connection)`.

### Model

A new constant, next to `POSTS_WITH_AUTHORS` (which does **not** change):

```python
# Leaves out posts by anyone the viewer blocked. The viewer's id is the one "?".
# With None (nobody signed in), "blocker_id = NULL" matches no row, so nothing is left out.
NOT_BLOCKED = (" AND posts.author_id NOT IN "
               "(SELECT blocked_id FROM blocks WHERE blocker_id = ?)")
```

| Function | Add / change | What it does |
|---|---|---|
| `posts_after(db_path, after, viewer_id=None)` | change | Adds `NOT_BLOCKED` after `WHERE posts.id > ?`, and passes `viewer_id`. The default `None` keeps every other caller and test working unchanged. |
| `find_account(connection, name)` | add | `check_name(name)`, then the row (`id, name, display_name`) with `name = ? COLLATE NOCASE`, or `RuleBroken("There is no account @name.")`. Only reads: it never adds a user. |
| `add_block(db_path, blocker_id, name)` | add | `find_account`; if it is the blocker: `RuleBroken("You cannot block yourself.")`; `INSERT`; on `sqlite3.IntegrityError` (the primary key): `RuleBroken("You have already blocked @name.")`. Returns the blocked user's row. |
| `remove_block(db_path, blocker_id, name)` | add | `find_account`; one `DELETE … WHERE blocker_id = ? AND blocked_id = ?`; if `cursor.rowcount == 0`: `RuleBroken("You have not blocked @name.")`. Returns the row. Like `remove_like`: no look-then-delete gap. |
| `blocks_for(db_path, blocker_id)` | add | The users this person blocked (`name, display_name`), by account name. |
| `check_not_blocked_by_author(connection, post_id, user_id)` | add | If the author of `post_id` has blocked `user_id`: `RuleBroken("You cannot like this post.")`. Takes the sentence as an argument with that default, so `replies` can say "reply". |
| `add_like` | change | **One line**, after the "post exists" check: `check_not_blocked_by_author(connection, post_id, user_id)`. (Close the connection on the error, as the lines around it do.) |

`remove_like` does not change: a blocked person may still take back a like they gave before.
`likes_for` and `like_count_for` do not change (decision 2a).

### Routes (controller)

All three need sign-in. Who is blocking comes from the cookie, through `signed_in_user`.

| Request | JSON in | Answer |
|---|---|---|
| `POST /blocks` | `{"account_name": "ben"}` | `201 {"account_name": "ben", "display_name": "Ben Ito"}` · `400` with the rule · `401` |
| `DELETE /blocks` | `{"account_name": "ben"}` | `200`, the same JSON · `400` if not blocked · `401` |
| `GET /blocks` | — | `200 {"blocked": [{"account_name", "display_name"}, …]}` · `401` |
| `GET /posts?after=` | — | as before, but if the request has a valid cookie, posts by people that person blocked are left out |

- `do_GET`, `/posts` branch: **change**, two lines: `user = self.user_or_none()` and pass
  `user["id"] if user else None` to `posts_after`. A missing or ended cookie is not an error here:
  reading is open to everyone.
- `do_GET`: **add** an `elif url.path == "/blocks":` branch.
- `do_POST`: **change** the list of paths to include `"/blocks"`, and one `elif` → `take_block`.
- `do_DELETE`: **change**: one `elif` for `/blocks` → `end_block`, and the 404 sentence names
  `/blocks` too.
- `take_block(data)`, `end_block(data)`: **add**, written like `take_like`.
- `log_message` does not change: the page does not ask `GET /blocks` every second.

The body must say `Content-Type: application/json`, as every other request with a body
(`read_json` already does this).

### View

- `account_to_json(user)` is reused for one blocked account: it already gives exactly
  `account_name` and `display_name`, and nothing about the password.
- `blocks_to_json(rows)`: **add**. `{"blocked": [account_to_json(row) for row in rows]}`.

### Page

`index.html`, inside `#signed-in`, after the "Signed in as" line:

```html
<details id="blocked-section">
  <summary>Blocked accounts</summary>
  <ul id="blocked-list" class="blocked-list"></ul>
</details>
```

`<details>` is a box the browser opens and closes by itself, with no JavaScript.

`app.js`:

- **`showPost` (change, two lines).** `item.dataset.author = post.author;` so posts can be found
  by author, and `addBlockButton(likeRow, post);` after the heart is added.
- **`addBlockButton(row, post)` (add).** Only if `account !== null` and
  `post.author !== account.account_name` (the page's copy of "you cannot block yourself"): a
  `button.link-button.block` with `data-author`, text `Block`, and
  `aria-label="Block @" + post.author`.
- **`pressBlock(accountName)` (add).** `confirm(...)`; then `POST /blocks`. On `401`:
  `showSignedOut`. On `400`: show the sentence. On `201`: `hidePostsBy(accountName)` and
  `loadBlocked()`. One press at a time, with a `busy` flag, like `pressHeart`.
- **`hidePostsBy(accountName)` (add).** Removes every `li.post` with that `data-author` and its
  entry in `likeParts`. If `edit-delete` has merged and has a `removePost(postId)`, it calls that
  for each one instead.
- **`unblock(accountName)` (add).** `DELETE /blocks`; then `loadBlocked()` and
  `reloadTimeline()`, because the posts that come back are *older* than `lastId`, and `after`
  would never bring them.
- **`reloadTimeline()` (add).** Empties `#timeline` and `likeParts`, sets `lastId = 0`, and calls
  `checkForNewPosts()`.
- **`loadBlocked()` and `showBlocked(list)` (add).** `GET /blocks`, then one `<li>` per account:
  display name, `@name`, and an **Unblock** button. Text is set with `textContent`, never
  `innerHTML`. If the list is empty, the `<details>` is hidden.
- **`showSignedIn` (change, one line):** `loadBlocked();`. **`showSignedOut` (change, one line):**
  empty the list.
- **`afterAccountChange` (change, one line):** `checkForNewPosts()` becomes `reloadTimeline()`.
  Someone else, or nobody, is now looking, so the posts and the Block buttons must be drawn again.
- **`clickOnTimeline` (change):** one more `closest(".block")` branch → `pressBlock`.
- **The last two lines (change):** `askWhoIAm(); keepChecking();` becomes
  `askWhoIAm().then(keepChecking);`, so the first posts are drawn when the page already knows who
  is signed in, and the Block buttons are right from the start.
- `pressHeart` does not change: a `400` already shows the server's sentence and asks again.
- `checkForNewPosts` does **not** change. The server does the leaving-out.

`style.css` (and its copy `page-only/style.css`): at the end, under `/* block */`: `.block`
(small, quiet, beside the heart), `.blocked-list` and its Unblock buttons. Large type and high
contrast, as everywhere else.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | `create_tables` (one `if version < N` line) | change |
| `with-backend/server.py` | `upgrade_to_block` | add |
| `with-backend/server.py` | `NOT_BLOCKED` constant | add |
| `with-backend/server.py` | `posts_after` (new `viewer_id=None` argument, `NOT_BLOCKED` added) | change |
| `with-backend/server.py` | `find_account`, `add_block`, `remove_block`, `blocks_for`, `check_not_blocked_by_author` | add |
| `with-backend/server.py` | `add_like` (one call to `check_not_blocked_by_author`) | change |
| `with-backend/server.py` | `do_GET` (`/posts` passes the viewer; new `/blocks` branch) | change |
| `with-backend/server.py` | `do_POST` (path list, one `elif`) | change |
| `with-backend/server.py` | `do_DELETE` (one `elif`, 404 sentence) | change |
| `with-backend/server.py` | `take_block`, `end_block` | add |
| `with-backend/server.py` | `blocks_to_json` | add |
| `with-backend/server.py` | module docstring and MODEL banner ("five tables") | change |
| `with-backend/app.js` | `showPost` (two lines) | change |
| `with-backend/app.js` | `showSignedIn`, `showSignedOut`, `afterAccountChange` (one line each) | change |
| `with-backend/app.js` | `clickOnTimeline` (one branch); start-up line | change |
| `with-backend/app.js` | `addBlockButton`, `pressBlock`, `hidePostsBy`, `unblock`, `reloadTimeline`, `loadBlocked`, `showBlocked`, the click listener on `#blocked-list`, the `blockedSection`/`blockedList` constants | add |
| `with-backend/index.html` | `<details id="blocked-section">` inside `#signed-in` | add |
| `with-backend/style.css`, `page-only/style.css` | `/* block */` section at the end | add |
| `with-backend/test_server.py` | new methods at the end of each of the four classes | add |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (section 7) | add |

`POSTS_WITH_AUTHORS`, `post_to_json`, `checkForNewPosts`, `likes_for` and `GET /likes` are
**not** changed.

## 5. Depends on, and collides with

- **`accounts`** (depends): needs `user_for_session`, `user_or_none`, `signed_in_user`, `check_name`,
  `account_to_json`, and the signed-in page. Build on top of the merged `accounts`.
- **`edit-delete`** (soft): what block needs from it is only a page function
  `removePost(postId)` that removes one post and its `likeParts` entry; `hidePostsBy` calls it if
  it exists, and removes the `<li>` itself if not. If `edit-delete` designs its "tell open windows"
  feature as a per-viewer answer ("which of the posts you show are still visible *to you*"), then
  blocks fall out of it for free and decision 5 goes away. If it is a list of deleted posts for
  everyone, block does not use it. Both change `do_DELETE`, `clickOnTimeline` and `showPost`:
  small merge.
- **`replies`** (rule to share): a blocked person must not reply to the blocker's posts. Whichever
  merges second adds one call, `check_not_blocked_by_author(connection, parent_id, user_id,
  "You cannot reply to this post.")`, in the replies model. Replies are posts, so `NOT_BLOCKED`
  already hides a blocked person's replies. A reply from someone else *to* a hidden post is for
  `replies` to show (for example "a reply to a post you cannot see").
- **Every plan that returns posts must leave out blocked authors**: `timeline-flow` (older posts on
  scroll), `search`, `bookmarks`, `replies` (a thread). Each takes the viewer from `user_or_none`
  and adds `NOT_BLOCKED` to its query. Whichever merges second adds it.
- **`timeline-flow`**: changes `checkForNewPosts` and how posts are loaded. `reloadTimeline` must
  then also reset its "oldest loaded" mark. Collides on `showPost` and the start-up line.
- **`who-liked`**: should leave out names the viewer blocked (decision 2 keeps the *count* as is).
- **`report`, `bookmarks`, `edit-delete`, `replies`**: all add a button to each post, so all touch
  `showPost` and `clickOnTimeline`. Each change is one line or one branch; merge by keeping all.
- **`rate-limit`**: may want to limit `POST /blocks` too. Not needed here.
- Every plan with an upgrade touches `create_tables` by one line.

## 6. Tests

**`ModelTests`** (each makes two or three accounts with `create_account`):

- After Aiko blocks Ben, `posts_after(db, 0, aiko)` has none of Ben's posts; `posts_after(db, 0,
  carol)` and `posts_after(db, 0)` (signed out) still have them.
- Ben's posts written *after* the block never come to Aiko.
- Blocking yourself is refused with a sentence; a direct `INSERT` of `(1, 1)` into `blocks` is
  refused by the database (`IntegrityError`, the CHECK).
- Blocking twice is refused; a direct second `INSERT` is refused by the primary key.
- Blocking `@nobody` is refused, and the number of rows in `users` is the same afterwards.
- Blocking `@BEN` blocks `ben` (any capital letters).
- Unblocking deletes the row; unblocking someone not blocked is refused; after unblocking,
  `posts_after(db, 0, aiko)` has Ben's old posts again.
- Ben cannot like Aiko's post after she blocks him; he can still like Carol's; his like given
  *before* the block is still counted, and he can still take it back.
- `blocks_for` lists exactly the accounts this person blocked.
- A block on an old, unclaimed name still holds after someone claims it.
- `upgrade_to_block` on a database at the version before it keeps every user, post, like and
  session.

**`RealServerTest`**:

- `POST /blocks` without a cookie gets `401`; without `Content-Type: application/json` gets `400`.
- `GET /posts?after=0` with Aiko's cookie leaves out Ben's post; the same request with no cookie,
  and with a wrong cookie, includes it.
- `GET /blocks` with no cookie gets `401`.

**`JourneyTest`**, `test_the_whole_journey_of_a_block`, reading `timeline.db` with SQL after each
step: Aiko and Ben sign up and each post · Aiko sees Ben's post · Aiko sends `POST /blocks
{"account_name": "ben"}` → one row in `blocks` with their two ids · Aiko's next `GET /posts?after=0`
has no post by Ben · a window with no cookie still has it · Ben posts again; Aiko's poll does not
bring it · Ben presses the heart on Aiko's post → `400` "You cannot like this post." and no row in
`likes` · Aiko sends `"blocker": "ben"` in the JSON of a block: it is ignored, the blocker is still
Aiko (who comes from the cookie) · Aiko sends `DELETE /blocks` → the row is gone, and
`GET /posts?after=0` has both of Ben's posts, in order.

**`PageAndServerAgreeTest`**:

- The page asks for `/blocks` with `GET`, `POST` and `DELETE`, and the server answers each one
  (the existing "every request the page makes" test should see them; add `/blocks` to any test
  that lists the routes by hand).
- The JSON key the page sends to `/blocks` is `account_name`, the key `take_block` reads.
- The page compares `post.author` with `account.account_name` before it shows a Block button (the
  page's copy of "you cannot block yourself").
- Both `style.css` files are still the same.

## 7. Docs to update

- **`AGENTS.md`**: in the model list, add `add_block`, `remove_block`, `blocks_for`,
  `find_account`, `check_not_blocked_by_author`; the `blocks` table; a new short paragraph: "A post
  query that a person reads adds `NOT_BLOCKED` with the viewer's id. A block is never checked only
  in the page."
- **`DESIGN.md`**: a new section "Blocking": the table, why the server leaves posts out instead of
  the page hiding them, decisions 1 to 5, and two new rows in the adversarial review ("hide them in
  the page" → reject: the posts would still be sent; "hide your posts from the blocked person" →
  reject: reading is open, so it would be pretend).
- **`README.md`**: a "things to try": block someone in one window, watch their posts disappear;
  try to like the blocker's post from the blocked window; unblock.

## 8. Not in this plan

- Muting (hiding without stopping likes and replies), and blocking by word.
- Hiding the blocker's posts from the blocked person (decision 1b).
- Per-viewer like counts (decision 2b).
- Other open windows of the same person updating without a reload (decision 5b).
- Blocking in `page-only/` (it has no accounts).
- A list of who blocked you.
- An admin who blocks someone for everyone: that is closer to `report`.

## 9. Size

**M.** About 350 lines: `server.py` ~90, `app.js` ~90, `index.html` ~6, `style.css` ~20 (twice),
`test_server.py` ~160, docs ~40.

## Changes made at approval (orchestrator)

- **One visibility filter.** `groundwork` adds one model function that every list of posts uses
  (posts, older posts, search, bookmarks, replies, the picture route). `block` adds its condition
  inside that function, instead of its own `NOT_BLOCKED` piece used in many places. `report` adds
  its condition there too.
- **Decision 6 is changed.** Block lives in a "⋯" menu on each post, which `groundwork` adds and
  `report`, `edit-delete` and `replies` also use. It still asks to confirm.
- `who-liked` leaves blocked people out of its names; its count still includes them.
  `DESIGN.md` says why.
