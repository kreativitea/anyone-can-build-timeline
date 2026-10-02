Status: merged

# Report

## 1. What it does

A signed-in person can press **Report** on someone else's post, and may say why. When three
different people have reported the same post, the server stops sending it to anyone except its
author. The author still sees it, with a note that it is hidden from others. A person who pressed
Report by mistake can press it again to take the report back, and if that brings the post under
three reports, everyone sees it again.

## 2. Decisions for the owner

**2.1 Is "hidden" counted from the rows, or kept as a flag?**
- *Counted* (recommended). A post is hidden when `reports` holds 3 or more rows for it. This is
  the rule `likes` already follows: no second copy of a fact. Taking a report back un-hides the
  post by itself, with no extra code. If the limit is changed later, it applies to every post at
  once, old ones too.
- *A flag* (`posts.hidden`, set when the third report arrives). It would stay set if the limit
  were raised, and it would need code to clear it when a report is taken back. Its one gain is a
  cheaper query, and this timeline is far too small for that to matter.

**2.2 How many reports hide a post?**
- *A fixed number, 3* (recommended). One person can never hide a post alone, and two friends
  cannot either. In a class of 20 it is easy to understand: "three people said so".
- *Relative to how many accounts exist* (for example one in ten). Signing up more accounts would
  raise the limit, which is strange, and with 12 users it is 2, which is too low.
- *1.* Any one person could hide anything. No.

The number lives in one constant, `HIDE_AFTER_REPORTS = 3`, in the model.

**2.3 Can you report your own post?**
- *No* (recommended). It is refused, by the model and by the page. To remove your own post, use
  `edit-delete`.
- *Yes.* It would let a person count toward hiding their own post, which means nothing.

**2.4 Does the author still see their hidden post?**
- *Yes, with a note* (recommended): "Hidden from others: several people reported it." Otherwise
  the post simply vanishes from their screen, and they will think the app is broken.
- *No, hidden from everyone.* Simpler SQL, but confusing.

**2.5 How is a post un-hidden? There are no admins.**
- *Take a report back, plus one `sqlite3` line for whoever runs the server* (recommended). A
  reporter can press Report again to take it back. The person running the server can clear
  every report on post 12 with
  `sqlite3 with-backend/timeline.db 'delete from reports where post_id = 12'`.
  That is the smallest admin there is: no code, no new kind of account, and only someone with the
  server's computer can do it. It goes in `README.md` and `AGENTS.md`.
- *A real admin* (an `is_admin` column, an admin page, `DELETE /reports/all`). A new kind of user
  and a new screen. Too large for this plan; it would be its own plan.
- *Nothing.* A hidden post stays hidden forever, even if the reports were a mistake.

**2.6 Abuse: accounts are free, so one person can make three and hide anyone's post.**
- *Only people who had already posted before this post was written can report it* (recommended).
  "Before" means the reporter has a post with a smaller `id`. This is counted from rows that
  already exist, so it needs no new column. It stops the cheapest attack: make three new accounts
  now, and hide a post that is on the timeline now. Someone who plans ahead (makes the accounts,
  posts with each, then waits) can still do it; nothing short of real identity stops that. The
  cost is that a brand-new user cannot report until they have posted once, and the server tells
  them so.
- *Only accounts older than N days.* Needs a `created_at` column on `users`, which is a change to
  `accounts`. The same protection, more change.
- *No rule.* Three accounts hide anything.
- In every case, `rate-limit` (if it limits sign-ups) makes the attack slower.

**2.7 Does a report need a reason?**
- *Optional, free text, up to 200 characters* (recommended). The page asks with the browser's own
  `prompt()` box: Cancel means "do not report", an empty answer means "no reason". The reason is
  shown to nobody in the app; only the person running the server reads it, with `sqlite3`.
- *A fixed list* (spam, rude, other). Needs new HTML and a list kept the same on both sides.
- *No reason at all.* Drop the column.

