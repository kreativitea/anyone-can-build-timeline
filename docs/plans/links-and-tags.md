Status: built on branch links-and-tags, awaiting merge

# Links, tags and names

## 1. What it does

When a post has a web address in it (`https://example.com`), a `#tag` (`#kyoto`) or an account
name (`@aiko`), the timeline shows it in colour, and you can click it. A web address opens that
website in a new tab. A `#tag` opens a search for every post with that tag, and an `@name` opens a
search for that person's posts (both need the `search` plan). Nothing changes when you write a post:
you type plain words, as now.

## 2. Decisions for the owner

1. **Should a web link open in a new tab?**
   - (a) Yes: `target="_blank"` with `rel="noopener noreferrer"`. The timeline stays open, and the
     other website can neither control this tab (`noopener`) nor learn the address it came from
     (`noreferrer`).
   - (b) No: open in the same tab, and the person leaves the timeline.
   - **Recommendation: (a).** The timeline is a page you keep open; it asks the server for new posts
     every second.

2. **What does a `#tag` or an `@name` do before `search` is merged?**
   - (a) Build this plan now. Until `search` is merged, a tag and a name are shown in colour but are
     not clickable. When both are merged, a small change (about 10 lines, in one function) makes
     them clickable.
   - (b) Wait, and build this plan only after `search` is merged.
   - **Recommendation: (a).** Web links are the part with the most risk and the most value, and
     they do not need `search`.

3. **Which characters may a `#tag` hold?**
   - (a) English letters, digits and `_`, with at least one letter: `#kyoto`, `#web_2`. So `#1`
     and `#2026` stay plain words ("we are #1").
   - (b) Letters in any language too: `#京都`.
   - **Recommendation: (a) now, (b) later with the `japanese` plan.** The page (JavaScript) and the
     model (Python) must use the exact same pattern, and Python's `re` cannot say "a letter in any
     language" the way JavaScript can (`\p{L}`). Doing (b) well is its own small piece of work.

4. **Where is a post's text cut into words, links, tags and names?**
   - (a) In the page, in `app.js`. The model has a twin of the same function, with the same
     patterns, so the tests (which only run Python) can check its behaviour with a table of examples.
     The server's answers do not change.
   - (b) In the server: `post_to_json` sends a new key, `pieces`, already cut up, and the page only
     draws them.
   - **Recommendation: (a).** No change to `post_to_json`, which many other plans also change, and no
     change to the JSON. The cost is two copies of a small function; section 6 says how the tests
     keep them the same.

5. **Does a link show the whole web address, or a short one (`example.com/…`)?**
   - (a) The whole address, exactly as it was typed.
   - (b) A short form.
   - **Recommendation: (a).** A person should see where a link goes before they click it. A short
     form could hide a dangerous address behind a friendly one.

## 3. Design

### Safety: the most important part

