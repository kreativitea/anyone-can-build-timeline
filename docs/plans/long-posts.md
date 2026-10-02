Status: approved

# Long posts

## 1. What it does

A post can be up to 560 characters long, not 280 (140 → 280 → 560: each step doubles). The live
count under the box says `x / 560`. An emoji counts as one character in the page, as it already
does on the server, so the count never says "fine" for a post the server will refuse.

A long post does not fill the screen. If a post is taller than 6 lines on the timeline, only its
first 6 lines show, with a **Show more** button under them. Pressing it shows the whole post, and
the button becomes **Show less**. A short post has no button.

## 2. Decisions for the owner

All four are decided.

1. **The new limit.** *Decided: 560.* After this plan, the number is written in two places only
   (`MAX_TEXT` in `server.py` and in `app.js`), and a test fails if they differ.
2. **What is "one character"?** *Decided: a code point, the same on both sides.* A *code point* is
   one Unicode number. Python's `len()` counts these. Most emoji are 1, but a family emoji 👨‍👩‍👧
   is 5. (Counting *graphemes*, what a person sees as one letter, is not possible with Python's
   standard library.) The page changes from `.length` to `[...text].length`, because JavaScript's
   `.length` counts *UTF-16 units*, so 😀 is 2 there and 1 in Python.
3. **`page-only/`.** *Decided: leave it at 280.* It is a demo (`docs/plans/README.md`). It keeps
   its own 280, its own hand-written message and its own `0 / 280` in the HTML. Section 8 lists them
   so nobody thinks they were missed. Only `page-only/style.css` changes, because it must stay a
   copy of `with-backend/style.css`.
4. **A rule in the database.** *Decided: no `CHECK (length(text) <= 560)`.* SQLite cannot add a
   `CHECK` to an existing table, so the whole `posts` table would have to be copied, and that would
   collide with every plan that adds a column to `posts`. Only the model writes posts.

## 3. Design

**Database.** No change. No upgrade function. Old posts are all 280 or shorter, so they still
follow the new rule.

**Model (`server.py`).** One line: `MAX_TEXT = 280` becomes `MAX_TEXT = 560`. `check_text` already
uses `len(text)` (code points) and already builds its message from `MAX_TEXT`. Nothing else.

**Routes and view.** No change.

**Page (`with-backend/app.js`): the limit and the count.**
- `MAX_TEXT = 280` becomes `MAX_TEXT = 560`.
- Add one small function, so the page counts the way Python does:
  ```js
  // How many characters, counted the way the server counts them.
  // "😀".length is 2 in JavaScript, but [..."😀"].length is 1, as in Python.
  function characterCount(text) {
    return [...text].length;
  }
  ```
- `textProblem`: `text.length > MAX_TEXT` becomes `characterCount(text) > MAX_TEXT`.
- `updateCount`: `textBox.value.length` becomes `characterCount(textBox.value)`. Its comment
  `"x / 280"` becomes `"x / MAX_TEXT"`.
- At the end of the file, with the other start-up lines, call `updateCount();` once, so the page
  writes its own starting `0 / 560`.

**Page (`with-backend/index.html`).** `<span id="count" class="count">0 / 280</span>` becomes
`<span id="count" class="count"></span>`. The number is no longer in the HTML, so it cannot go
stale.

**Show more / Show less.**

*How much is shown: 6 lines.* The text is 24px with a line height of 1.4, so one line is about
34px, and 6 lines are about 200px. On a computer, a post's text is about 830px wide, roughly 65 to
70 characters a line. So every old post of 280 characters (4 to 5 lines) still shows in full, and
only the new longer posts (up to about 9 lines) fold. On a phone, a line holds about 25 characters,
so a 280-character post folds there too, which is what a phone needs. Six lines also leave room for
a short poem or a list, written with line breaks, to show in full.

*We fold by height, not by character count.* The text has `white-space: pre-wrap`, so each line
break is a line. Ten short lines fold, and one long line of 300 characters on a wide screen does
not.

