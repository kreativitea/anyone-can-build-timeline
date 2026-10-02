Status: built on branch pictures, awaiting merge

# Pictures

## 1. What it does

A signed-in person can attach one picture to a post: a PNG, JPEG, GIF or WebP file, up to 2 MB.
They also write a short description of the picture, for people who cannot see it. The picture
shows under the post's text, in every window. The server looks at the file's first bytes to check
it really is a picture; it never trusts the file's name or what the browser says it is.

## 2. Decisions for the owner

**2.1 How does the picture travel from the page to the server?**

The old way to send a file is a *multipart form* (a request body cut into parts, one per form
field). Python's `cgi` module read those, but it was removed in Python 3.13, and this Mac runs 3.14.

- **(a) Inside the JSON of `POST /posts`, as base64.** *Base64* writes any bytes as plain letters,
  so they fit in JSON. One request makes the post and its picture together. It goes through
  `read_json`, so it keeps the `Content-Type: application/json` protection with no new code. Cost:
  the request is about a third bigger than the file.
- **(b) Raw bytes to a route of their own,** `POST /pictures` with `Content-Type: image/png` (or
  jpeg, gif, webp), which answers with an id; then `POST /posts` sends that id. Smaller, but two
  requests: a picture can be uploaded and never used, and needs cleaning up later. It needs its own
  protection: it must refuse any `Content-Type` that is not one of the four image types (a form on
  another website can only send three plain types, never `image/png`).
- **(c) Read multipart by hand.** The page could send a normal `FormData`. But splitting the parts
  ourselves is about 60 lines of fiddly byte work, a common source of bugs, for no gain here.

**Recommendation: (a).** One request, one transaction, no orphan pictures, and the cross-site
protection that accounts already built covers it. A third more bytes does not matter at 2 MB.

**2.2 Where is the picture kept?**

- **(a) In the database, in a new `pictures` table, as a BLOB.** A *BLOB* is a column that holds
  raw bytes. Everything stays in `timeline.db`: the post and its picture are saved in one
  transaction, deleted together, and `make reset`, `.gitignore` and copying the app need no change.
  There is no file path anywhere, so *path traversal* (a request like `/pictures/../server.py`
  that tricks a server into reading a file it should not) cannot happen.
- **(b) As files in `with-backend/pictures/`,** each named by a random id (`secrets.token_hex(16)`
  plus `.png` etc.), with the name kept in the database. This is how big sites work (they use a
  separate file store). But now there are two places that can disagree: a file with no row, or a
  row with no file. It needs `pictures/` in `.gitignore`, `rm -rf with-backend/pictures` in
  `make reset`, and a test folder for the tests.

**Recommendation: (a).** SQLite handles pictures of this size well, and it keeps the project's rule
that one fact lives in one place. `DESIGN.md` said pictures need "a second kind of storage"; this
plan answers that a BLOB table is enough for an app this size, and says so in `DESIGN.md`. If the
owner chooses (b), section 3 lists what changes.

**2.3 How big may a picture be?** 1 MB, **2 MB**, or 5 MB.
**Recommendation: 2 MB.** A phone photo is often 2 to 5 MB, so some will be refused with a clear
message; a polling page loads every picture, so smaller is kinder. Resizing is not possible without
an image library (see section 8).

**2.4 Is a description (alt text) required?**
*Alt text* is the words a screen reader says instead of the picture.
- (a) **Required**, 1 to 200 characters. (b) Optional. (c) None.

**Recommendation: (a) required.** A picture with no description is invisible to a blind reader, and
an empty `alt` tells the screen reader to skip it. The same `HIDDEN_CHARACTERS` rule as display
names applies.

**2.5 May a post be only a picture, with no text?**
**Recommendation: no, text is still required.** `check_text` stays as it is, and every other plan
(search, links, replies) can keep assuming a post has text.

**2.6 Photos can hold the place they were taken.**
A JPEG from a phone often carries *EXIF* data (hidden notes inside the file), sometimes with GPS
location. This plan keeps the file exactly as sent.
- (a) **Keep it, and warn** in one line next to the file box.
- (b) Remove every EXIF block from a JPEG (about 25 lines). This also removes the note that says
  "turn this photo", so phone photos may show lying on their side.
- (c) Blank only the GPS entry inside the EXIF (about 60 lines of byte parsing).

