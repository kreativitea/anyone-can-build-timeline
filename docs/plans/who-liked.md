Status: merged

# Who liked

## 1. What it does

Under every post that has likes, one line says who liked it: *Anika, Chika, and 10 others liked this
post*. The two names are the two most **popular** people who liked it: the people whose own posts
have received the most likes. If you liked the post yourself, you always come first, as *You*: *You,
Anika, and 10 others liked this post*. Click the line (or the number next to the heart), and the full
list opens under it: everyone who liked the post, A to Z, each with display name (*Aiko Tanaka*) and
account name (`@aiko`), at most 50. Anyone can see the line and the list, signed in or not, just as
anyone can read the timeline.

The line, by number of likes:

| Likes | Line |
|---|---|
| 0 | no line |
| 1 | *Anika liked this post* |
| 2 | *Anika and Chika liked this post* |
| 3 | *Anika, Chika, and 1 other liked this post* |
| 12 | *Anika, Chika, and 10 others liked this post* |
| 12, and you are one | *You, Anika, and 10 others liked this post* |

**No database change is needed.** This is the payoff of how likes were built. The `likes` table
keeps one row for each person who liked each post, and the count is counted from those rows. If the
app had kept only a number (`like_count = 3`), the names would be lost, and this feature would need
a new table and could never show who liked a post before today. Because each like is a row that
points at a user, the names are already there, and so is each person's popularity: we only have to
read them.

## 2. Decisions (made by the owner)

**2.1 Who may see the line and the list? Decided: everyone, signed in or not.** Reading is open to
everyone in this app (see `accounts.md`), and the names are already public: each one is shown on that
person's own posts. Signed-in only would hide nothing from anyone who makes an account in ten seconds.
Author-only would need an author check and a second answer for "you may not see this", for little
gain. A like is a public act, and the page does not hint otherwise.

**2.2 The order of the full list? Decided: A to Z by account name, ignoring capital letters.**
- Newest first was rejected for now. It needs the time of each like, and `likes` has no time column:
  that means an upgrade, `upgrade_to_who_liked`, adding `liked_at`. Every like from before it would
  have no time, and it would touch time while the `timestamps` plan is changing how time is saved.
- SQLite's hidden `rowid` (a number every row gets, which grows as rows are added) was rejected:
  the SQLite manual says `VACUUM` (the command that tidies the file) may change the rowids of a table
  with no `INTEGER PRIMARY KEY`, and `likes` has none. An order a tidy-up can scramble is not an order.
- A to Z needs no database change, is the same every time (easy to test), and is easy to scan.

**2.3 A limit for a very popular post? Decided: at most 50 names in the full list** (`MAX_LIKERS =
50`), plus the total, so the list can end with "and 120 more". Paging is not in this plan.

**2.4 Does an open list update by itself? Decided: only when that post's count changes** (or when
your own like on it changes). The page already gets every count each second from `GET /likes`, so this
costs no new request while nothing changes. The one case it misses: in the same second, one person
takes a like back and another likes, so the count stays the same. The list is then out of date until
the count changes again or the list is opened again. That is rare and harmless.

**2.5 The summary line. Decided: under every post with likes, the two most popular likers by name,
then "and N others".** The cases are in the table in section 1.

**2.6 What "popular" means. Decided: how many likes that person's own posts have received in total,
not counting their likes on their own posts.** It is counted from the rows in `likes` at the moment of
asking. It is **never kept as a number anywhere**, the same rule as like counts: a stored number could
drift away from the rows; a count of the rows cannot. Ties are broken A to Z by account name,
ignoring capital letters.

*Why not "how many posts they wrote"?* Posting a lot is not popularity. Someone who posts 500 times
that nobody likes would come first, ahead of someone whose one post 40 people liked. Likes received
measure what *other people* thought of their posts. *Why not count likes on your own posts?* For the
same reason: liking yourself is not other people liking you, and it would let anyone raise their own
place with a click on each of their posts.

**2.7 You first. Decided:** if the signed-in viewer liked the post, they are always the first name,
shown as *You*, and then one leader (the most popular other person). So the line still has at most two
names. A window that is not signed in never sees *You*.