**2.8 Does editing a hidden post (from `edit-delete`) clear its reports?**
- *No* (recommended). The reports belong to the post's `id`, so they stay. Otherwise an author
  could un-hide a post by changing one letter.

## 3. Design

### Database: `upgrade_to_report(connection)`

Written like `upgrade_to_accounts`: one transaction, then the orchestrator's `user_version`.

```sql
CREATE TABLE reports (
  post_id INTEGER NOT NULL REFERENCES posts(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  reason  TEXT CHECK (reason IS NULL OR length(reason) <= 200),
  PRIMARY KEY (post_id, user_id)
)
```

- `PRIMARY KEY (post_id, user_id)`: one report per person per post. The database refuses a
  second one, even if every check in the code is got around. Because `post_id` comes first in the
  key, counting the reports for one post is fast without another index.
- `CHECK` on `reason`: the database refuses a reason over 200 characters, the same limit as the
  model.
- No `hidden` column and no count column anywhere (decision 2.1).
- The two rules the database cannot hold (not your own post; you posted before it) are in the
  model.

`create_tables` gets one line: `if version < N: upgrade_to_report(connection)`.

### Model

```python
HIDE_AFTER_REPORTS = 3
MAX_REASON = 200
```

| Function | What it does |
|---|---|
| `check_reason(reason)` | `None` or missing → `None`. Text is trimmed; empty → `None`; over `MAX_REASON` → `RuleBroken`; not text → `RuleBroken`. |
| `check_report_rules(connection, user_id, post_id)` | Raises `RuleBroken` if the post does not exist ("That post does not exist."), if it is the reporter's own post ("You cannot report your own post."), or if the reporter has no post with a smaller id ("You can report a post only after you have posted something before it."). |
| `add_report(db_path, user_id, post_id, reason)` | `check_post_id`, `check_reason`, `check_report_rules`, then `INSERT`. A second report is refused by a look first, and by the primary key in a race (`IntegrityError` → "You have already reported that post."), exactly like `add_like`. Returns `post_id`. |
| `remove_report(db_path, user_id, post_id)` | One `DELETE … WHERE post_id = ? AND user_id = ?`; `rowcount == 0` → "You have not reported that post." Like `remove_like`. Returns `post_id`. |
| `visible_to(viewer_id)` | Returns `(sql, params)`: the piece of `WHERE` that keeps a hidden post out, and its values. `viewer_id` is `None` for a window not signed in. |
| `reports_for(db_path, user_id)` | Returns three lists of post ids: hidden posts by other people, hidden posts by this user, and the posts this user has reported. The last two are empty when `user_id` is `None`. |
| `upgrade_to_report(connection)` | The table above. |

`visible_to` is the whole hide rule, in one place:

```python
def visible_to(viewer_id):
    """The part of a WHERE that hides a post reported by HIDE_AFTER_REPORTS people.

    Its author still sees it. viewer_id is None when nobody is logged in.
    """
    sql = ("((SELECT COUNT(*) FROM reports WHERE reports.post_id = posts.id) < ? "
           "OR posts.author_id IS ?)")
    return sql, [HIDE_AFTER_REPORTS, viewer_id]
```

`posts_after` gains one argument, `viewer_id=None`, and builds its `WHERE` from a list, so that
`block` can add its own condition beside this one with two lines and no other change:

```python
def posts_after(db_path, after, viewer_id=None):
    conditions, params = ["posts.id > ?"], [after]
    hidden_sql, hidden_params = visible_to(viewer_id)
    conditions.append(hidden_sql)
    params += hidden_params
    # block adds its condition here, the same way.
    connection = connect(db_path)
    rows = connection.execute(POSTS_WITH_AUTHORS + " WHERE " + " AND ".join(conditions)
                              + " ORDER BY posts.id", params).fetchall()
    ...
```

`POSTS_WITH_AUTHORS` is **not** changed. `save_post` is not changed: it reads back one post by
its id for its author, who may always see it. `add_like` is not changed: a hidden post has no
heart on anyone's screen, and liking one by hand harms nobody.

`reports_for` never returns counts and never says who reported. A count would tell people "one
more and it is gone"; the names would invite revenge.