*CSS: line clamp.* The new rules go at the end of `style.css`, under `/* long-posts */`:
```css
/* long-posts */
.post-text.collapsed {
  display: -webkit-box;          /* line clamp works only on this kind of box */
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 6;
  line-clamp: 6;                 /* the future name; ignored for now */
  overflow: hidden;
}

.show-more {
  /* a quiet text button under the post, the same size as the text */
}
```
Why line clamp and not `max-height` with a fade: `-webkit-line-clamp` works in every current
browser (Chrome, Edge, Safari, and Firefox since version 68), even with the `-webkit-` name. It
always cuts between two lines, never through the middle of one, and it puts "…" at the end, so the
reader sees that the text goes on. A fade would need the card's background colour, so it would
break when `dark-mode` changes that colour. The unprefixed `line-clamp` is not in browsers yet; it
is written too, so nothing has to change when it arrives. Line clamp needs `display: -webkit-box`
and `-webkit-box-orient: vertical`, which is why both are in the rule. When the class is taken
away, the text goes back to a normal block.

*The page (`app.js`).* `showPost` gets one new line, at the very end, after
`timeline.prepend(item)`:
```js
makeExpandable(text, post.id);
```
It must come after the post is on the page, because a height can only be measured on the page.

New functions (all added, near `showPost`):
- `makeExpandable(textElement, postId)`: gives the text the id `post-text-<postId>` and the class
  `collapsed`; makes a `<button type="button" class="show-more">` with
  `aria-controls="post-text-<postId>"`, `aria-expanded="false"` and the words "Show more"; puts it
  right after the text; then calls `checkOverflow`.
- `checkOverflow(textElement)`: if the text is still collapsed, the button is shown only when the
  text really overflows: `textElement.scrollHeight > textElement.clientHeight + 1` (the `+ 1`
  allows for rounding). Otherwise the button gets the `hidden` attribute, so a short post shows no
  button and a screen reader does not announce one.
- `toggleExpanded(button)`: finds the text by `aria-controls`, toggles `collapsed`, sets
  `aria-expanded` to `"true"` or `"false"`, and changes the words to "Show less" or "Show more".
- `recheckAllPosts()`: calls `checkOverflow` for every `.post-text` on the page.

*When it is measured.* Once, right after each post is put on the timeline (the moment
`makeExpandable` runs). Reading `scrollHeight` makes the browser lay the post out first, so the
number is right. Again whenever the window is resized: one `resize` listener at the start-up lines
calls `recheckAllPosts`, at most once per screen frame (through `requestAnimationFrame`). A post
that is folded keeps or loses its button as it starts or stops overflowing. A post the reader has
opened stays open, with its "Show less" button, until they close it.

*The click.* No listener per post. The one existing handler on the timeline, `clickOnTimeline`,
gets a second check, written like the heart's:
```js
const more = event.target.closest(".show-more");
if (more !== null) {
  toggleExpanded(more);
}
```

*Screen readers.* The folded text is only clipped by CSS (`overflow: hidden`). It is never
`display: none`, `hidden` or `aria-hidden`, so a screen reader still reads the whole post. The
button is a real `<button>`, so it works with the keyboard, and `aria-expanded` tells a screen
reader whether the post is open.

*The words.* "Show more" and "Show less" are written once each, as two constants at the top of
`app.js` (`SHOW_MORE`, `SHOW_LESS`). `docs/plans/japanese.md` does not exist yet, so: these two
strings must move into the `japanese` words table, and `japanese` owns them from then on.

**Every hand-written "280", found by grep in `main` and in the `accounts` worktree:**