**2.8 How the page asks. Decided: no new polling, and no change to `GET /likes`.** When the page sees
a post's count change (or whether you liked it change), it asks for the summaries of **all** changed
posts in **one** request, `GET /likesummary?post_ids=3,7,9`. When the page opens, the first answer
from `GET /likes` makes every post with likes "changed", so one request covers them all. One request
may name at most **100** posts (`MAX_SUMMARY_POSTS = 100`). If more posts changed, the page splits
them into groups of 100 and sends one request per group, one after the other. (A new route, not a
second shape of `/likers`: see section 3.)

**2.9 What can be clicked. Decided by the planner:** the **whole line** is one button, so clicking
*10 others* (or any part of the line) opens the list. The line is not split into a sentence plus a
separate *10 others* link, because one sentence must be one entry in the words table (the `japanese`
contract, rule 7): Japanese puts the words in a different order, so a sentence built from pieces
cannot be translated. The number next to the heart opens the same list.

## 3. Design

This plan is written after `japanese` Part A: refusals are **codes** in `PROBLEMS`, and every word
the page shows is a key in `words.js` (see `japanese.md`, section 3.4). If Part A has not landed
when this is built, the same words must move there when it does.

### Database

No change. No upgrade function. Everything is read from `likes`, `posts` and `users`.

### Model (`server.py`, MODEL part)

New constants, next to the others:

```python
MAX_LIKERS = 50          # at most this many names in the full list; the total is sent too
SUMMARY_NAMES = 2        # names in the summary line ("Anika, Chika, and 10 others")
MAX_SUMMARY_POSTS = 100  # at most this many posts in one GET /likesummary
```

New codes in `PROBLEMS`, at the end, under `# who-liked`:

| Code | English |
|---|---|
| `post_ids_missing` | The request must say which posts it is about. |
| `post_ids_too_many` | One request may ask about at most {limit} posts. |

**`who_liked(db_path, post_id)` → `(rows, like_count)`** — the full list.

1. `post_id = check_post_id(post_id)` (raises `like_post_id_missing`; no change to `check_post_id`).
2. If no post has this id: `RuleBroken("post_missing")`, the same code as `add_like`.
3. The names and the count, in one read transaction, so both come from the same moment:

   ```sql
   SELECT users.name, users.display_name
   FROM likes JOIN users ON users.id = likes.user_id
   WHERE likes.post_id = ?
   ORDER BY users.name COLLATE NOCASE
   LIMIT ?
   ```
   with `(post_id, MAX_LIKERS)`. Then `like_count_for(connection, post_id)` (already there, no change).

**`check_post_ids(text)` → a list of whole numbers** — the rule for the `post_ids` query word.
The text is split on commas. Empty, or any piece that is not a whole number: `post_ids_missing`.
More than `MAX_SUMMARY_POSTS` different ids: `post_ids_too_many` with `limit`. The same id twice
counts once.

**`like_summaries(db_path, viewer_id, post_ids)` → `{post_id: {"like_count", "you", "leaders"}}`** —
the summary lines. `viewer_id` is `None` for a window that is not signed in. Every asked id gets an
entry; a post that does not exist (or was deleted) simply has count 0 and no names, which gives away
nothing.

All three reads are in one read transaction. `marks` is `", ".join("?" * len(post_ids))`, built from
the **number** of ids only; the ids themselves are always passed as values, never written into SQL.

