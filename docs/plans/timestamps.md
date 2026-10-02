Status: approved

# Timestamps

## 1. What it does

Each post shows when it was written as "just now", "5 minutes ago" or "yesterday". The words change
as time passes, without reloading. Holding the mouse over the time shows the full date and time in the
reader's own time zone. A post from before this change has no date, so it shows its old clock time
with the words "date unknown". It does not show a guessed date.

## 2. Decisions for the owner

1. **How is a time kept in the database?**
   - (a) ISO 8601 text in UTC, to the second: `2026-10-02T07:42:10Z`. **UTC** (Coordinated Universal
     Time) is the one clock the whole world agrees on. The `Z` at the end means "this is UTC".
   - (b) A Unix number: the seconds since 1 January 1970, for example `1790926930`. `sessions.expires_at`
     already uses this.
   - **Recommendation: (a).** A person can read it in `sqlite3` without converting it. As text it sorts
     in the right order. The browser's `new Date(...)` reads it directly, and the database can check its
     shape with `GLOB` (a simple text pattern). Sessions can stay as numbers, because nobody reads them.

2. **Old posts have only `HH:MM` and no date. What happens to them?**
   - (a) Keep them, and say honestly that the date is unknown. The old `15:42` goes into a column
     called `old_clock_time`, and `posted_at` is empty (NULL). The page shows "15:42 · date unknown".
   - (b) Guess that they were written on the day of the upgrade. This would be wrong for most of them,
     and some would land in the future.
   - (c) Delete them (`make reset`).
   - **Recommendation: (a).** Accounts kept every old row, so this plan does too. The database also
     makes sure every post has either a full time or an old clock time. It cannot have both or neither.

3. **How long does a post say "… ago"?**
   - (a) For 7 days, then the date ("2 Oct", or "2 Oct 2025" if it was in another year).
   - (b) Always ("14 months ago").
   - (c) For 24 hours, then the date.
   - **Recommendation: (a).** After about a week, "23 days ago" is harder to use than a date.

4. **How is the full date shown?**
   - (a) A `<time datetime="2026-10-02T07:42:10Z">` element with a `title`, which shows a tooltip on hover:
     *Friday, 2 October 2026 at 16:42:10*, in the reader's own time zone.
   - (b) Always print the full date under each post.
   - **Recommendation: (a).** It keeps the timeline quiet. The `datetime` attribute also gives the exact
     time to screen readers and to other programs. A phone cannot hover, so phone users will not see
     the tooltip. Choose (b) if that matters.

5. **Which time goes in the server's log line?** (The log line is the text the server prints in the
   terminal for each new post.)
   - (a) UTC, exactly as it is saved: `2026-10-02T07:42:10Z  Aiko Tanaka @aiko: "…"`.
   - (b) The server's local time.
   - **Recommendation: (a).** The log then matches the database exactly. It also needs no code change:
     `post_to_log_line` already prints `row["posted_at"]`.

## 3. Design

**The rule that does not change:** the order of the timeline, and `GET /posts?after=`, use the post
**id**, never the time. Ids only go up. A clock can jump backwards, for example when the computer
corrects its time. Two posts can also have the same second. The time is only for showing to people.

**The time always comes from the server's clock.** The page never sends a time. If a request includes
a `posted_at`, the server ignores it, in the same way it ignores `"author"`.

### Database: `upgrade_to_timestamps(connection)`

SQLite cannot change a column from `NOT NULL` to "may be NULL" in place. So the upgrade **rebuilds**
the `posts` table. This is SQLite's own documented way to do it. The steps are written like
`upgrade_to_accounts`, and all of them happen in one transaction:

1. `PRAGMA foreign_keys = OFF`. This must happen before `BEGIN`, because SQLite ignores the setting
   inside a transaction. `likes` points at `posts`, and the old `posts` table is removed for a moment.
2. `BEGIN`.
3. Create `posts_new`:
   ```sql
   CREATE TABLE posts_new (
     id INTEGER PRIMARY KEY,
     author_id INTEGER NOT NULL REFERENCES users(id),
     text TEXT NOT NULL,
     posted_at TEXT CHECK (posted_at GLOB
       '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
     old_clock_time TEXT CHECK (old_clock_time GLOB '[0-9][0-9]:[0-9][0-9]'),
     CHECK ((posted_at IS NULL) <> (old_clock_time IS NULL))
   )
   ```
   A `CHECK` on a NULL value passes, so each column's own check applies only when the column has a
   value. The last `CHECK` means exactly one of the two must have a value.
4. `INSERT INTO posts_new (id, author_id, text, posted_at, old_clock_time)
   SELECT id, author_id, text, NULL, posted_at FROM posts`. Ids do not change, so every like still
   points at the right post.
