Status: merged

# Place

## 1. What it does

When you write a post, you can also say where you are, for example "Osaka". It is optional: you
can leave it empty. Everyone then sees it after the time of your post: *Aiko Tanaka @aiko 15:42 ·
Osaka*. The page remembers the last place you typed in this browser, so you do not type it again
every time.

## 2. Decisions for the owner

**1. Does the person type the place, or does the browser find it?**

- **(a) Typed.** A small optional box under the post box. The person writes any short words:
  "Osaka", "Kansai Gaidai", "home", or nothing. They decide how much to say.
- **(b) Geolocation.** *Geolocation* is the browser's way to find where the device is. The browser
  first asks "Allow this site to know your location?". If the person says yes, the page gets a
  *latitude and longitude*: two numbers that point at one spot on Earth, often to within a few
  metres. Three problems:
  - It is **precise and private**. A post written at home would show, to everyone, where that
    person lives. Saving it in `timeline.db` means keeping a record of where real people were.
    That is a privacy decision, and it cannot be taken back after it is shared.
  - Two numbers mean nothing to a reader. Turning them into a town name ("Osaka") needs an
    *outside service* (a website run by someone else, called *reverse geocoding*). This project
    may not use one: it needs only `python3`, and sending people's locations to another company
    is a second privacy problem.
  - Rounding the numbers (to about 1 km) helps a little, but it still says "near here", and it
    still shows only numbers.

**Recommendation: (a) typed.** It is simple, it needs no permission, nothing outside the project,
and the person chooses exactly what to share. A typed place can be untrue; that is fine. It is a
label the writer chose, not a proof of where they were. The rest of this plan assumes (a).

**2. How long may a place be?**

- 40 characters (the same as an account name), 60, or 100.

**Recommendation: 40.** Enough for "Higashiosaka, Osaka Prefecture" (30). A place is a label, not a
second post.

**3. Should the page remember the last place typed?**

- **(a) No.** The box is empty for every post.
- **(b) Yes, in this browser**, with `localStorage`. *localStorage* is a small store that the
  browser keeps for one website, on this device only. It stays after the tab and the browser close.
  The server never sees it.
- **(c) Yes, on the server**, in a new column on `users`.

**Recommendation: (b), and forget it when the person logs out.** People usually post from the same
place many times, so (a) is tiring. (c) would keep "where this person usually is" on the server,
for every user, which is the kind of record decision 1 avoids. With (b) the place stays on the
person's own device. The page forgets it on **Log out**, so the next person on a shared computer
(a library, a classroom) does not see it. The box always shows the remembered place before Post is
pressed, so nobody shares a place without seeing it.

## 3. Design

### Why a column on `posts`, not on `users`

A place belongs to **one post**: the same person writes in Osaka today and in Kyoto tomorrow. If the
place were kept on `users`, it would be one value per person, so changing it would change the place
on **every old post** too, the way a new display name shows on old posts. That is right for a name,
and wrong for a place. And a `users.place` column would be a record of where each person is now,
which decision 1 avoids. So the place is a detail of the post, saved with the post, in `posts`.

### Database: `upgrade_to_place(connection)`

Written like `upgrade_to_accounts`. The orchestrator gives it its `user_version` number; below it is
written `<N>`.

```python
def upgrade_to_place(connection):
    """Version <N>: each post can say where it was written. Every old post is kept.

    An old post has no place: its place is NULL. A new post with no place is NULL too,
    so there is only one way to say "no place".
    """
    connection.execute("BEGIN")
    # The database refuses an empty place and a place that is too long, even if the
    # rule in check_place is got around. NULL passes the CHECK, so old posts pass.
    connection.execute("ALTER TABLE posts ADD COLUMN place TEXT "
                       "CHECK (place IS NULL OR length(place) BETWEEN 1 AND 40)")
    connection.execute("PRAGMA user_version = <N>")
    connection.commit()
```

In `create_tables`, one new line after the other upgrades:
`if version < <N>: upgrade_to_place(connection)`.

`length()` in SQLite counts characters, as `len()` does in Python, so the two limits agree. The
hidden-character rule cannot be written as a simple `CHECK`, so only the model checks it.

| `posts` (new column) | |
|---|---|
| `place` | text or NULL. NULL means "no place". Never `''`. At most 40 characters. |

### Model

New constant and new function, next to `check_display_name`:

```python
MAX_PLACE = 40

def check_place(place):
    """Return the place without extra spaces, or None if there is no place. Or raise RuleBroken."""
    place = place.strip() if isinstance(place, str) else ""
    if place == "":
        return None
    if len(place) > MAX_PLACE:
        raise RuleBroken(f"The place must be {MAX_PLACE} characters or fewer.")
    if HIDDEN_CHARACTERS.search(place):
        raise RuleBroken("The place must not have hidden characters or line breaks.")
    return place
```