1. The leaders, with popularity counted in one query:

   ```sql
   SELECT post_id, name, display_name FROM (
     SELECT likes.post_id, users.name, users.display_name,
            ROW_NUMBER() OVER (
              PARTITION BY likes.post_id
              ORDER BY
                -- popularity: likes on this person's own posts, by other people
                (SELECT COUNT(*) FROM likes AS got
                 JOIN posts AS theirs ON theirs.id = got.post_id
                 WHERE theirs.author_id = users.id
                   AND got.user_id != users.id) DESC,
                users.name COLLATE NOCASE
            ) AS place
     FROM likes JOIN users ON users.id = likes.user_id
     WHERE likes.post_id IN ({marks})
       AND likes.user_id IS NOT ?          -- the viewer is "You", not a leader
   )
   WHERE place <= ?
   ORDER BY post_id, place
   ```

   with `(*post_ids, viewer_id, SUMMARY_NAMES)`. `IS NOT ?` with `None` leaves everyone in.
   `ROW_NUMBER() OVER (PARTITION BY …)` numbers the likers of each post 1, 2, 3… in popularity order,
   so `place <= 2` keeps the top two of every post in one query. (This needs SQLite 3.25 or newer,
   from 2018. Every Python 3.9 from python.org has a newer one; a test checks it, so an old one fails
   with a clear message instead of a strange error.)
2. The counts: `SELECT post_id, COUNT(*) AS like_count FROM likes WHERE post_id IN ({marks}) GROUP BY
   post_id`.
3. If `viewer_id` is not `None`: `SELECT post_id FROM likes WHERE user_id = ? AND post_id IN ({marks})`.
4. In Python: for a post the viewer liked, `you` is true and only the first `SUMMARY_NAMES - 1`
   leaders are kept (decision 2.7). So **the model decides who is named**; the page only words it.

Rules for `who_liked` and `like_summaries`, written in their docstrings:
- **They only read.** They never insert, update or delete, and never commit. They never make a user
  or a session. (`user_id_for` is gone since accounts, and must not come back.)
- **They name their columns.** `users.name, users.display_name`, never `users.*`, so the password
  salt and hash can never reach an answer by accident.
- Popularity is counted from rows every time. Never add a `popularity` or `likes_received` column.
- They read the constants when they run (not as default arguments), so a test can lower them.
- An old user from before accounts, never claimed, still shows if they liked something, with their
  old name as display name, the same as their posts.
- **`block`** will later leave people the viewer has blocked out of both the list and the leaders:
  one more `AND likes.user_id NOT IN (SELECT …)` in each query, using `viewer_id`. That is why
  `like_summaries` already takes `viewer_id`. See section 5.

### Routes (`server.py`, CONTROLLER part)

| Request | In | Answer |
|---|---|---|
| `GET /likers?post_id=7` | `post_id` | `200` `{"post_id": 7, "like_count": 3, "likers": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}, …]}` |
| | missing or not a number | `400`, code `like_post_id_missing` |
| | no such post | `400`, code `post_missing` |
| `GET /likesummary?post_ids=3,7,9` | `post_ids`; the cookie, if any | `200` `{"summaries": {"7": {"like_count": 12, "you": true, "leaders": [{"account_name": "anika", "display_name": "Anika"}]}, …}}` |
| | missing, empty, or not numbers | `400`, code `post_ids_missing` |
| | more than 100 ids | `400`, code `post_ids_too_many`, `limit: 100` |

"Likers" means "the people who liked". Why these paths:

- **Not `GET /likes?post_id=7`.** `GET /likes` already answers "all the counts, and mine", every
  second. One path that gives different shapes, chosen by a query word, is a trap. The same reason
  keeps the summaries off `/likers`: a new path, a new answer.
- **Not `GET /posts/7/likes`.** Every route here is a fixed path plus a query string
  (`/posts?after=3`); the controller compares `url.path` with `==`. And `PageAndServerAgreeTest`
  reads routes with `fetch\("(/[a-z]*)`, which would see `fetch("/posts/" + id + "/likes")` as just
  `/posts` and miss the new route. `/likers` and `/likesummary` are letters only, so the test sees
  both, and they must be added on both sides.

In `do_GET`, two new branches (the only change to shared routing):

```python
elif url.path == "/likers":
    self.show_likers(parse_qs(url.query).get("post_id", [None])[0])
elif url.path == "/likesummary":
    self.show_like_summaries(parse_qs(url.query).get("post_ids", [""])[0])
```

New methods on `TimelineHandler`:
- `show_likers(self, post_id)`: calls `who_liked`; 200 with `likers_to_json`, or the problem with 400.
  It does not read the cookie.