### Routes

| Request | JSON in | Answer |
|---|---|---|
| `POST /reports` | `post_id`, `reason` (optional) | `201 {"post_id": 7, "reported": true}` · `400` with the rule broken · `401` |
| `DELETE /reports` | `post_id` | `200 {"post_id": 7, "reported": false}` · `400` if you had not reported it · `401` |
| `GET /reports` | — | `200 {"hidden": [7], "mine_hidden": [9], "reported": [7, 12]}`. Anyone may ask; signed out, the last two are empty. |
| `GET /posts?after=…` | — | the same answer as now, without posts hidden from this viewer. The viewer comes from the cookie through `user_or_none`. |

Controller changes, all small:

- `do_GET`: the `/posts` branch passes `viewer_id` (one line: `user = self.user_or_none()`, and
  `user["id"] if user else None`). A new `elif url.path == "/reports"` branch.
- `do_POST`: `"/reports"` added to the tuple of paths, and one `elif` that calls `take_report`.
- `do_DELETE`: a `/reports` branch before the `/likes` check, calling `drop_report`; the 404
  message names `/reports` too.
- New methods `take_report(data)` and `drop_report(data)`, written like `take_like`.
- `log_message`: `GET /reports` is asked every second, so it is not printed, like `/posts` and
  `/likes`.

### View

- `report_to_json(post_id, reported)` → `{"post_id": 7, "reported": true}`
- `reports_to_json(hidden, mine_hidden, reported)` → the `GET /reports` answer.

`post_to_json` is not changed.

### Page (`with-backend/app.js`, `style.css`)

- `const MAX_REASON = 200;` beside the other rules.
- `showPost`: one change. After the heart, add a **Report** button (`class="report"`,
  `data-post-id`, `data-author`, `aria-pressed`). It is kept in `reportParts[post.id]`, the same
  way as `likeParts`.
- `pressReport(postId)` (new): signed out → "Please log in to report a post."; your own post →
  "You cannot report your own post."; if not yet reported, `prompt("Why are you reporting this
  post? (optional)")`, Cancel stops, a reason longer than `MAX_REASON` is refused on the page;
  then `POST` or `DELETE /reports`. One press at a time (a `busy` flag), and on `401` or `400`
  it shows the server's sentence and asks again, exactly like `pressHeart`.
  The "you must have posted before it" rule is checked only by the server: the page may not have
  every older post on screen, so it cannot know for sure. It shows the server's sentence.
- `showReports(answer)` (new): for each id in `hidden`, take that post off the screen; for each id
  in `mine_hidden`, add the class `hidden-by-reports` and the note "Hidden from others: several
  people reported it."; remove that note from my posts that are no longer hidden; show each
  Report button as pressed or not from `reported`.
- `forgetPost(postId)` (new, unless `edit-delete` has already added one; see section 5): removes
  the `<li>` and deletes `likeParts[postId]` and `reportParts[postId]`.
- `checkForNewPosts`: one change, after the likes: `fetch("/reports")` and `showReports`.
- `clickOnTimeline`: one change, an `else if` for `.report`.
- `style.css`, at the end under `/* report */`: the Report button (small, quiet, not red until
  pressed), `.report.reported`, and `.hidden-by-reports` (faded, with the note). Copied to
  `page-only/style.css`.