5. `DROP TABLE posts`, then `ALTER TABLE posts_new RENAME TO posts`.
6. `PRAGMA foreign_key_check`. If it returns any row, roll back and stop with a clear `SystemExit`
   message, as `upgrade_to_accounts` does.
7. Set `PRAGMA user_version` (the orchestrator chooses the number), `COMMIT`, then
   `PRAGMA foreign_keys = ON`.

If an old row's `posted_at` is not `HH:MM`, the `CHECK` refuses it. In that case, roll back and stop
with a message that suggests `make reset`. This should never happen, because only
`time.strftime("%H:%M")` ever wrote that column.

A new database follows the same steps. It is created at version 0, and then it is upgraded.
`create_tables` is not changed except for one new line: `if version < N: upgrade_to_timestamps(connection)`.

The column order stays `id|author_id|text|posted_at|…`, so the `sqlite3` line in the README keeps its
shape. It only gains `old_clock_time` at the end.

### Model

- `TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"`, one constant used for both writing and reading.
- `utc_now()` (**add**). It returns `datetime.now(timezone.utc)`. This is the only place that reads the
  real clock for posts.
- `utc_text(moment)` (**add**). It turns an aware `datetime` into `2026-10-02T07:42:10Z`. It first
  converts the time to UTC with `moment.astimezone(timezone.utc)`, so a time in Japan Standard Time
  (JST) is saved correctly. If `moment` has no time zone, it raises `ValueError`, because a time
  without a zone cannot be placed honestly. This is a programmer's mistake, so it is not a
  `RuleBroken`, and a user can never cause it.
- `save_post(db_path, user_id, text, now=None)` (**change**). It gains one keyword argument at the
  end. `now = now or utc_now()`, and the `INSERT` writes `utc_text(now)` into `posted_at`
  instead of `time.strftime("%H:%M")`.
  **Tests use this to set the time, so they do not depend on the real clock.** `utc_now` is looked up
  each time the function is called, so a test of the running server can also replace it with
  `unittest.mock.patch("server.utc_now", ...)`.
- `POSTS_WITH_AUTHORS` (**change**): add `posts.old_clock_time` after `posts.posted_at`.
- `posts_after` does not change. It still uses `WHERE posts.id > ? ORDER BY posts.id`.

Python 3.9 note: `datetime.fromisoformat` in 3.9 cannot read a trailing `Z`. If code needs to read a
saved time back, use `datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)`. This plan
itself never needs to read one back.

### Routes

No new routes. `POST /posts` and `GET /posts?after=` send the same JSON as before, with a new key and
a changed value:

```json
{"id": 9, "author": "aiko", "display_name": "Aiko Tanaka", "text": "…",
 "posted_at": "2026-10-02T07:42:10Z", "old_clock_time": null, "like_count": 0}
```
An old post looks like this instead: `"posted_at": null, "old_clock_time": "15:42"`. The status codes
do not change.

### View

- `post_to_json` (**change**): add `"old_clock_time": row["old_clock_time"]`. That is one key.
- `post_to_log_line`: no change. Its output now begins with the full UTC time.

### Page (`with-backend/app.js`)