| Where | What it says | This plan |
|---|---|---|
| `with-backend/server.py` | `MAX_TEXT = 280` | change to 560 |
| `with-backend/app.js` | `MAX_TEXT = 280`; comment `"x / 280"` | change |
| `with-backend/index.html` | `0 / 280` | remove; `updateCount()` writes it |
| `with-backend/test_server.py` | `"a" * 281`, `test_text_of_exactly_280_is_allowed` | use `server.MAX_TEXT` |
| `DESIGN.md` | live count *x / 280*; "at most 280"; "longer than 280" | change to 560 |
| `README.md` | "a post over 280 characters" | change to 560 |
| `page-only/app.js` | `MAX_TEXT = 280`; message `"...280 characters or fewer."` | leave (decision 3) |
| `page-only/index.html` | `0 / 280` | leave (decision 3) |

`DESIGN.md`'s review table row *"The error message says '280' even if the limit is changed"* is a
record of a past decision, not a limit. It stays.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/server.py` | model constant `MAX_TEXT` | change (one line) |
| `with-backend/app.js` | constant `MAX_TEXT` | change |
| `with-backend/app.js` | constants `SHOW_MORE`, `SHOW_LESS` | add |
| `with-backend/app.js` | `characterCount` | add |
| `with-backend/app.js` | `makeExpandable`, `checkOverflow`, `toggleExpanded`, `recheckAllPosts` | add |
| `with-backend/app.js` | `showPost`: one line at the end, `makeExpandable(text, post.id);` | change (one line) |
| `with-backend/app.js` | `clickOnTimeline`: one `.show-more` check, like the heart's | change (4 lines) |
| `with-backend/app.js` | `textProblem` (post-text line only) | change |
| `with-backend/app.js` | `updateCount` | change |
| `with-backend/app.js` | start-up lines at the end: `updateCount();` and one `resize` listener | change (two lines added) |
| `with-backend/index.html` | `#count` span | change |
| `with-backend/style.css` | `/* long-posts */` at the end: `.post-text.collapsed`, `.show-more` | add |
| `page-only/style.css` | the same `/* long-posts */` block (it stays a copy) | add |
| `with-backend/test_server.py` | `ModelTests.test_too_long_text_is_refused`, `test_text_of_exactly_280_is_allowed` | change (literal → `server.MAX_TEXT`; second one renamed `test_text_of_exactly_the_limit_is_allowed`) |
| `with-backend/test_server.py` | new methods at the end of `ModelTests`, `RealServerTest`, `PageAndServerAgreeTest` | add |
| `DESIGN.md`, `README.md` | the lines in the 280 table above, and a new **Long posts** section in `DESIGN.md` | change / add |

## 5. Depends on, and collides with

- **Depends on `accounts`.** Planned against its `server.py` (`check_text`, `save_post(…, user_id,
  …)`) and its `app.js` (`showPost`, `clickOnTimeline`, `textProblem`, start-up lines). The
  accounts plan promises an agree test that *"the page has the same limits and patterns as the
  model"*, but today its `PageAndServerAgreeTest` checks only `ACCOUNT_NAME`. If accounts lands a
  `MAX_TEXT` check, this plan uses it and does not add a second one. Accounts already adds a test
  that both `style.css` files are the same, so `page-only/style.css` must get the same block.
- **`links-and-tags`:** also changes how the post text is built in `showPost` (links instead of
  plain `textContent`). `makeExpandable` works on any element, so it only needs to run *after* the
  text is filled in. Keep `makeExpandable(text, post.id)` as the last line of `showPost`.
- **`edit-delete`:** redraws a post's text after an edit, and its edit box must use `MAX_TEXT` and
  `characterCount`. After a redraw it calls `checkOverflow` on the new text (or `makeExpandable` if
  it builds a new element), so the button matches the new length. Build `long-posts` first if
  possible, so edit-delete reuses both.
- **`japanese`:** Part A owns the words. "Show more" and "Show less" move from the two constants
  into its words table. It must also keep building the "characters or fewer" message from
  `MAX_TEXT`, never type the number.
- **`drafts`:** also adds to the start-up lines, and calls `updateCount` after it puts a saved
  draft back. Both are one-line additions; `updateCount()` must run after the draft is restored.
- **`dark-mode`:** none, because the line clamp uses no colour. Both add blocks at the end of
  `style.css`, which is an easy rebase.
