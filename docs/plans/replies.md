Status: built on branch replies, awaiting merge

# Replies

## 1. What it does

Under each post there is a **Reply** button. A signed-in person presses it, writes an answer, and
presses Post. The answer (a *reply*) appears under the post it answers, with a small line
"replying to @aiko", and the post shows how many replies it has ("2 replies"). A reply is a
normal post in every other way: it has an author, a time and a heart.

## 2. Decisions for the owner

1. **Can someone reply to a reply?**
   - A. No, one level only. The Reply button is only on posts that are not replies. *(recommended)*
   - B. Yes, a tree (replies to replies to replies). Needs indents inside indents, and is hard to
     read on a phone.
   - *Why A:* simple to show and to test, and the database can enforce it (see 3, the trigger).
     If people want to answer a reply, they reply to the same post and write "@ken".

2. **Where does a reply appear?**
   - A. Only under the post it answers, oldest reply first, so it reads like a conversation.
     *(recommended)*
   - B. Under the post **and** at the top of the main timeline.
   - C. Under the post, but folded: only "2 replies" shows until you press it.
   - *Why A:* every reply is shown once, nothing is hidden, and no extra state is needed. The
     cost: a new reply to an old post appears low on the page. `timeline-flow` can point to it later.

3. **Can you reply to your own post?**
   - A. Yes. *(recommended)* People add a second thought, or a correction. It costs nothing.
   - B. No. A new rule in the model and in the page.

4. **The route.**
   - A. `POST /posts` with an extra `parent_id`. *(recommended)* A reply is a post: same text
     rules, same polling, same hearts, nothing new for the page to ask for.
   - B. A new `POST /replies`. A second route that does almost the same thing.

5. **Where do you write the reply?**
   - A. In the main post box. Pressing Reply puts "Replying to @aiko · Cancel" above the box and
     moves the box into view. *(recommended)* One box, one character count, one set of checks.
   - B. A small new box opens under the post. Nicer, but it copies the box, the count and the checks.