- `show_like_summaries(self, post_ids)`: `user = self.user_or_none()`, calls
  `like_summaries(db_path, user["id"] if user else None, post_ids)`; 200 with `summaries_to_json`, or
  the problem with 400. It passes the text to the model as it is: splitting and checking it is the
  model's rule (`check_post_ids`).

Neither checks a rule or opens the database. `log_message` is not changed: both requests are made
only when something changed, not every second.

### View (`server.py`, VIEW part)

```python
def likers_to_json(post_id, rows, like_count):
    return {"post_id": post_id, "like_count": like_count,
            "likers": [account_to_json(row) for row in rows]}

def summaries_to_json(summaries):
    """A JSON name is always text, so the post ids are text too, as in likes_to_json."""
    return {"summaries": {str(post_id): {"like_count": s["like_count"], "you": s["you"],
                                         "leaders": [account_to_json(r) for r in s["leaders"]]}
                          for post_id, s in summaries.items()}}
```

Both reuse `account_to_json` (no change to it), so every person has the same two keys as "Signed in
as": `account_name` and `display_name`. Nothing else about a user is ever in an answer.

### Words (`with-backend/words.js`, at the end of `WORDS`, under `// who-liked`)

The two codes above, with the same English, plus:

| Key | English |
|---|---|
| `liked_you` | You |
| `liked_by_one` | {first} liked this post |
| `liked_by_two` | {first} and {second} liked this post |
| `liked_by_two_and_others_one` | {first}, {second}, and {count} other liked this post |
| `liked_by_two_and_others_other` | {first}, {second}, and {count} others liked this post |
| `liked_by_one_and_others_one` | {first} and {count} other liked this post |
| `liked_by_one_and_others_other` | {first} and {count} others liked this post |
| `liked_by_others_one` | {count} person liked this post |
| `liked_by_others_other` | {count} people liked this post |
| `likers_none` | No likes yet. |
| `likers_more_one` · `likers_more_other` | and {count} more |
| `likers_show` | Show who liked this post (`aria-label` of the count and the line) |

The last four `liked_by_…` keys look unused today: with no `block`, a post with two or more likes
always has two names. They are there for `block`, which can leave names out, so the page never builds
a sentence by hand. Names go in as `{first}`/`{second}` values, filled by `fill()`, which never reads
a value as a template.

### Page (`with-backend/app.js`, `style.css`)

`index.html`: no change. Everything is built in `showPost`.

`app.js`, a new block under `// who-liked`:

- New constant `MAX_SUMMARY_POSTS = 100`, the same as the model.
- **`showPost` (change, small):** the count becomes a `<button type="button" class="like-count">`
  instead of a `<span>`. After the like row, two new elements: a hidden
  `<button type="button" class="like-summary">` (the line) and a hidden
  `<ul class="likers" id="likers-<id>">` (the full list). Both buttons carry `dataset.postId`,
  `aria-expanded="false"`, `aria-controls="likers-<id>"` and `aria-label` from `say("likers_show")`.
  `likeParts[post.id]` gets `summary`, `list`, and `summaryFor` (the count and "you" the line was
  last made for; empty at first). About 12 lines change.
- **`showLike` (change, 3 lines):** if `count` or `liked` differs from `parts.summaryFor`, call
  `wantSummary(postId)`. This one place covers the page opening, another window's like, and this
  window's own press. `checkForNewPosts` and `pressHeart` are **not** changed.
- **`clickOnTimeline` (change, 3 lines):** a click on `.like-count` or `.like-summary` calls
  `toggleLikers(postId)`.
- **`wantSummary(postId)` (add):** adds the id to a `Set`, and if none is queued, queues
  `askForSummaries` with `setTimeout(…, 0)`. Every `showLike` in one pass of the loop runs before it,
  so all the changed posts of one second go in one request.
- **`askForSummaries()` (add):** takes the ids out of the set, in groups of `MAX_SUMMARY_POSTS`, and
  for each group: `fetch("/likesummary?post_ids=" + ids.join(","))`, then `showSummary` for each
  answer, and if that post's list is open, `showLikers(postId)` again (decision 2.4). If a request
  fails, its ids get an empty `summaryFor`, so the next second asks again.