**Recommendation: (a) now, and (c) as its own plan later.** (b) breaks phone photos; (c) is a
feature of its own. It matters most next to the `place` plan, where sharing a location is meant to
be a choice.

## 3. Design

### Database: `upgrade_to_pictures(connection)`

Written like `upgrade_to_accounts`: `BEGIN`, the statements, `PRAGMA user_version = <N>` (the
orchestrator picks N), `commit`. `create_tables` gains `if version < N: upgrade_to_pictures(connection)`.

```sql
CREATE TABLE pictures (
    post_id  INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    kind     TEXT NOT NULL CHECK (kind IN ('png', 'jpeg', 'gif', 'webp')),
    alt_text TEXT NOT NULL CHECK (length(alt_text) BETWEEN 1 AND 200),
    bytes    BLOB NOT NULL CHECK (length(bytes) BETWEEN 12 AND 2097152)
)
```

What the database enforces by itself, even if every check in the code is got around:

- `post_id` is the primary key, so **a post has at most one picture**.
- `REFERENCES posts(id)`: a picture always belongs to a real post. `ON DELETE CASCADE`: when the
  post's row is deleted, its picture row is deleted too (`connect` already turns foreign keys on).
- `kind` is one of four words, so the server can never be made to send another type.
- The size limit. The number is written out in the CHECK; a test checks it equals
  `MAX_PICTURE_BYTES`. Raising the limit later needs a new upgrade.

The picture is a table of its own, not a column on `posts`, so `posts` stays small and no query for
posts ever reads picture bytes by accident.

### Model

New constants:

```python
MAX_PICTURE_BYTES = 2 * 1024 * 1024
MAX_ALT_TEXT = 200
# The biggest request body the server will read: a 2 MB picture as base64,
# plus room for the text and the description.
MAX_REQUEST_BYTES = (MAX_PICTURE_BYTES + 2) // 3 * 4 + 64 * 1024
# The first bytes of each kind of picture (its "magic number").
PICTURE_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
```

New functions:

- `picture_kind(data)` → `"png"`, `"jpeg"`, `"gif"`, `"webp"`, or `None`. Reads only the first bytes:
  - PNG: `89 50 4E 47 0D 0A 1A 0A`
  - JPEG: `FF D8 FF`
  - GIF: `GIF87a` or `GIF89a`
  - WebP: `RIFF` at 0–3 and `WEBP` at 8–11 (a WAV sound file also starts with `RIFF`).

  SVG is never accepted: it is text that can hold a script.
- `check_picture(encoded)` → `(kind, data)`, or raises `RuleBroken`. Refuses: not a string; longer
  than base64 of `MAX_PICTURE_BYTES` (checked before decoding); not plain base64
  (`base64.b64decode(encoded, validate=True)`; a `data:image/png;base64,` start is refused, the page
  removes it); more than `MAX_PICTURE_BYTES` after decoding; `picture_kind` is `None`.
- `check_alt_text(alt_text)` → trimmed text, or `RuleBroken`: empty, over `MAX_ALT_TEXT`, or
  `HIDDEN_CHARACTERS`.
- `insert_post(connection, user_id, text)` → the new post id. Only the `INSERT INTO posts` line,
  moved out of `save_post` so both save functions share it. `save_post` now calls it (small change).
- `save_post_with_picture(db_path, user_id, text, picture, alt_text)` → the saved row, like
  `save_post`. **All checks first** (`check_text`, `check_picture`, `check_alt_text`), then one
  transaction: `insert_post`, `INSERT INTO pictures`, `commit`. A broken rule saves nothing.
- `picture_for(db_path, post_id)` → the row `(kind, bytes)`, or `None`. Takes a number, never a path.

`POSTS_WITH_AUTHORS` gains one column, written like `like_count`, never the bytes:

```sql
(SELECT alt_text FROM pictures WHERE pictures.post_id = posts.id) AS picture_alt
```

`NULL` means the post has no picture (alt text can never be empty).

Error messages (all `RuleBroken` → 400):
"The picture must be a PNG, JPEG, GIF or WebP file." · "The picture must be 2 MB or smaller." ·
"The picture could not be read." · "Please describe the picture in a few words." ·
"The description must be 200 characters or fewer." · "The description must not have hidden
characters or line breaks."

### Routes