6. **What happens to replies when their post is deleted?** This is decided in `edit-delete`, but
   this plan sets the safe starting point: **the database refuses to delete a post that has
   replies** (the `parent_id` foreign key has no `ON DELETE` action). `edit-delete` then picks one:
   - A. Keep the replies; the post shows "This post was deleted" in its place. *(recommended:
     nobody's words are removed by someone else)*
   - B. Delete the replies with the post, in one transaction. Removes other people's words.
   - C. Refuse to delete a post that has replies.

## 3. Design

### Database: `upgrade_to_replies(connection)`

Written like `upgrade_to_accounts`: one transaction, `BEGIN` … `commit`, and the `user_version`
number is chosen by the orchestrator. In `create_tables`, one new line:
`if version < N: upgrade_to_replies(connection)`.

```sql
ALTER TABLE posts ADD COLUMN parent_id INTEGER REFERENCES posts(id);
CREATE INDEX posts_by_parent ON posts (parent_id);
CREATE TRIGGER replies_are_one_level BEFORE INSERT ON posts
  WHEN NEW.parent_id IS NOT NULL
   AND (SELECT parent_id FROM posts WHERE id = NEW.parent_id) IS NOT NULL
  BEGIN SELECT RAISE(ABORT, 'A reply cannot be answered.'); END;
```

- `parent_id` is `NULL` for a normal post. For a reply it is the id of the post it answers, just as
  `author_id` points at a user. Every old post gets `NULL`, so no old row changes.
- A *foreign key* (`REFERENCES posts(id)`) means the database itself refuses a reply to a post that
  does not exist, and refuses deleting a post that still has replies (decision 6).
- An *index* (`posts_by_parent`) is a sorted list the database keeps, so finding a post's replies
  is fast.
- A *trigger* is a rule the database runs by itself before each insert. This one refuses a reply
  to a reply (decision 1A), even if the model's check is got around.
- **A reply count is never stored.** It is always the number of rows with that `parent_id`.

### Model

| Function | What it does |
|---|---|
| `check_parent_id(parent_id)` *(add)* | Returns it as a number, or raises `RuleBroken("The reply must say which post it answers.")`. Written like `check_post_id`. |
| `save_reply(db_path, user_id, text, parent_id)` *(add)* | `check_text`, `check_parent_id`. Reads the parent: missing → `RuleBroken("That post does not exist.")`; itself a reply → `RuleBroken("You can only reply to a post, not to a reply.")`. Inserts with `parent_id`. An `sqlite3.IntegrityError` (the parent was deleted a moment ago, or the trigger refused) → the same `RuleBroken`. Returns the row from `POSTS_WITH_AUTHORS`, like `save_post`. |
| `POSTS_WITH_AUTHORS` *(change)* | Two more columns: `posts.parent_id`, and `parent_author`, the parent's account name, looked up through `users` (never copied into `posts`): `(SELECT parent_users.name FROM posts AS parents JOIN users AS parent_users ON parent_users.id = parents.author_id WHERE parents.id = posts.parent_id) AS parent_author`. |

`save_post` does not change: a normal post is still saved by `save_post`. `posts_after` does not
change: it already returns every post, so replies come too, oldest first. Replying to yourself is
allowed (decision 3A), so there is no rule for it. A reply's text follows `check_text`, the same
as a post.

### Controller

`take_post` *(change, about 4 lines)*: after `signed_in_user`, it picks which model function to
call. This is choosing, not checking a rule:

```python
if data.get("parent_id") is None:
    row = save_post(self.server.db_path, user["id"], data.get("text"))
else:
    row = save_reply(self.server.db_path, user["id"], data.get("text"), data.get("parent_id"))
```

No new route. `do_POST` does not change.

### Route

| Request | JSON in | Answer |
|---|---|---|
| `POST /posts` | `text`, and `parent_id` (a number; missing or `null` means a normal post) | 201 + the post, or 400 (rule broken), or 401 (not signed in) |
| `GET /posts?after=N` | — | as now; each post now also has `parent_id` and `parent_author` |

### View

`post_to_json` *(change)*: adds `"parent_id": row["parent_id"]` and
`"parent_author": row["parent_author"]` (both `null` for a normal post). `post_to_log_line` does
not change.

### The hook for `reply-email`

The place to send an email is the reply branch in `take_post`, **after** `send_json(201, …)`, the
same place where the log line is printed: the reply is saved and answered before any email is
tried, so a slow or broken email never stops a reply. `reply-email` adds one line there, calling its
own model function with the saved row. The row already has `id`, `author`, `parent_id` and
`parent_author`, so it knows who to write to. It should skip a reply to your own post.

### Page (`with-backend/`)

- **`index.html`** *(add)*: inside `#post-form`, above the box, a line that starts hidden:
  `<p id="replying-to" hidden>Replying to <span id="replying-to-name"></span> ·
  <button type="button" id="cancel-reply" class="link-button">Cancel</button></p>`.
- **`app.js`**:
  - `let replyingTo = null;` *(add)*: `{ id, author }` while writing a reply.
  - `const replyParts = {};` *(add)*: for each normal post on screen, its replies list and its count.
  - `showPost` *(change, one line)*: the last line, `timeline.prepend(item)`, becomes
    `placePost(post, item)`. Everything else stays, so a reply gets a heart like any post.
  - `placePost(post, item)` *(add)*:
    - A normal post: add a row with a **Reply** button (`data-post-id`) and a count, and an empty
      `<ol class="replies">`; keep them in `replyParts`; put the item at the top of the timeline.
    - A reply whose parent is on screen: add the "replying to @aiko" line, and **append** it to the
      parent's `replies` list (oldest reply first), then `showReplyCount(post.parent_id)`.
    - A reply whose parent is not on screen (only possible after `timeline-flow`): add the
      "replying to @aiko" line and put it at the top like a normal post.
  - `showReplyCount(postId)` *(add)*: writes "1 reply" / "N replies" (hidden at 0). The number is
    how many reply items are in that list: the page counts the rows it was given, it never keeps
    its own number. This always equals the rows in the database, because a reply always has a
    larger id than its parent, so a window that has the parent has every reply too.
  - `startReply(postId)` *(add)*: if `account === null`, "Please log in to reply." Otherwise set
    `replyingTo`, show `#replying-to` with "@" + author, scroll the box into view and focus it.
  - `cancelReply()` *(add)*: clear `replyingTo`, hide `#replying-to`.
  - `sendPost` *(change, about 3 lines)*: the body is `{ text: text }`, plus
    `parent_id: replyingTo.id` when replying. After a 201, `cancelReply()`.
  - `clickOnTimeline` *(change, 3 lines)*: also `event.target.closest(".reply-button")` →
    `startReply(...)`.
  - `checkForNewPosts` does not change: the server sends posts oldest first, so a parent is always
    placed before its replies, even in one answer.
  - One new listener: `#cancel-reply` → `cancelReply`.
- **`style.css`** *(add at the end, under `/* replies */`)*: `.replies` (indented, a thin line on
  the left), `.replying-to`, `.reply-row`, `.reply-button`, `.reply-count`, `#replying-to`. Copied
  to `page-only/style.css`.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | `create_tables` (one `if version < N` line) | change |
| `with-backend/server.py` | `upgrade_to_replies` | add |
| `with-backend/server.py` | `POSTS_WITH_AUTHORS` (two columns) | change |
| `with-backend/server.py` | `check_parent_id`, `save_reply` | add |
| `with-backend/server.py` | `TimelineHandler.take_post` (pick `save_post` or `save_reply`) | change |
| `with-backend/server.py` | `post_to_json` (two keys) | change |
| `with-backend/app.js` | `replyingTo`, `replyParts`, `placePost`, `showReplyCount`, `startReply`, `cancelReply`, `#cancel-reply` listener | add |
| `with-backend/app.js` | `showPost` (last line), `sendPost` (body + after 201), `clickOnTimeline` (reply button) | change |
| `with-backend/index.html` | `#replying-to` line inside `#post-form` | add |
| `with-backend/style.css`, `page-only/style.css` | `/* replies */` section at the end | add |
| `with-backend/test_server.py` | new methods at the end of `ModelTests`, `RealServerTest`, `PageAndServerAgreeTest`; new `test_the_whole_journey_of_a_reply` at the end of `JourneyTest` | add |
| `AGENTS.md`, `DESIGN.md` | new short sections; model and view lists | add |

## 5. Depends on, and collides with

- **Depends on `accounts`**: `user_for_session`, `save_post(db_path, user_id, text)`,
  `POSTS_WITH_AUTHORS` with `display_name`, and the 401 handling in `sendPost`.
- **`reply-email`** depends on this plan: it uses the hook in `take_post` (section 3) and
  `parent_author`/`parent_id` in the row. Build it after this one.
- **`edit-delete`**: the `parent_id` foreign key refuses deleting a post with replies (decision 6),
  just as `likes` already refuses deleting a liked post. `edit-delete` must handle both. Both plans
  change `showPost` and `clickOnTimeline`; a deleted reply must also call `showReplyCount`. Editing
  never changes `parent_id`.
- **`timeline-flow`**: replies arrive through `/posts?after=`. A reply placed under a parent that is
  already on screen should not count in "3 new posts". Older posts loaded on scroll bring their
  replies in the same answer. Both change `showPost`/`checkForNewPosts`.
- **`rate-limit`**: replies must count too. Its check should be called from `save_reply` as well
  as `save_post` (or from `take_post`, before the branch).
- **`timestamps`**, **`pictures`**, **`place`**, **`links-and-tags`**: change `POSTS_WITH_AUTHORS`,
  `post_to_json` and/or `showPost` too. Each adds its own lines; the merge is small but by hand.
- **`block`**, **`report`**: a reply by a blocked person, or a hidden parent, must be hidden too;
  those plans decide how.
- **`search`**: a reply is a post, so search finds it; it may want to show "replying to @aiko".
- **`japanese`**: new words: "Reply", "replying to", "1 reply", "N replies", "Cancel", and the
  three new error messages.
- **`drafts`**: whether "replying to" is saved with the draft is that plan's choice (here: not saved).

## 6. Tests

**`ModelTests`** (new methods at the end)
- A reply is saved with its `parent_id`, and `posts_after` returns it with `parent_id` and
  `parent_author`; a normal post has both `None`.
- A reply to a post that does not exist is refused.
- A reply to a reply is refused by `save_reply`; and an `INSERT` written straight in SQL is refused
  by the trigger (`sqlite3.IntegrityError`).
- A `parent_id` that is not a number (`"abc"`, `[]`) is refused.
- A reply to your own post is allowed.
- A reply follows the text rules (empty and 281 characters are refused).
- The number of replies is the number of rows: `SELECT COUNT(*) … WHERE parent_id = ?` after two
  replies is 2; no count column exists in `posts`.
- Deleting a post that has a reply is refused by the database (the contract for `edit-delete`).
- The upgrade keeps every old post, each with `parent_id` `NULL`.

**`RealServerTest`**
- `POST /posts` with `parent_id` → 201, and the answer has `parent_id` and `parent_author`.
- The same without a cookie → 401, and no row.
- `parent_id: 9999` → 400 with a reason; `parent_id: "abc"` → 400.

**`JourneyTest`** — `test_the_whole_journey_of_a_reply`
- Aiko and Ken sign up. Aiko posts. Ken replies: the row in `posts` has `parent_id` = Aiko's post
  and `author_id` = Ken. `GET /posts?after=0` gives the reply after its parent.
- Ken sends `"author": "aiko"` with a reply: it is still Ken's.
- Aiko replies to her own post: allowed. Ken replies to Ken's reply: 400, and no new row.
- Aiko likes Ken's reply: one row in `likes`, as for any post.
- At the end, the count of rows with that `parent_id` (SQL) equals the number of posts in
  `GET /posts` with that `parent_id`.

**`PageAndServerAgreeTest`**
- The page sends `parent_id: ` and reads `post.parent_id` and `post.parent_author`, the same names
  as `post_to_json`.
- The page still asks only for routes the server answers (no new route).

## 7. Docs to update

- `AGENTS.md`: add `check_parent_id` and `save_reply` to the model list; say that `posts.parent_id`
  points at the post a reply answers, that a reply count is counted, never kept, and that the
  database refuses a reply to a reply and deleting a post that has replies.
- `DESIGN.md`: a new section "Replies": one level, shown under the parent, the trigger, and why the
  page's count matches the rows.
- `README.md`: one line under the things to try: "Reply to a post in one window; watch it appear
  under the post in another."

## 8. Not in this plan

- Replies to replies (a tree).
- Folding replies away, or a page for one conversation.
- Deleting a post that has replies (`edit-delete`), and emails (`reply-email`).
- Telling someone in the page that they got a reply (a notification).
- A reply in `page-only/` (it has no server).
- Changing which post a reply answers: nothing ever updates `parent_id`.

## 9. Size

**M**, about 300 lines: `server.py` about 60, `app.js` about 80, `index.html` 4, `style.css` about
30 (twice), tests about 120, docs about 20.

## Changes made at approval (orchestrator)

- **The reply count comes from the server**, counted from rows like `like_count`, and is sent
  with each post. The page adds one for each new reply that arrives. A count made only by the page
  is wrong when `timeline-flow` loads part of the timeline, or when `block` or `report` hide replies.
- **Drafts:** a draft remembers the post it replies to, as well as its text. Whichever of
  `replies` and `drafts` is built second adds this.
- **Deleting a post that has replies** is decided with `edit-delete` (see that plan).
- Replies are listed through the shared visibility filter from `groundwork`, and the reply
  button lives in the post's "⋯" menu or beside the heart, as `groundwork` sets out.