- **`showSummary(postId, summary)` (add):** `names` is `say("liked_you")` if `summary.you`, then the
  leaders' `display_name`s. `others = Math.max(0, summary.like_count - names.length)`. No likes:
  hide the line. Otherwise pick the key by `names.length` (0, 1 or 2) and whether `others` is 0, and
  use `say` or `sayCount(key, others, {first, second, count})`. The line gets the result with
  **`textContent`**. Then `summaryFor` is set.
- **`toggleLikers(postId)` (add):** open or close the list; set `aria-expanded` on both buttons.
  Opening calls `showLikers`.
- **`showLikers(postId)` (add):** `fetch("/likers?post_id=" + postId)`, then `buildLikers`. On a 400,
  `showProblem(answer)`. On a network error, `showStatus("cannot_reach")`.
- **`buildLikers(list, answer)` (add):** empties the list and builds one `<li>` per person, with a
  `.post-author` span (display name) and a `.post-handle` span (`"@" + account_name`), the same
  classes as a post. **Only `textContent`, never `innerHTML`**: a display name is text a stranger
  typed. No likes: one `<li>`, `say("likers_none")`. More than shown: a last `<li>`,
  `sayCount("likers_more", like_count - likers.length)`.

No page-side rule for the ids is needed beyond the cap: the page sends only ids it got from the
server, never more than 100 at once, and the server checks both anyway.

`style.css` (and its copy `page-only/style.css`): new rules at the end, under `/* who-liked */`:
`.like-count` and `.like-summary` as buttons that look like text (no border, no background, underline
on hover and focus); `.like-summary` quiet and small, on its own line, long display names wrapping
(`overflow-wrap: anywhere`); `.likers` small, no bullets, indented under the heart. About 30 lines.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | `MAX_LIKERS`, `SUMMARY_NAMES`, `MAX_SUMMARY_POSTS` constants (MODEL) | add |
| `with-backend/server.py` | `PROBLEMS`: `post_ids_missing`, `post_ids_too_many` under `# who-liked` | add |
| `with-backend/server.py` | `who_liked`, `check_post_ids`, `like_summaries` (MODEL) | add |
| `with-backend/server.py` | `likers_to_json`, `summaries_to_json` (VIEW) | add |
| `with-backend/server.py` | `TimelineHandler.show_likers`, `TimelineHandler.show_like_summaries` (CONTROLLER) | add |
| `with-backend/server.py` | `TimelineHandler.do_GET`: two branches, `/likers` and `/likesummary` | change |
| `with-backend/words.js` | `// who-liked` block at the end of `WORDS` (2 codes, 13 keys) | add |
| `with-backend/app.js` | `showPost`: count becomes a button; hidden summary line and list | change |
| `with-backend/app.js` | `showLike`: call `wantSummary` when count or "you" changed | change |
| `with-backend/app.js` | `clickOnTimeline`: one branch for `.like-count` / `.like-summary` | change |
| `with-backend/app.js` | `MAX_SUMMARY_POSTS`, `wantSummary`, `askForSummaries`, `showSummary`, `toggleLikers`, `showLikers`, `buildLikers` | add |
| `with-backend/style.css` | new section at the end, `/* who-liked */` | add |
| `page-only/style.css` | the same section (the copy must stay the same) | add |
| `with-backend/test_server.py` | new test methods at the end of `ModelTests`, `RealServerTest`, `JourneyTest`, `PageAndServerAgreeTest` | add |
| `with-backend/test_server.py` | `PageAndServerAgreeTest`: the route set gains `"/likers"` and `"/likesummary"` | change |
| `AGENTS.md` | model and view lists gain the new functions; one sentence on popularity | change (a few lines) |
| `DESIGN.md` | new section "Who liked a post" | add |

Not touched: the database, any upgrade function, `GET /likes`, `likes_for`, `likes_to_json`,
`POSTS_WITH_AUTHORS`, `post_to_json`, `check_post_id`, `like_count_for`, `account_to_json`,
`checkForNewPosts`, `pressHeart`, `keepChecking`, `log_message`, `index.html`, `page-only/app.js`,
`page-only/index.html`.