Today `showPost` puts a post's text on the screen with `textContent`. `textContent` shows words
*as words*: if a post says `<script>…</script>`, the screen shows those characters, and nothing
runs. **This plan keeps that.** It never uses `innerHTML` (which reads text *as HTML*, so a post
could run code on everyone's page). Instead it builds the parts by hand:

- plain words become a **text node** (`document.createTextNode`), which is always just words;
- a link becomes an `<a>` element made with `document.createElement("a")`. Its address goes in
  `href`, and the words shown go in with `textContent`.

Rules for a web link:

- **Only `http:` and `https:`.** The link pattern starts with the letters `http://` or `https://`,
  so `javascript:alert(1)`, `data:text/html,…` and `file:///…` can never even match: they stay plain
  words. As a second guard, the page reads the address with `new URL(…)` and makes an `<a>` only if
  its `protocol` is exactly `"http:"` or `"https:"`. If `new URL` fails, the words stay plain.
- Only lowercase `http`/`https` count. `HTTPS://x.com` stays plain words. (Simple, and rare.)
- A link may hold only the characters a web address may hold (from the standard, RFC 3986): `A–Z
  a–z 0–9 - . _ ~ : / ? # [ ] @ ! $ & ' ( ) * + , ; = %`. So a link stops at a space, at `<`, `>`
  or `"`, and at any non-English letter: `https://x.com/を見て` links only `https://x.com/`.
- **Punctuation at the end is not part of the link.** "see https://x.com." links `https://x.com`,
  and the `.` stays a word. The characters cut from the end, one at a time, again and again:
  `. , : ; ! ? * '` (this list is `LINK_END`). A `)` at the end is cut only if the link has more
  `)` than `(`, so `(see https://x.com)` cuts it, but `https://en.wikipedia.org/wiki/Kyoto_(city)`
  keeps it. `]` works the same way with `[`.
- After cutting, the link must still have a letter or digit just after `://` (`LINK_START`).
  `https://.` is plain words.
- Every link gets `target="_blank"` and `rel="noopener noreferrer"` (decision 1).
- The words shown are the address exactly as typed (decision 5). A long address wraps, because
  `.post-text` already has `overflow-wrap: anywhere`.

### The three patterns

The same text in `app.js` and in `server.py` (JavaScript writes `\/` for `/` outside `[ ]`; the test
ignores that one difference). `(?<! … )` means "not just after", and `(?! … )` means "not just
before". Both work the same in Python and in every current browser.

| Name | Pattern | Matches | Does not match |
|---|---|---|---|
| `LINK` | `https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+` | `https://x.com/a?b=1` | `javascript:…`, `ftp://…` |
| `TAG` | `(?<![A-Za-z0-9_])#[A-Za-z0-9_]*[A-Za-z][A-Za-z0-9_]*` | `#kyoto`, `#web_2` | `#1`, `page#top` |
| `NAME` | `(?<![A-Za-z0-9_])@[A-Za-z0-9_]{1,40}(?![A-Za-z0-9_])` | `@aiko`, `(@ben_2)` | `aiko@mail.com`, an `@` with 41 characters |

- A `#tag`: `#`, then English letters, digits and `_`, with at least one letter (decision 3). It
  must not come straight after a letter, digit or `_`, so `page#top` is not a tag. It ends at the
  first other character: `#kyoto!` is the tag `#kyoto` and the word `!`.
- An `@name`: `@`, then 1 to 40 of `[A-Za-z0-9_]`: exactly the account-name rule `ACCOUNT_NAME` and
  the length `MAX_AUTHOR` in the model. A longer run is not a name at all (not a cut-off one). It
  must not come straight after a letter, digit or `_`, so an email address is not a name. `@aiko's`
  is the name `@aiko` and the word `'s`. The page does not ask whether the account exists: `@nobody`
  is shown like any name, and a search for it simply finds nothing.
- The three are tried together, left to right, and a link wins where they overlap:
  `https://x.com/#top` is one link, not a link and a tag.

### Model (`server.py`)

Nothing is refused, and nothing is saved differently. A post that says `javascript:alert(1)` or
`<script>` is a fine post: it is shown as words. The danger is only in *how a page shows* text, and
the server sends text as JSON, never as HTML. So no new rule, no new check, no database change and
no upgrade function.

The model gets the twin of the page's function, as pure functions (they touch no database):

- constants `LINK`, `TAG`, `NAME` (compiled patterns), `LINK_START`, and the string `LINK_END`;
- `trim_link_end(link)` → the link without the punctuation at its end (rules above);
- `post_text_pieces(text)` → a list of pieces, each `{"kind": "text" | "link" | "tag" | "name",
  "text": …}`. Joined together, the pieces' `text` is always the whole post again, letter for letter;
- `tags_in(text)` → the tags in a post, lowercase, each once, in order: `["kyoto", "food"]`.
  This is for `search` (section 5), so the server and the page agree on what a tag is.

### Routes and view

None. `post_to_json` does not change (decision 4).

### Page (`app.js`)

New constants, next to `ACCOUNT_NAME`: `LINK`, `TAG`, `NAME`, `LINK_START`, `LINK_END`, and
`PIECE = new RegExp(LINK.source + "|" + TAG.source + "|" + NAME.source, "g")`.

New functions, all below `showPost`:

- `postTextPieces(text)`: the twin of `post_text_pieces`, line for line. It walks the matches of
  `PIECE`; a link goes through `trimLinkEnd`, and a link that then fails `LINK_START` stays words.
- `trimLinkEnd(link)`: the twin of `trim_link_end`.
- `showPostText(element, text)`: for each piece, `element.append(pieceElement(piece))`.
- `pieceElement(piece)`: a text node for `text`; `linkElement` for `link`; `searchElement` for
  `tag` and `name`.
- `linkElement(address)`: `new URL(address)` in a `try`; only `http:`/`https:`; makes the `<a>`
  with `href`, `textContent`, `target`, `rel` and `className = "post-link"`. Otherwise a text node.
- `searchElement(words, className)`: until `search` is merged, a `<span>` with `textContent` and the
  class `post-tag` or `post-name`. When it is, an `<a href="/?q=…">` (built with
  `encodeURIComponent`) that runs the search in this tab (section 5).

The only change to `showPost` is one line:

```js
text.textContent = post.text;      // before
showPostText(text, post.text);     // after
```

The comment "textContent, never innerHTML" in `showPost` stays true and stays.

### Look (`style.css`, at the end, under `/* links-and-tags */`)

`.post-link`, `.post-tag`, `.post-name`: the colour `var(--author)` (already in both themes, so
`dark-mode` needs nothing new), and a link is underlined so it does not depend on colour alone.
`a.post-tag:focus-visible` etc. get a clear outline for keyboard users. About 20 lines, copied to
`page-only/style.css` as usual.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/app.js` | constants `LINK`, `TAG`, `NAME`, `LINK_START`, `LINK_END`, `PIECE` (after `ACCOUNT_NAME`) | add |
| `with-backend/app.js` | `postTextPieces`, `trimLinkEnd`, `showPostText`, `pieceElement`, `linkElement`, `searchElement` | add |
| `with-backend/app.js` | `showPost`: one line, `text.textContent = post.text` → `showPostText(text, post.text)` | change |
| `with-backend/server.py` | model: constants `LINK`, `TAG`, `NAME`, `LINK_START`, `LINK_END` (after `ACCOUNT_NAME`) | add |
| `with-backend/server.py` | model: `trim_link_end`, `post_text_pieces`, `tags_in` | add |
| `with-backend/style.css` | `/* links-and-tags */` at the end: `.post-link`, `.post-tag`, `.post-name` | add |
| `page-only/style.css` | the same copy | add |
| `with-backend/test_server.py` | new class `PostTextTests` (with the `EXAMPLES` table), at the end | add |
| `with-backend/test_server.py` | `JourneyTest`: one new method at the end | add |
| `with-backend/test_server.py` | `PageAndServerAgreeTest`: new methods at the end | add |
| `AGENTS.md`, `DESIGN.md`, `README.md` | a new section each | add |

Not touched: `index.html`, the controller, the view, `POSTS_WITH_AUTHORS`, `post_to_json`,
`checkForNewPosts`, `clickOnTimeline`, the database.

## 5. Depends on, and collides with

- **`accounts`** (depends on): `NAME` is built from `ACCOUNT_NAME` and `MAX_AUTHOR`, and the
  tests check that. If `accounts` changes either one, this plan's test fails, which is the point.
- **`search`** (works with; neither must wait). What this plan needs from `search`:
  1. an address that opens the page with a search already done: `/?q=<words>`, so a tag link also
     works in a new tab or when copied;
  2. a page function `searchFor(words)` that runs a search in this tab without reloading;
  3. that a search for `#kyoto` finds posts with that tag, without caring about upper or lower case,
     using the model's `TAG` (or `tags_in`) so the two plans agree on what a tag is;
  4. if it can, that a search for `@aiko` finds posts by `@aiko`. If not, an `@name` stays a
     coloured, not clickable word.

  The two plans must not both add a `TAG` pattern: whichever merges first adds it, and the other
  uses it. If `search` is merged first, this plan builds `searchElement` as a link straight away. If
  this plan is merged first, `searchElement` makes a `<span>`, and the `search` branch changes only
  `searchElement` (about 10 lines) when it is rebased.
- **`edit-delete`, `replies`, `timeline-flow`** (collide lightly): each one that draws a post's
  text somewhere new (an edited post, a quoted post, older posts loaded on scroll) must draw it
  with `showPostText`, never `textContent` alone and never `innerHTML`. All of them change
  `showPost`; this plan changes only one line of it, so a rebase is simple.
- **`timestamps`, `pictures`, `place`, `who-liked`, `block`, `report`, `bookmarks`**: also change
  `showPost`, on other lines. No real collision.
- **`japanese`**: tags in other languages (decision 3) and Japanese punctuation at the end of a link
  (`。` already stops a link, because it is not a web-address character).
- **`dark-mode`**: none, because the colours come from existing variables.
- **`long-posts`**: none; the patterns have no limit tied to 280.

## 6. Tests

The page's JavaScript is never run by the tests. So the behaviour is written down **once, as a
table of examples**, and checked on the model's twin; then the agree tests check that the page's
twin is built from the very same patterns and the same list of end characters.

**`PostTextTests`** (a new class of model tests, after the others). `EXAMPLES` is a list of
`(text, expected pieces)`, and one test runs `post_text_pieces` on every row (with `subTest`).
Pieces are written short here: `("link", "https://x.com")`.

| Text | Pieces |
|---|---|
| `hello` | text `hello` |
| `see https://x.com.` | text `see `, link `https://x.com`, text `.` |
| `(see https://x.com)` | text `(see `, link `https://x.com`, text `)` |
| `https://en.wikipedia.org/wiki/Kyoto_(city)` | link, the whole of it |
| `https://x.com/?a=1&b=2!!` | link `https://x.com/?a=1&b=2`, text `!!` |
| `javascript:alert(1)` | text, all of it |
| `data:text/html,<b>hi</b>` | text, all of it |
| `HTTPS://x.com` | text, all of it |
| `https://.` | text, all of it |
| `https://x.com/を見て` | link `https://x.com/`, text `を見て` |
| `<script>alert(1)</script>` | text, all of it |
| `#kyoto is nice` | tag `#kyoto`, text ` is nice` |
| `we are #1` | text, all of it |
| `page#top` | text, all of it |
| `https://x.com/#top` | link, the whole of it |
| `hi @aiko's cat` | text `hi `, name `@aiko`, text `'s cat` |
| `mail aiko@mail.com` | text, all of it |
| `@` + 40 × `a` | name, the whole of it |
| `@` + 41 × `a` | text, all of it |
| `@aiko #kyoto https://x.com` | name, text ` `, tag, text ` `, link |

More model tests:
- joining the pieces' `text` gives back the whole post, for every row of `EXAMPLES`;
- `tags_in("#Kyoto and #kyoto and #food")` is `["kyoto", "food"]`.

**`RealServerTest`**: nothing new. No route changes.

**`JourneyTest`**, one new method: a signed-in person posts
`see https://x.com. #kyoto @ben javascript:alert(1) <b>hi</b>`; `GET /posts` gives that text back
exactly, letter for letter, with the same keys as any other post (no `pieces`, no HTML); and the
`text` column in the database file holds exactly the same. This shows that the server neither
changes nor refuses such a post, and that drawing it safely is the page's job.

**`PageAndServerAgreeTest`**, new methods:
- `LINK`, `TAG`, `NAME` and `LINK_START` in `app.js` are the same text as in `server.py`
  (the test reads `app.js` with `\/` turned into `/`);
- `app.js` has `LINK_END = "<the same characters>"`;
- `NAME` holds `ACCOUNT_NAME`'s `[A-Za-z0-9_]` and `{1,<MAX_AUTHOR>}`;
- `app.js` never says `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write`;
- `app.js` names no protocol except `"http:"` and `"https:"`, and says
  `"noopener noreferrer"`;
- `showPost` calls `showPostText(text, post.text)` and no longer says `text.textContent = post.text`.

**By hand, once, in a browser** (the tests cannot see the screen): post the rows of `EXAMPLES`,
check each looks as the table says, that a link opens in a new tab, that `javascript:alert(1)`
does nothing when clicked (it is not a link), and that Tab reaches each link with a visible outline.

## 7. Docs to update

- `AGENTS.md`: a new short section, "Links, tags and names": the page never uses `innerHTML`; a
  post's text goes through `showPostText`; `post_text_pieces` in the model is the twin of
  `postTextPieces` in the page, and a change to one is a change to both and to `EXAMPLES`.
- `DESIGN.md`: a new section with the three patterns, the end-punctuation rule and why only `http`
  and `https`.
- `README.md`: one line in the things to try: post a link, a `#tag` and an `@name`.

## 8. Not in this plan

- A preview card for a link (a picture and title from the other website).
- Making `example.com` or `www.example.com` a link without `https://`.
- Email addresses as links (`mailto:`).
- Tags in Japanese or other languages (decision 3, later with `japanese`).
- Checking that an `@name` is a real account, telling a person they were named, and a page for
  each person.
- A list of popular tags.
- A `Content-Security-Policy` header from the server (a second wall against code in the page).
  Worth doing, but it is about the whole page, not this feature.
- `page-only/`: it stays as it is (only its `style.css` copy changes).

## 9. Size

**M**, about 260 lines: `app.js` about 75, `server.py` about 45, tests about 90, CSS about 20
(twice), docs about 30.

## Changes made at approval (orchestrator)

- **The tag rule belongs to `search`.** `search` is built first and its `TAG` pattern covers
  Japanese, the same text in `server.py` and `app.js`. This plan uses that `TAG` and does not
  write its own, so `#東京` works from the start.