| Request | In | Answer |
|---|---|---|
| `POST /posts` | `{"text": "...", "picture": "<base64>", "picture_alt": "a cat asleep on a desk"}`; `picture` and `picture_alt` may be left out | 201 + the post JSON, 400 a rule, 401 not signed in, **413** body too big |
| `GET /posts?after=…` | — | each post now has `"picture": {"url": "/pictures/7", "alt": "…"}` or `"picture": null` |
| `GET /pictures/<post id>` | — | 200 the bytes, or 404. Open to everyone, like reading posts. |

**Controller changes.**

- `read_json` (small change): before reading, refuse a `Content-Length` that is missing, not a
  number, below 0 or above `MAX_REQUEST_BYTES`, with 413 "The request is too big." Today it reads
  any length, so this also protects every other route. It is a limit on reading, not a rule about
  posts: the picture's own limit is checked in the model.
- `take_post` (small change): if `"picture"` is in the data, call `save_post_with_picture(…,
  data.get("text"), data.get("picture"), data.get("picture_alt"))`, else `save_post` as now.
- `do_GET` (small change): one `elif url.path.startswith("/pictures/"): self.send_picture(url.path)`.
- `send_picture(path)` (add): `re.fullmatch(r"/pictures/([0-9]{1,18})", path)` or 404. The number
  goes to `picture_for`. No part of the request is ever used as a file name. Unknown id → 404.
- `send_picture_answer(content_type, body)` (add), so `send_answer` is not changed. Headers:
  - `Content-Type` from `PICTURE_TYPES[row["kind"]]`, the kind the server found, not what was sent.
  - `X-Content-Type-Options: nosniff`: the browser must believe the type and never guess. A file
    that starts like a PNG but hides HTML is then still only an image.
  - `Content-Security-Policy: default-src 'none'; sandbox`: if someone opens the picture's address
    on its own, nothing in it can run.
  - `Cache-Control: max-age=86400`: a post's picture never changes, so a window loads it once.

### View

- `post_to_json` (small change): add `"picture": picture_to_json(row)`.
- `picture_to_json(row)` (add): `None` if `row["picture_alt"]` is `None`, else
  `{"url": "/pictures/" + str(row["id"]), "alt": row["picture_alt"]}`. The page never builds the
  address itself.

### Page

`index.html`, inside `#post-form`, before `.post-row`:

```html
<label for="picture">Picture (optional): PNG, JPEG, GIF or WebP, up to 2 MB</label>
<input id="picture" type="file" accept="image/png,image/jpeg,image/gif,image/webp">
<label for="picture-alt">Describe the picture for people who cannot see it</label>
<input id="picture-alt" type="text" maxlength="200">
<p class="hint">A photo from a phone may hold the place where it was taken.</p>
```

`app.js`:

- Constants `MAX_PICTURE_BYTES`, `MAX_ALT_TEXT`, `PICTURE_TYPES` (same values as the model).
- `pictureProblem(file, altText)` (add): the same rules as the model, as far as a page can check:
  size, the browser's type (only a quick hint: the server reads the bytes), the description.
- `readPictureAsBase64(file)` (add): `FileReader.readAsDataURL`, then keep only the part after
  the comma.
- `pictureElement(picture)` (add): `<img class="post-picture" loading="lazy">`, `img.src =
  picture.url`, `img.alt = picture.alt` (set as properties, never as HTML).
- `showPost` (small change): one line, `if (post.picture) item.insertBefore(pictureElement(post.picture), likeRow);`
- `sendPost` (change): if a file is chosen, check it, read it, add `picture` and `picture_alt` to
  the body; after 201, clear both boxes. A 413 shows the server's message.

`style.css` (and its copy `page-only/style.css`), at the end under `/* pictures */`:
`.post-picture { display: block; max-width: 100%; max-height: 24rem; object-fit: contain;
border-radius: …; margin-top: … }` and `.hint` if not already there.

### If the owner chooses files on disk (2.2 b) instead