## 5. Depends on, and collides with

**Depends on `accounts`** (`users.display_name`, `user_or_none`, and `user_id_for` gone) and on
**`japanese` Part A** (`PROBLEMS`, `words.js`, `say`, `sayCount`, `showProblem`). Part A is built
right after `accounts`, so this is no wait in practice. If it is not there yet, this plan's words are
written as plain English first, and moved into `words.js` when Part A lands.

**Collides with** (small, mostly the same lines):
- **Every plan that adds a route** (`search`, `bookmarks`, `block`, `report`, `replies`,
  `edit-delete`, `pictures`, `timeline-flow`…): each adds `elif`s to `do_GET` and paths to the route
  set in `PageAndServerAgreeTest`. One-line conflicts, easy to rebase.
- **Every plan that changes `showPost` or `showLike`** (`timestamps`, `replies`, `links-and-tags`,
  `pictures`, `edit-delete`, `timeline-flow`, `block`, `report`, `japanese`): this plan changes the
  like-row lines and adds after them, not the author, time or text lines. Merge in any order.
- **`block`:** people the viewer has blocked are left out of the leaders and of the full list, for
  that viewer. Both model functions take the viewer already (`who_liked` will need `viewer_id` added
  then; `show_likers` will read the cookie with `user_or_none`). The extra `liked_by_one_and_others`
  and `liked_by_others` keys are ready for the lines this produces. If `block` also takes blocked
  people out of the counts (its decision 2), `like_summaries`' count query must do the same, or the
  line will say "and 3 others" when the heart says 2. Whichever merges second owns the filter.
- **`report`:** a hidden post shows no likers and no summary. Whichever merges second adds the check.
- **`edit-delete`:** a deleted post's likes go with it, so `who_liked` says "does not exist" and
  `like_summaries` gives count 0. Nothing to do; its tests should cover it if it merges second.
- **`japanese`:** this plan adds its block at the end of `PROBLEMS` and `WORDS`; Part B writes the
  `ja:` lines. The line is one key per sentence, so Japanese can put *You* and the names wherever its
  grammar needs.
- **`dark-mode`:** both add a section at the end of both `style.css` files. Keep both sections.
- **`timestamps`:** none, because no time is added to `likes` (decision 2.2).
- **`timeline-flow`:** older posts loaded on scroll come through `showPost`/`showLike`, so they get
  their lines through `wantSummary` with no extra work.

## 6. Tests

All new methods go at the end of their class. Accounts are made straight with SQL where many are
needed, or with `MAX_…` lowered for the test (put back in `finally`), so no test hashes dozens of
passwords 600,000 times each.

**`ModelTests`**
- *Full list (`who_liked`):* nobody liked → no names, count 0. Two likes → both, A to Z ignoring
  capitals (`@ben` before `@Chika`). A like taken back → that person is gone. Missing / `"seven"` /
  `None` → `like_post_id_missing`; no such post → `post_missing`. `MAX_LIKERS` lowered to 2 → three
  likes give two names and a count of 3. An old, unclaimed user's like is listed.
- *Popularity:* Chika's posts have 3 likes from others, Anika's 1, Ben's 0. All three like post P →
  leaders of P are Chika, then Anika.
- *Posting a lot is not popularity:* Ben writes 10 posts nobody likes; Anika writes 1 that one person
  likes → Anika ranks above Ben.
- *Liking yourself is not popularity:* Ben likes his own 5 posts → his popularity is still 0.
- *Ties:* equal popularity → A to Z by account name, ignoring capitals.
- *Counted from rows, never stored:* after a like on Chika's post is taken back, the order changes
  at the next ask. And no table gains a column (`PRAGMA table_info` of `users`, `posts`, `likes` is the
  same before and after).
- *You first:* the viewer liked P → `you` is true and there is one leader, not the viewer. The viewer
  did not → `you` false and two leaders. `viewer_id` `None` → `you` false.
- *Counts:* each `like_count` equals `COUNT(*)` from `likes`. An id with no post → count 0, no names.
- *`check_post_ids`:* `""`, `"a,b"`, `"1,,2"` → `post_ids_missing`; 101 ids → `post_ids_too_many`
  with `limit` 100; exactly 100 is fine; `"7,7"` is one id.