It reuses `HIDDEN_CHARACTERS` (line breaks, control characters, and the invisible marks that turn
text around), exactly as `check_display_name` does. A place is shown on one line next to a name, and
it is printed in the terminal, so it must not be able to fake a second line or look like a name.
A place that is not text (a number, a list) counts as no place, the same as `check_display_name`.

`check_text` is **not changed**.

`save_post` gains one keyword argument with a default, so every other call (and every other plan's
call) still works without it:

```python
def save_post(db_path, user_id, text, place=None):
    text = check_text(text)
    place = check_place(place)
    ...
        "INSERT INTO posts (author_id, text, posted_at, place) VALUES (?, ?, ?, ?)",
        (user_id, text, time.strftime("%H:%M"), place))
```

`POSTS_WITH_AUTHORS` gains one column: `posts.place,` after `posts.posted_at,`.

### Controller

`take_post` changes one line: `save_post(..., data.get("text"), data.get("place"))`. No new route.
The controller checks nothing; `save_post` does.

### Routes

No new route. `POST /posts` accepts one more optional key:

| Request | JSON in | Answer |
|---|---|---|
| `POST /posts` | `text`, `place` (optional) | 201 and the post with `place`; 400 if the place breaks a rule; 401 if not logged in |
| `GET /posts?after=` | — | each post now has `"place"`: text, or `null` |

### View

- `post_to_json` gains one key: `"place": row["place"]` (text or `null`; the view decides nothing).
- `post_to_log_line` adds the place only when there is one:
  `15:42  Aiko Tanaka @aiko: "the library is open late" · Osaka`. A post with no place prints the
  same line as today. The place can hold no line break (the rule), so it cannot fake a line.

### Page (`with-backend/`)

- `index.html`: inside `#post-form`, between the `<textarea>` and `.post-row`, one optional box:
  `<label for="place">Where are you? (optional)</label>`
  `<input id="place" type="text" autocomplete="off" placeholder="Osaka">`.
- `app.js`:
  - `const MAX_PLACE = 40;` next to the other limits, and `const placeBox = …`.
  - New `placeProblem(place)`: the same rules and the same words as `check_place`, using the
    `HIDDEN_CHARACTERS` the page already has.
  - New `placePart(post)`: returns a `<span class="post-place">` with `"· " + post.place`
    (`textContent`, never `innerHTML`), or `null` when `post.place` is empty.
  - `showPost`: **one small change**: after `time`, add `const place = placePart(post);` and put
    it after `time` in `item.append(...)` only when it is not `null`.
  - `sendPost`: checks `placeProblem(placeBox.value.trim())`, sends
    `{ text: text, place: placeBox.value }`, and after a 201 calls `rememberPlace(...)`. The place
    box is **not** emptied after a post: the same place is likely next time.
  - New `rememberPlace(place)`, `rememberedPlace()` and `forgetPlace()`: read and write
    `localStorage` under the key `timeline-place` (an empty place removes the key). Each is wrapped
    in `try … catch`, because some browsers (private windows) refuse `localStorage`; then the page
    simply does not remember.
  - At start: `placeBox.value = rememberedPlace();`. In `logOut`: `forgetPlace()` and empty the box.
- `style.css`: at the end, under `/* place */`: `.post-place` the same quiet colour as `.post-time`,
  and spacing for `#place`. Copied into `page-only/style.css`, which must stay the same file.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | `MAX_PLACE`, `check_place` | add |
| `with-backend/server.py` | `upgrade_to_place` | add |
| `with-backend/server.py` | `create_tables` (one `if version < <N>` line) | change |
| `with-backend/server.py` | `POSTS_WITH_AUTHORS` (one column) | change |
| `with-backend/server.py` | `save_post` (keyword `place=None`, one column in the `INSERT`) | change |
| `with-backend/server.py` | `TimelineHandler.take_post` (pass `data.get("place")`) | change |
| `with-backend/server.py` | `post_to_json` (one key) | change |
| `with-backend/server.py` | `post_to_log_line` (place at the end, if any) | change |
| `with-backend/app.js` | `MAX_PLACE`, `placeBox`, `placeProblem`, `placePart`, `rememberPlace`, `rememberedPlace`, `forgetPlace`, start-up line | add |
| `with-backend/app.js` | `showPost` (one line, and the `item.append` line) | change |
| `with-backend/app.js` | `sendPost` (check, body, remember) | change |
| `with-backend/app.js` | `logOut` (forget the place) | change |
| `with-backend/index.html` | `#post-form`: label and `#place` box | add |
| `with-backend/style.css`, `page-only/style.css` | `/* place */` at the end | add |
| `with-backend/test_server.py` | new methods at the end of each of the four classes | add |
| `AGENTS.md`, `DESIGN.md` | see section 7 | add |