- **`timeline-flow`:** adds posts at the bottom when scrolling. Every post goes through
  `showPost`, or must call `makeExpandable` the same way.
- **`replies`, `pictures`:** if they change `check_text` (for example, a picture with no text), the
  change is in the same function. Small conflict, easy to rebase.

## 6. Tests

**`ModelTests`**
- The two existing limit tests use `server.MAX_TEXT` and `server.MAX_TEXT + 1`, not 280 and 281,
  so the next change of limit touches no test.
- `test_the_limit_is_560`: `self.assertEqual(server.MAX_TEXT, 560)`. One place that says the number
  on purpose, so a wrong edit is noticed.
- `test_an_emoji_counts_as_one_character`: a post of `"😀" * MAX_TEXT` is saved; `"😀" * (MAX_TEXT
  + 1)` raises `RuleBroken`.

**`RealServerTest`**
- `test_a_post_at_the_limit_gets_201_and_one_more_gets_400`: signed in, `POST /posts` with
  `MAX_TEXT` characters → 201; with `MAX_TEXT + 1` → 400 and the message names `560`.

**`JourneyTest`** — not needed. The feature has no new request and no new row.

**`PageAndServerAgreeTest`** (only those accounts has not already added). The tests cannot run the
page's JavaScript, and they cannot measure a height. So they check that the parts that must match
are written the same way in each file:
- `test_the_page_has_the_same_text_limit`: find `const MAX_TEXT = (\d+);` in `app.js` and compare
  it with `server.MAX_TEXT`.
- `test_the_page_counts_characters_as_python_does`: `app.js` contains `[...text].length`, and the
  post-text lines in `textProblem` and `updateCount` use `characterCount(`, not `.length`.
- `test_the_html_does_not_write_the_limit`: `index.html` has no `/ 280` or `/ 560`, and `app.js`
  calls `updateCount();` outside a function (at start-up).
- `test_a_long_post_is_folded_by_the_css_the_page_uses`: both `style.css` files have a
  `.post-text.collapsed` rule with `-webkit-line-clamp: 6`, `display: -webkit-box` and
  `overflow: hidden`, and a `.show-more` rule; `app.js` names the same two classes, `"collapsed"`
  and `"show-more"`.
- `test_the_show_more_button_is_accessible`: `app.js` makes the button with `type = "button"` and
  sets `aria-expanded` and `aria-controls`.
- `test_show_more_goes_through_the_timeline_click`: the body of `clickOnTimeline` names
  `.show-more`, and `showPost` calls `makeExpandable(`.

**By hand** (in `README.md` "Things to try"): post 560 characters, see 6 lines and **Show more**;
press it, then **Show less**; make the window narrow and see a shorter post fold; press Tab to reach
the button.

## 7. Docs to update

- `DESIGN.md` and `README.md`: 280 → 560 in the lines listed in section 3.
- `DESIGN.md`, a new short section **Long posts**: the limit lives in `MAX_TEXT` in `server.py` and
  in `app.js`, and a test fails if they differ; a character is a code point on both sides, so 😀 is
  1 and 👨‍👩‍👧 is 5; a post taller than 6 lines folds, measured by height on the page.
- `README.md` "Things to try": the hand checks in section 6.
- `AGENTS.md`: no change.

## 8. Not in this plan

- `page-only/`: keeps 280, its hand-written message in `page-only/app.js`, and `0 / 280` in
  `page-only/index.html`. Its `style.css` gets the new rules only to stay a copy; its page does not
  use them.
- Counting graphemes (👨‍👩‍👧 as 1).
- A database `CHECK` on text length (decision 4).
- The same `.length` mismatch in the account-name, display-name and password checks in `app.js`.
  Those limits are rarely reached with emoji; `characterCount` can be reused there later.
- Remembering which posts a reader opened, after a reload.

## 9. Size

**M.** About 70 lines of code (10 for the limit and the count, about 40 of JavaScript for Show
more, about 15 of CSS in each `style.css`), about 70 lines of tests, and about 20 lines of docs.