`pictures` keeps `file_name TEXT NOT NULL UNIQUE` instead of `bytes`; the name is
`secrets.token_hex(16) + "." + kind`, made by the server. The file is written to a temporary name
and renamed after the row is committed. `send_picture` still takes only the post id and reads the
name from the row. Add `with-backend/pictures/` to `.gitignore` and `rm -rf with-backend/pictures`
to `make reset`; `make_server` takes a `pictures_dir` so tests use a temporary folder; deleting a
post must also delete the file (`edit-delete`).

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | imports: `base64` | change |
| `with-backend/server.py` | `TimelineHandler.do_GET`: `/pictures/` branch | change |
| `with-backend/server.py` | `TimelineHandler.read_json`: size check, 413 | change |
| `with-backend/server.py` | `TimelineHandler.take_post`: picture branch | change |
| `with-backend/server.py` | `TimelineHandler.send_picture` | add |
| `with-backend/server.py` | `TimelineHandler.send_picture_answer` | add |
| `with-backend/server.py` | model constants `MAX_PICTURE_BYTES`, `MAX_ALT_TEXT`, `MAX_REQUEST_BYTES`, `PICTURE_TYPES` | add |
| `with-backend/server.py` | `create_tables`: call the upgrade | change |
| `with-backend/server.py` | `upgrade_to_pictures` | add |
| `with-backend/server.py` | `POSTS_WITH_AUTHORS`: `picture_alt` column | change |
| `with-backend/server.py` | `picture_kind`, `check_picture`, `check_alt_text` | add |
| `with-backend/server.py` | `insert_post` | add |
| `with-backend/server.py` | `save_post`: calls `insert_post` | change |
| `with-backend/server.py` | `save_post_with_picture`, `picture_for` | add |
| `with-backend/server.py` | `post_to_json`: `picture` key | change |
| `with-backend/server.py` | `picture_to_json` | add |
| `with-backend/app.js` | constants `MAX_PICTURE_BYTES`, `MAX_ALT_TEXT`, `PICTURE_TYPES`; two element lookups | add |
| `with-backend/app.js` | `pictureProblem`, `readPictureAsBase64`, `pictureElement` | add |
| `with-backend/app.js` | `showPost`: one line | change |
| `with-backend/app.js` | `sendPost`: picture in the body, clear after | change |
| `with-backend/index.html` | `#post-form`: file box, description box, hint | change |
| `with-backend/style.css`, `page-only/style.css` | `/* pictures */` at the end | add |
| `with-backend/test_server.py` | new tests at the end of each of the four classes | add |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (see 7) | add |

Not touched: `Makefile`, `.gitignore` (with 2.2 a), `page-only/index.html`, `page-only/app.js`.

## 5. Depends on, and collides with

- **Depends on `accounts`**: posting needs `user_for_session`; `check_alt_text` reuses
  `HIDDEN_CHARACTERS`; the 413 check goes into the `read_json` accounts wrote.
- **`edit-delete`**: deleting a post must delete its picture. If it deletes the `posts` row,
  `ON DELETE CASCADE` does it. If it only marks a post as deleted, it must also run
  `DELETE FROM pictures WHERE post_id = ?` in the same transaction, and `GET /pictures/<id>` must
  answer 404 for a deleted post. Editing changes the text only, never the picture. Both plans
  touch `POSTS_WITH_AUTHORS`, `post_to_json` and `showPost`.
- **`timestamps`**, **`replies`**, **`place`**: change how a post is inserted. After this plan the
  `INSERT INTO posts` is in `insert_post`, so they change it there once. All three also touch
  `POSTS_WITH_AUTHORS`, `post_to_json` and `showPost` (one line each: rebase, not redesign).
- **`report`**: a hidden post's picture should also get 404 from `GET /pictures/<id>`.
- **`rate-limit`**: also wraps `take_post`. It may want a smaller allowance for picture posts.
- **`long-posts`**: `MAX_REQUEST_BYTES` leaves 64 KB for text, enough for 500 characters.
- **`timeline-flow`**, **`links-and-tags`**, **`search`**: change `showPost` or the posts query;
  one-line merges.
- **`drafts`**: a draft cannot keep a chosen file (the browser does not allow it). Only text is kept.
- **`japanese`**: the new labels and messages need translating.

## 6. Tests

Small real pictures are written in the test file as bytes (a 1×1 PNG and GIF, the first bytes of a
JPEG and a WebP), and base64-encoded there.