## 5. Depends on, and collides with

- **Depends on `accounts`**: `save_post(db_path, user_id, …)`, `take_post`, `HIDDEN_CHARACTERS`,
  `upgrade_to_accounts` as the model for the upgrade, and `logOut` in the page.
- **Collides (same lines, small merges):**
  - `timestamps`: changes `posted_at` in `save_post`'s `INSERT`, `POSTS_WITH_AUTHORS`,
    `post_to_json`, `post_to_log_line`, and the time `<span>` in `showPost`. The place goes after
    the time, whatever the time says. Both add an upgrade function.
  - `edit-delete`, `replies`, `pictures`, `who-liked`, `block`, `report`: each touches some of
    `save_post`, `POSTS_WITH_AUTHORS`, `post_to_json`, `showPost`'s `item.append` line, or
    `create_tables`. Each adds one item; the merges are one line each.
  - `rate-limit`: may change `take_post` or `save_post`.
  - `edit-delete`: if a post can be edited, should its place be editable too? Not in this plan;
    that plan decides, and if yes it calls `check_place`.
  - `drafts`: keeps the half-written text. The place has its own `localStorage` key
    (`timeline-place`), so they do not share a key. Drafts need not save the place: it is
    already remembered.
  - `dark-mode`: also uses `localStorage`, with another key. No real collision.
  - `japanese`: the new label, placeholder and two error sentences need translating.
  - `search`: could later search places too. Not in either plan unless the owner asks.
  - `long-posts`: changes `MAX_TEXT` only. No collision.

## 6. Tests

**`ModelTests`** (new methods at the end):
- a post with no place is saved with `place` NULL; `""` and `"   "` are also NULL;
- `" Osaka "` is saved as `"Osaka"`;
- 40 characters is allowed, 41 is refused with the sentence above;
- a place with `\n`, with ` `, and with `‮` (the mark that turns text around) is refused,
  and no post is saved;
- a place that is not text counts as no place;
- the place is in `posts`, and `users` has no place column;
- the database itself refuses `''` and a 41-character place put in with plain SQL (the `CHECK`);
- the upgrade: a `timeline.db` at the version before keeps every post, old posts get `place` NULL,
  and starting the server twice changes nothing more;
- `post_to_log_line` ends with `· Osaka` when there is a place, and is the same as before when not.

**`RealServerTest`**: a logged-in `POST /posts` with `"place": "Osaka"` gets 201 and the answer has
`"place": "Osaka"`; `GET /posts` shows it; a place with a line break gets 400 and a reason; a post
with no `place` key still gets 201 with `"place": null`.

**`JourneyTest`**: one new test, `test_the_whole_journey_of_a_place`. Aiko signs up, posts with
`"place": "Osaka"`: `select place from posts` shows `Osaka`. She posts with no place: the row has
NULL. She sends a place with a line break: 400, and the number of rows in `posts` has not changed.
Ben's window reads `GET /posts` and sees both posts, one with a place and one with `null`.

**`PageAndServerAgreeTest`**:
- the page's `MAX_PLACE` (read from `app.js` with a regular expression) equals `server.MAX_PLACE`;
- the page sends `place: ` and shows `post.place`;
- the page's two place error sentences are the server's sentences.

## 7. Docs to update

- `AGENTS.md`: add `check_place` to the model's list of functions, and one sentence: "A place is a
  detail of one post, so it is a column on `posts`, never on `users`."
- `DESIGN.md`: a new short section after the data model, "Place": the `place` column, NULL for none,
  the `CHECK`, why it is on `posts`, and why it is typed and not found by geolocation.
- `README.md`: one line in what the app does, if it lists features.

## 8. Not in this plan

- Geolocation, a map, latitude and longitude, or turning numbers into town names.
- A list of places to choose from, or checking that a place is real.
- Changing the place of a post after it is written (`edit-delete` decides).
- Searching or filtering by place (`search` could add it later).
- Translating the new words (`japanese`).
- `page-only/` (a demo; only its `style.css` copy changes).

## 9. Size

**S.** About 170 lines: `server.py` about 35, `app.js` about 40, `index.html` 3, `style.css` about
8 in each copy, tests about 80, docs about 15.