The browser already has everything needed: `Date`, `Intl.RelativeTimeFormat` (it makes words like
"5 minutes ago" in the reader's language) and `toLocaleString`. No library is needed.

- `timeAgo(moment, now)` (**add**). It takes two `Date` values and returns text:
  - under 60 seconds, **or in the future**: "just now". (The reader's clock may be a few seconds
    ahead of or behind the server's. A brand-new post must never say "in 3 seconds".)
  - under 1 hour: "5 minutes ago". Under 1 day: "3 hours ago". Under 7 days: "yesterday" or
    "3 days ago". These come from `new Intl.RelativeTimeFormat(undefined, { numeric: "auto" })`.
  - 7 days or more: `moment.toLocaleDateString(undefined, { day: "numeric", month: "short" })`, plus
    `year: "numeric"` when the year is not this year.
- `fullLocalTime(moment)` (**add**):
  `moment.toLocaleString(undefined, { dateStyle: "full", timeStyle: "medium" })`.
- `timeElement(postedAt, oldClockTime)` (**add**). This is **the one helper other plans reuse.**
  - With `postedAt`, it makes `<time class="post-time" datetime="…" title="…" data-relative>`, with
    its text set by `timeAgo`.
  - With only `oldClockTime`, it makes `<span class="post-time post-time-unknown"
    title="Posted before Timeline kept dates">15:42 · date unknown</span>`.
  - It uses `textContent` and `setAttribute` only, never `innerHTML`.
- `refreshTimes()` (**add**). For every `time[data-relative]` on the page, it writes `timeAgo` again.
  It is called by `setInterval(refreshTimes, 30000)`, next to `keepChecking()` at the bottom of the
  file. Every 30 seconds is often enough, because the smallest unit shown is one minute.
- `showPost` (**change, 3 lines → 1**). Replace the three lines that make the `post-time` span with
  `const time = timeElement(post.posted_at, post.old_clock_time);`. Nothing else in `showPost` changes.

**How other plans show a time:** call `timeElement(isoText)` and append the result. Its words then
refresh by themselves, because `refreshTimes` finds every `time[data-relative]`. In the server, save a
time with `utc_text(now)`, where `now` is an argument that defaults to `utc_now()`. Do not call
`time.strftime` or `datetime.now()` directly.
- `edit-delete`: save `edited_at` with `utc_text`, and show "edited 2 minutes ago" with
  `timeElement`.
- `replies`, `search` and `timeline-flow` (older posts loaded on scroll, and the "3 new posts"
  button): they all build posts through `showPost`, or through a function that calls `timeElement`.
  `timeline-flow` loads older posts by **id** (`before=`), not by time.
- `rate-limit`: count recent posts by comparing `posted_at` text. ISO text in UTC sorts in time order.
  Take `now` as an argument, as `save_post` does, so its tests do not depend on the clock either.
- `japanese`: `undefined` as the locale means "the browser's language", so "5 分前" works without
  extra work. If the app gets its own language switch, pass `document.documentElement.lang` instead.

### CSS

At the end of `style.css`, under `/* timestamps */`, add `.post-time-unknown { font-style: italic; }`
and `time.post-time { cursor: help; }`. The existing `.post-time` rule is not changed. Copy the result to
`page-only/style.css`.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | imports: `from datetime import datetime, timezone` | change |
| `with-backend/server.py` | `create_tables`: one `if version < N` line | change |
| `with-backend/server.py` | `upgrade_to_timestamps` | add |
| `with-backend/server.py` | `TIME_FORMAT`, `utc_now`, `utc_text` | add |
| `with-backend/server.py` | `POSTS_WITH_AUTHORS`: add `posts.old_clock_time` | change |
| `with-backend/server.py` | `save_post`: `now=None`, write `utc_text(now)` | change |
| `with-backend/server.py` | `post_to_json`: add `old_clock_time` | change |
| `with-backend/app.js` | `timeAgo`, `fullLocalTime`, `timeElement`, `refreshTimes` | add |
| `with-backend/app.js` | `showPost`: 3 lines → 1 call to `timeElement` | change |
| `with-backend/app.js` | bottom: `setInterval(refreshTimes, 30000)` | add |
| `with-backend/style.css`, `page-only/style.css` | `/* timestamps */` section at the end | add |
| `with-backend/test_server.py` | new methods at the end of `ModelTests`, `RealServerTest`, `JourneyTest`, `PageAndServerAgreeTest` | add |
| `with-backend/test_server.py` | `test_saved_post_comes_back_with_id_and_time`: change the `HH:MM` regex to the ISO form | change |
| `with-backend/test_server.py` | `test_log_line_has_the_time_the_author_and_the_text`: pass a fixed `now`, and expect the ISO form | change |
| `DESIGN.md`, `AGENTS.md`, `README.md` | see section 7 | change / add |

`with-backend/index.html`, the controller (`TimelineHandler`) and `post_to_log_line` do not change.

## 5. Depends on, and collides with

- **`accounts`: depends on it.** This plan is written against its `save_post(db_path, user_id, text)`,
  its `POSTS_WITH_AUTHORS` and `upgrade_to_accounts`.
- **Every plan that adds a column to `posts`, or an index on it** (probably `replies`, `edit-delete`,
  `pictures`, `place`, `report`). **This is a real collision.** The rebuild copies a fixed list of
  columns, so a column added by an earlier upgrade would be lost. **Merge `timestamps` before them**,
  so their `ALTER TABLE posts ADD COLUMN` runs on the rebuilt table. If that is not possible, whoever
  rebases must add those columns, and recreate those indexes, in `posts_new`. A new table that only
  *points at* `posts` (for example `post_versions`) is safe in either order, because ids do not change.
- **`showPost`, `POSTS_WITH_AUTHORS`, `post_to_json`, `save_post`**: these are shared with `replies`,
  `edit-delete`, `pictures`, `place`, `links-and-tags`, `who-liked` and `rate-limit`. The changes here
  are one or two lines each, so the conflicts are small text conflicts.
- **`edit-delete`, `replies`, `search`, `timeline-flow`, `rate-limit`, `japanese`**: these should
  *reuse* `timeElement`, `utc_now` and `utc_text` (see section 3). It is easier for them if
  `timestamps` merges first.

## 6. Tests

None of them depend on the real clock. They pass a fixed `now`, check only the shape of the time, or
check that it lies between two readings of the clock taken just before and just after.

**`ModelTests`**
- `save_post(..., now=datetime(2026, 10, 2, 7, 42, 10, tzinfo=timezone.utc))` saves exactly
  `2026-10-02T07:42:10Z`. Read it back with SQL.
- A time in JST (`+09:00`), 16:42:10, is saved as `07:42:10Z`.
- `utc_text` of a datetime without a time zone raises `ValueError`.
- Two posts at 15:42 on two different days get two different `posted_at` values.
- With no `now`, the saved time has the ISO shape and lies between two readings of the clock, one taken
  just before and one just after.
- The database refuses an `INSERT` with `posted_at = '15:42'`, one with both columns NULL, and one with
  both columns set (`sqlite3.IntegrityError`).
- Upgrade: build a version-1 database by hand, with two users, posts at `15:42` and `09:05`, and a like.
  Then run `create_tables`, and check:
  - every row is kept, and the ids are the same;
  - `posted_at` is NULL and `old_clock_time` holds the old text;
  - the like still points at its post;
  - `PRAGMA foreign_key_check` returns nothing;
  - `PRAGMA foreign_keys` is ON again;
  - `user_version` is the new number.
- After the upgrade, a new post gets a full time, and `posts_after(0)` still returns posts in id order.
- `post_to_json` has `posted_at` and `old_clock_time`, for both an old post and a new one.
- The log line, with a fixed `now`, starts with `2026-10-02T07:42:10Z  `.

**`RealServerTest`**
- `POST /posts` answers 201 with `posted_at` matching `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$` and
  `old_clock_time` null. `GET /posts?after=0` gives the same value.

**`JourneyTest`**
- Start the real server on a database file made in the old format, with an old post at `15:42`.
  1. `GET /posts` shows it with `posted_at: null` and `old_clock_time: "15:42"`. Check the row with
     SQL.
  2. Sign up and post with `"posted_at": "1999-01-01T00:00:00Z"` in the JSON, while
     `server.utc_now` is patched to a fixed time. The answer, and the row read with SQL, both have
     the server's fixed time, not 1999.
  3. `GET /posts?after=<old id>` returns only the new post. `after` is still an id.

**`PageAndServerAgreeTest`**
- The page reads every time key the server sends: `post.posted_at` and `post.old_clock_time` both
  appear in `app.js`.
- The page never shows the raw text: `textContent = post.posted_at` is not in `app.js`.
- The page makes a `<time>` with a `datetime` attribute (`createElement("time")` and
  `"datetime"`), and refreshes it (`setInterval(refreshTimes`).
- The page never sends a time: no `posted_at:` key inside a `JSON.stringify` call.

## 7. Docs to update

- `DESIGN.md`:
  - in the `posts` table, the `posted_at` row becomes "text, ISO 8601 UTC, NULL only for posts from
    before timestamps", and add an `old_clock_time` row;
  - update the example rows;
  - add a new section, **Times**, which explains UTC on the server, local time on the page, the ids
    used for order, and the old posts with no date.
- `AGENTS.md`:
  - add `utc_now` and `utc_text` to the model's list;
  - add one sentence: "A time is saved as UTC text by `utc_text`, and shown by `timeElement` in
    `app.js`."
- `README.md`:
  - the post line becomes `id|author_id|text|posted_at|old_clock_time`;
  - the log-line example shows the UTC time.

## 8. Not in this plan

- The `page-only/` version (its `HH:MM` stays as it is).
- A choice of time zone in settings.
- Correcting the reader's clock using the server's `Date` header (a "just now" for times in the future
  is enough).
- Times for likes and sessions.
- Ordering or paging by time.
- Showing times in Japanese words beyond what `Intl` gives (`japanese`).

## 9. Size

**M**, about 300 lines:

| Part | Lines (about) |
|---|---|
| `server.py` | 70, most of it the upgrade |
| `app.js` | 70 |
| CSS | 8 |
| tests | 130 |
| docs | 25 |

## Changes made at approval (orchestrator)

- Decisions 1, 2, 3 and 5 approved as recommended.
- **Decision 4 (owner):** the full local date is in the hover tooltip of `<time datetime>` only.
  Nothing extra for phones.
- `groundwork` already gave `posts.id` `AUTOINCREMENT` and provides `rebuild_table`. Use
  `rebuild_table` for this plan's change to `posts`, so columns added by other plans are kept.
  The new column goes into `insert_post`'s list, and the time goes in the `head` slot.
- Build this first in step 3, before `place`, `replies`, `pictures`, `report` and `edit-delete`.