**A post hidden while it is on screen.** `GET /posts?after=` never sends an old post again, so it
cannot carry "this post is now hidden". `GET /reports` does, once a second, the same way
`GET /likes` carries counts: it sends *all* hidden ids each time, and the page takes them off. A
post that is un-hidden later does not come back into a window that has already passed its id; it
comes back on reload. That is acceptable for a rare event, and section 8 says so.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | `do_GET`: `/posts` branch passes the viewer; new `/reports` branch | change |
| `with-backend/server.py` | `do_POST`: path tuple, one `elif` | change |
| `with-backend/server.py` | `do_DELETE`: `/reports` branch, 404 message | change |
| `with-backend/server.py` | `take_report`, `drop_report` | add |
| `with-backend/server.py` | `log_message`: also quiet for `GET /reports` | change |
| `with-backend/server.py` | `HIDE_AFTER_REPORTS`, `MAX_REASON` | add |
| `with-backend/server.py` | `create_tables`: one `if version < N` line | change |
| `with-backend/server.py` | `upgrade_to_report` | add |
| `with-backend/server.py` | `check_reason`, `check_report_rules`, `add_report`, `remove_report`, `visible_to`, `reports_for` | add |
| `with-backend/server.py` | `posts_after`: `viewer_id=None`, `WHERE` built from a list | change |
| `with-backend/server.py` | `report_to_json`, `reports_to_json` | add |
| `with-backend/server.py` | module docstring and MODEL banner: five tables | change |
| `with-backend/app.js` | `MAX_REASON`, `reportParts` | add |
| `with-backend/app.js` | `showPost`: append the Report button | change |
| `with-backend/app.js` | `pressReport`, `showReports`, `forgetPost` | add |
| `with-backend/app.js` | `checkForNewPosts`: fetch `/reports` | change |
| `with-backend/app.js` | `clickOnTimeline`: `.report` branch | change |
| `with-backend/style.css`, `page-only/style.css` | end of file, `/* report */` | add |
| `with-backend/test_server.py` | new methods at the end of each of the four classes | add |
| `with-backend/test_server.py` | the `PageAndServerAgreeTest` list of routes and methods the page may use gains `/reports` | change |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (section 7) | add |

`with-backend/index.html` is not touched.

## 5. Depends on, and collides with

- **`accounts`** (depends). Needs `user_for_session`, `user_or_none`, `signed_in_user`, and
  `check_post_id`.
- **`block`** (collides in `posts_after` and the `do_GET /posts` branch). Both filters need the
  viewer, and both are conditions joined by `AND`, so the order does not matter and a post must
  pass both. Whichever plan lands first adds `viewer_id=None` and the `conditions, params` list
  in `posts_after`, and the `user_or_none()` line in `do_GET`; the second adds only its own
  two-line condition, written as a function like `visible_to`. Neither changes
  `POSTS_WITH_AUTHORS`. Blocking and reporting are separate: a report from someone the author has
  blocked still counts.
- **`edit-delete`** (collides in the page, and in the database). What this plan needs from it:
  1. A page function that takes one post off the screen by id. If it has one, `report` uses it
     instead of adding `forgetPost`; it must also delete `likeParts[id]` (and this plan adds
     `reportParts[id]`).
  2. Its way of telling windows about changes should not assume that every post that leaves the
     screen was deleted. This plan does not write "hidden" into any change log, because hidden is
     counted, not stored; it uses its own `GET /reports` poll instead.
  3. If it deletes rows from `posts`, it must delete that post's `reports` rows first (foreign
     keys are on), as it must for `likes`.
  4. Editing keeps the reports (decision 2.8).
- **`timeline-flow`, `search`, `replies`, `bookmarks`** (follow the rule). Any new query that
  lists posts must add `visible_to(viewer_id)` to its `WHERE`, or a hidden post comes back
  through the side door. "3 new posts" must count only visible posts.
- **`pictures`**: a hidden post's picture must not be served to anyone but its author.
- **`rate-limit`**: a limit on sign-ups makes the abuse in 2.6 slower. No code shared.
- **`japanese`**: new sentences to translate: the button, the note, five error messages.
- **`dark-mode`**: both add CSS at the end of `style.css`; the new rules use the existing colours.
- Every plan with a database change adds one line to `create_tables`.

## 6. Tests

**`ModelTests`**
- A report is saved as one row, with its reason; with no reason, `reason` is `NULL`.
- The same person reporting the same post twice is refused; a raw second `INSERT` is refused by
  the database (`IntegrityError`).
- Reporting your own post is refused. Reporting a post that does not exist is refused.
- A user whose only post is newer than the target cannot report it; after posting before it, they
  can (set up with posts in order).