**`ModelTests`**
- Each of the four kinds is accepted, and `picture_kind` names it.
- A text file named `cat.png`, an SVG, an HTML page, and a WAV (`RIFF…WAVE`) are refused.
- Exactly `MAX_PICTURE_BYTES` is accepted; one byte more is refused.
- Bad base64, and a `data:image/png;base64,` start, are refused.
- Empty, too long, or hidden-character alt text is refused.
- A broken rule saves nothing: no `posts` row and no `pictures` row.
- The bytes read back with `picture_for` are exactly the bytes sent.
- A post without a picture has `"picture": null`; the posts query never returns the bytes.
- The database itself refuses a second picture for one post, `kind = 'svg'`, and too many bytes,
  with plain SQL that skips the model.
- Deleting a `posts` row deletes its `pictures` row.
- The upgrade keeps every old row; old posts have no picture.
- The number in the table's CHECK equals `MAX_PICTURE_BYTES` (read from `sqlite_master`).

**`RealServerTest`**
- Post with a PNG → 201; `GET` its `url` → the same bytes, `Content-Type: image/png`,
  `X-Content-Type-Options: nosniff`, and the `Content-Security-Policy`.
- A GIF chosen from a file named `photo.jpg` is served as `image/gif`: the type comes from the bytes.
- `/pictures/999`, `/pictures/abc`, `/pictures/1.png`, `/pictures/../timeline.db` and
  `/pictures/%2e%2e%2fserver.py` → 404, and the body is never the file.
- A picture post with no cookie → 401 and no rows; with `Content-Type: text/plain` → 400.
- A `Content-Length` above `MAX_REQUEST_BYTES` → 413, sent without the body.

**`JourneyTest`**
- Aiko signs up and posts with a picture: SQL shows one `pictures` row with the right `post_id`,
  `kind` and `length(bytes)`. Ben's window gets the post with its `url`, loads it, and the bytes
  match. Ben posts a text file renamed `.png`: 400, and the row counts in `posts` and `pictures`
  do not change. (When `edit-delete` is merged: Aiko deletes the post, the `pictures` row is gone,
  and the `url` answers 404.)

**`PageAndServerAgreeTest`**
- `MAX_PICTURE_BYTES`, `MAX_ALT_TEXT` and the four types in `app.js` equal the model's.
- The `accept` list in `index.html` equals `PICTURE_TYPES`.
- The page sends the keys `picture` and `picture_alt`, which are the keys the server reads.
- The page takes the picture's address from `post.picture.url` and never builds `/pictures/`
  itself; it sets `alt`.
- Both `style.css` files are the same.

## 7. Docs to update

- `AGENTS.md`: add `pictures` to the model's list of tables and functions, `picture_to_json` to
  the view, and `GET /pictures/<id>`. In "How to run it", the "see what is saved" line gains
  `select post_id, kind, length(bytes), alt_text from pictures` (never `select *`: it would print
  the picture's raw bytes into the terminal).
- `DESIGN.md`: a new "Pictures" section (BLOB table, magic numbers, nosniff, base64 in JSON and
  why not multipart); the "No pictures" line in section 2 now points to it; new rows in the
  objections table for 2.1, 2.2 and 2.6.
- `README.md`: one line that posts can carry a picture, up to 2 MB.

## 8. Not in this plan

- Resizing, cropping or compressing pictures (needs an image library such as Pillow).
- Removing location data from photos (2.6 c, a later plan).
- Checking a picture's width and height. A tiny file can claim a huge size and slow a browser.
  Reading the size from the header is possible later for PNG and GIF; JPEG and WebP are harder.
- More than one picture per post; video; SVG; HEIC (iPhone's own format: Safari usually
  converts it to JPEG when uploading).
- Changing or removing the picture of a post that is already posted.
- Pictures in `page-only/`.
- Keeping `GET /pictures/…` out of the terminal log (each new window logs one line per picture).

## 9. Size

**M**, about 450 lines: `server.py` about 140, `app.js` about 70, `index.html` 8, CSS 12,
tests about 190, docs about 30.

## Changes made at approval (orchestrator)

- **Decision 6 is changed.** The page redraws a JPEG through a `<canvas>` before sending it. This
  drops all EXIF data, so a phone photo's GPS location is never published. Modern browsers already
  turn the photo the right way up when they draw it, so the rotation is kept. A large photo can be
  made smaller on the way, to fit under the limit. GIFs are not redrawn, so animations still work.
  The server still checks every picture; the redraw protects people from accidents.
- `insert_post` and the request-size check (413) are built in `groundwork`, not here.
- The picture route uses the shared visibility filter from `groundwork`, so a post hidden by
  `block` or `report` does not show its picture.