- **Asking adds nothing:** for both functions, the number of rows in `users`, `posts`, `likes` and
  `sessions` is the same before and after, including for posts that do not exist.
- Every person in `likers_to_json` and `summaries_to_json` has exactly the keys `account_name` and
  `display_name`, and no value is a password salt or hash.
- `sqlite3.sqlite_version_info >= (3, 25, 0)`, with a message that says window functions are needed.

**`RealServerTest`**
- `GET /likers?post_id=<id>` with no cookie: 200 and the names. No `post_id`, `abc`, no such post:
  400 with a code.
- `GET /likesummary?post_ids=<id>` with no cookie: `you` false. With the cookie of someone who liked
  it: `you` true and one leader. 101 ids: 400, `post_ids_too_many`. `post_ids=x`: 400.

**`JourneyTest`**: `test_the_whole_journey_of_who_liked`
1. Anika, Ben and Chika sign up. Chika posts twice, Anika once; Ben likes both of Chika's posts and
   Anika's (so Chika's popularity is 2, Anika's 1). Ben posts P.
2. No cookie: `/likesummary?post_ids=P` → count 0, no names. `/likers` → empty.
3. Anika and Chika like P. No cookie: leaders are Chika, then Anika. SQL: `select user_id from likes
   where post_id = P` agrees.
4. Ben likes P. With Ben's cookie: `you` true, one leader, Chika; count 3, the same as `GET /likes`.
   With no cookie: Chika and Anika, count 3.
5. Ben takes back his like on one of Chika's posts (Chika's popularity is now 1, a tie with Anika):
   no cookie → Anika, then Chika (A to Z).
6. `/likers?post_id=P` → Anika, Ben, Chika (A to Z); the SQL rows agree.
7. After every GET: `select count(*)` from `users`, `posts`, `likes` and `sessions` did not change
   because of it.

**`PageAndServerAgreeTest`**
- The route set gains `"/likers"` and `"/likesummary"` (the one changed line).
- New: the server answers `GET /likers?post_id=1` and `GET /likesummary?post_ids=1` with something
  other than 404 or 501.
- New: `MAX_SUMMARY_POSTS` in `app.js` equals the model's.
- New: the page reads the keys the view writes: `app.js` contains `.likers`, `.summaries`,
  `.leaders`, `.you`, `.account_name`, `.display_name` and `.like_count`, and each is a key in an
  answer from `likers_to_json` or `summaries_to_json`.
- New: `app.js` does not contain `innerHTML`.
- The `japanese` tests already check that every key `app.js` uses is in `words.js`, and that the two
  new codes have the same English in `PROBLEMS` and `words.js`.

## 7. Docs to update

- `AGENTS.md`: add `who_liked`, `check_post_ids`, `like_summaries` to the model list and
  `likers_to_json`, `summaries_to_json` to the view list; in the `app.js` row, add "shows who liked
  each post, and asks for the names only when a count changes". Add: "`who_liked` and
  `like_summaries` only read: they must never add a user, a like or a session. Popularity is counted
  from `likes`, never stored."
- `DESIGN.md`: a new section, "Who liked a post": the two routes and their answers, why new paths and
  not a second shape of `/likes`, the A-to-Z order and why not `rowid`, the limits, what "popular"
  means and why not number of posts, *You* first, how the page asks only on change, and the sentence
  that this needed no database change because a like is a row, not a number.
- `README.md`: one line in the feature list, if it has one.

## 8. Not in this plan

- The time of each like, and "newest first" (decision 2.2; its own later plan).
- Seeing more than 50 names (paging).
- A notification when someone likes your post.
- Private likes, or hiding your own likes from the list.
- A page of "every post I liked", or a "most popular people" page.
- Any change to `page-only/` except the copied CSS.

## 9. Size

**M.** About 520 lines in all: `server.py` about 110, `app.js` about 120, `words.js` about 30,
CSS about 30 (twice), tests about 220, docs about 40.