- A reason of 201 characters is refused; 200 is allowed; a raw `INSERT` of 201 is refused by the
  `CHECK`.
- Two reports: `posts_after` still returns the post to everyone. Three: it is gone for another
  user and for `viewer_id=None`, and still there for its author.
- Taking one of the three back makes it visible again. Taking back a report you do not have, or
  twice, is refused.
- `reports_for` gives `hidden`, `mine_hidden` and `reported` correctly, and empty lists for
  `None`.
- `posts` has no hidden or count column (`PRAGMA table_info(posts)`).
- `upgrade_to_report` on a database made by the accounts version keeps every user, post, like and
  session.

**`RealServerTest`**
- `POST /reports` without a cookie gets `401`; with a body that is not JSON gets `400`.
- `GET /reports` without a cookie gets `200` with `reported` and `mine_hidden` empty.

**`JourneyTest`** (`test_the_whole_journey_of_a_report`)
- Five people sign up (Aiko, Ben, Chika, Dai, Emi). Ben, Chika and Dai each post first; then Aiko
  posts the target. Emi does not post. After every step, read `reports` and `posts` with SQL.
- Aiko reports her own post: `400`, no row. Ben reports it with a reason: one row. Ben again:
  `400`, still one row. Ben takes it back: no row. Ben, Chika and Dai report it: three rows.
- Emi, who has no posts, reports it: `400`, no row.
- `GET /posts?after=0`: missing for Ben, for Emi and for a window with no cookie; present for
  Aiko. `GET /reports`: Ben sees it in `hidden`; Aiko sees it in `mine_hidden`. The `posts` row is
  still in the database.
- Dai takes his report back: everyone gets the post again.
- A request with `"user_id"` in the JSON reports as the cookie's person, not that id.

**`PageAndServerAgreeTest`**
- The page asks for `/reports` with `GET`, `POST` and `DELETE`, and the server answers each.
- The JSON keys the page sends to `/reports` (`post_id`, `reason`) are exactly the keys the
  server reads.
- `MAX_REASON` is the same number in `app.js` and `server.py`.
- Both `style.css` files are still the same.

## 7. Docs to update

- `AGENTS.md`: add the `reports` table to the model list, the new functions, and the sentence
  "A post is hidden when `HIDE_AFTER_REPORTS` people report it; this is counted from `reports`,
  never stored. Any query that lists posts uses `visible_to`." Also the `sqlite3` line that
  clears a post's reports.
- `DESIGN.md`: a new section *Reports*: the table, why hidden is counted, the threshold, the
  "posted before" rule and what it does not stop, and new rows in the adversarial review.
- `README.md`: under things to try, "report a post from three accounts, and watch it disappear
  from a fourth window"; and how the person running the server un-hides a post.

## 8. Not in this plan

- A real admin role, an admin page, or a list of reported posts in the app.
- Showing the reason, the count or the reporters' names to anyone in the app.
- Hiding the author's other posts, or suspending an account.
- Bringing an un-hidden post back into a window that has already scrolled past its id, without a
  reload.
- Hiding replies to a hidden post (`replies` decides).
- Telling the author by email (`reply-email` is only for replies).
- Any change to `page-only/` except the copied `style.css`.

## 9. Size

**M.** About 420 lines: `server.py` about 130, `app.js` about 90, `style.css` about 20 (twice),
tests about 180, docs about 40.

## Changes made at approval (orchestrator)

- Decisions 2.1 to 2.8 approved as recommended.
- **No `GET /reports` every second.** When a report or a report taken back moves a post across
  `HIDE_AFTER_REPORTS`, the model writes a "hidden" or "shown" row into `edit-delete`'s changes
  feed, and open windows learn from that. The page asks `GET /reports` only when it opens, after a
  login, and after a press, for the "reported" and "mine hidden" states. Hidden is still counted
  from rows; the change row is only the news that it happened.
- `visible_to` already exists in `groundwork`; this plan adds its condition inside it.
- The Report button is an item in `groundwork`'s "⋯" menu.
