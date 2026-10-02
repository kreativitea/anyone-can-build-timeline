Status: merged

# Classic style

## 1. What it does

The page takes on the *feel* of the classic light-blue microblog look of about 2009–2014: a soft
sky-blue page, all posts in one white card with thin lines between them, a round picture on the left
of each post, the name in bold with the @name and the time on the same line, and blue names and
links. Each post gets a coloured circle with the first letter of the person's name, because the app
has no pictures of people. Nothing new happens on the server: this plan only changes how the page
looks. The type stays large (24px), so the page can still be read from the back of a classroom.

It copies the feel only. There is no bird, no logo, no wordmark, no company name and no word
"tweet". The title stays **Timeline**, the label stays **What is happening?**, and every colour is
our own value, close to the classic one but not the same.

### What we looked at

You can open these pages yourself. The Wayback Machine (web.archive.org) keeps old copies of web
pages. Each link opens one saved copy.

| Page | What it shows |
|---|---|
| <https://web.archive.org/web/20090701021036/http://twitter.com/public_timeline> | 2009, the default theme. Pale blue page (`#9ae4e8`, with clouds), one white column with 5px round corners, a 200px light-green side column. Each post: a 48px picture placed on the left, the text pushed 65px to the right, the screen name **bold in link blue** (`#0084b4`) then the text on the same line, and a small grey line under it (`#999`, 11px) with the time. Dashed lines (`#d2dada`) between posts. Text `#333`, 14px. |
| <https://web.archive.org/web/20090618155139/http://twitter.com/twitter> | 2009, a profile page. The newest post is shown very large at the top; older posts are smaller below it, with the same dashed lines. |
| <https://web.archive.org/web/20101130232926/http://twitter.com/> | Late 2010, when the "New Twitter" two-pane design arrived. A thin dark strip at the very top, a wide blue header, then two columns: a narrow box on the left and the main list. (The posts themselves are loaded by a script and are blank in the saved copy. Pages from 2011 use `#!` addresses and do not open in the Wayback Machine at all.) |
| <https://web.archive.org/web/20130303004457/https://twitter.com/twitter> | 2012–2013. The clearest example of the post layout. All posts sit in **one white box** (round corners 6px, a faint edge). Between posts, one thin solid line (`#e8e8e8`). Each post: padding 9px top and bottom, 12px left and right; a 48px picture with 5px round corners, placed 12px from the top and left; the text starts 58px from the left. On one line: the **display name bold, dark** (`#333`, 14px), the @name grey and smaller (`#999`, 12px), and the time pushed to the right, light grey (`#bbb`, 12px). Text 14px on 18px lines, in Arial. When the mouse is over a post, its background turns very light grey (`#f5f5f5`) and the Reply / Retweet / Favorite links appear; they are hidden otherwise. A fixed dark bar across the top (`#252525`, 40px high, with a small shadow). The main button is blue (`#019ad2`, a light-to-dark gradient) with 4px corners and bold white text. Links are `#0084b4`. |
| <https://techcrunch.com/2010/09/14/the-new-twitter> | The news story about the 2010 redesign: the list of posts in one pane, and pictures and videos in a second pane at the side. |

Measurements in the table were read from the saved pages in a browser (the size and colour the
browser worked out for each part). No picture, logo or icon was copied.

### Two things the classic colours got wrong

Checked with the same contrast formula our `ColoursTest` uses (4.5 is the rule for text):

- The classic link blue `#0084b4` on white is **4.23**. Too faint for our rule.
- The classic grey `#999` for the @name and time on white is **2.85**. Much too faint, and far too
  faint for a projector.
- The thin line `#e8e8e8` on white is **1.23**. Our rule for edges is 3.

So our colours are a little darker than the classic ones. They keep the feel and pass the test.

## 2. Decisions for the owner

1. **A picture for each person: we have no photos. What goes in the round space?**
   - (a) A coloured circle with the **first letter of the display name** ("A" for Aiko Tanaka). The
     colour is one of six, chosen from the **account name**, so the same person always has the same
     colour, in every window and every browser.
   - (b) The same, but two letters (initials, "AT"). Harder for names with one word, or in Japanese.
   - (c) No circle. Only the other changes.
   - **Recommendation: (a).** The picture on the left is the biggest part of the classic feel, and
     a colour helps a reader find one person's posts fast. The account name never changes, so the
     colour never changes. The letter is from the display name, because that is the name people see.

2. **The list of posts: one card with lines between posts, or one card for each post (as today)?**
   - (a) **One card**, with a line between posts (2012–2013).
   - (b) Separate cards, as today, but with the other changes.
   - **Recommendation: (a).** It is the classic look, and it uses less space, so more posts fit on
     the screen.

3. **The lines between posts: how strong?**
   - (a) Use our `--border` colour, 2px. It passes the edge rule (3 or more).
   - (b) A new, fainter colour, nearer the classic `#e8e8e8`. It would not pass the edge rule, so the
     test would not check it.
   - **Recommendation: (a).** Space already separates the posts, but a faint line disappears on a
     projector. The orchestrator asked at `dark-mode` approval that edges can be seen.

4. **What colour are the names?**
   - (a) **Blue**, like a link (2009): `--author` becomes our blue. Everything that already uses
     `--author` turns blue with it: the names, the "Log out" link, the focus ring, the heart on hover,
     and the links and `#tags` from `links-and-tags`.
   - (b) The display name dark and bold, only links blue (2012). Needs a second colour token.
   - (c) Keep today's gold.
   - **Recommendation: (a).** One token change, and the page reads as "blue names, blue links",
     which is the classic feel. The @name and time stay grey.

5. **The top of the page.**
   - (a) A **coloured band** across the top of the page in our button blue, made in CSS only
     (`body { border-top: … }`). The title "Timeline" stays where it is.
   - (b) A fixed dark bar like 2012, with the title in it. Needs a change to `index.html`, near the
     same lines as `dark-mode` and `japanese`. A fixed bar also covers part of the screen on a
     projector and on a phone.
   - (c) Nothing.
   - **Recommendation: (a).** It gives the classic "header" signal with no HTML change.

6. **Buttons: round pill (today) or the classic rounded rectangle?**
   - (a) Rounded rectangle, 8px corners (the classic 4px, made larger with the larger type). Flat
     colour, no gradient.
   - (b) Keep the pill.
   - **Recommendation: (a).** It is closer to the classic feel. No gradient, because the lighter top
     of a gradient would make the white words harder to read.

7. **One column or two?** (The 2010 "New Twitter" had two.)
   - (a) **One column**, as today.
   - (b) Two columns on a very wide screen: the post box on the left, the posts on the right.
   - **Recommendation: (a).** With 24px type, two columns would make each post very narrow on a
     classroom projector (often 1280px wide). Two columns can be a later plan.

8. **On a phone.**
   - (a) Keep 24px type. Make the circle smaller (40px instead of 64px), and the space around each
     post smaller, so the text has room.
   - (b) The same, and also make the type 20px on a phone.
   - **Recommendation: (a).** The page should read the same everywhere, and the large type helps
     people who need it on a phone too.

9. **When the mouse is over a post.** Classic Twitter showed the Reply / Retweet / Favorite links only
   then.
   - (a) The post's background turns a very light blue (a new `--hover` colour). The heart **always**
     shows.
   - (b) Also hide the heart until the mouse is over the post (classic).
   - **Recommendation: (a).** A phone has no mouse, a keyboard user has no "over", and a person at
     the back of the room should see the hearts. The hover colour is used only where a mouse can
     hover (`@media (hover: hover)`).

## 3. Design

**Database, model, routes, view, `server.py`:** no change.

### 3.1 How the large type keeps the classic proportions

The classic post was built on 14px text. Ours is 24px. We keep the *proportions*, not the pixel
sizes, rounding to sizes that read well:

| Part | Classic (2012–13) | Ratio to the text | Ours (wide screen) | Ours (phone, under 600px) |
|---|---|---|---|---|
| Post text | 14px on 18px lines | 1 | 24px, line height 1.4 (no change) | the same |
| Display name | 14px bold | 1 | 24px bold (no change) | the same |
| @name and time | 12px | 0.86 | 0.85em (about 20px) | the same |
| Picture | 48px, corners 5px | 3.4 | **64px circle** | **40px circle** |
| Space from the left edge to the text | 58px | 4.1 | 20px + 64px + 16px = **100px** | 12px + 40px + 12px = **64px** |
| Padding of a post | 9px / 12px | — | 16px / 20px | 12px / 12px |
| Line between posts | 1px `#e8e8e8` | — | 2px `--border` | the same |
| Corners of the list card | 6px | — | 12px (as today) | the same |
| Button corners | 4px | — | 8px | the same |

The picture is a little smaller than a strict ratio (64px, not 82px), so the text keeps a wide
column at 24px.

### 3.2 The colours (the `:root` block at the top of `style.css`)

Every value is our own, close to the classic one, and every one is written as
`light-dark(LIGHT, DARK)` in lower case, so `ColoursTest` reads it. Classic Twitter had no dark mode
(that came in 2016), so the dark values are a night-blue version of the same feel.

| Token | Classic | Light (new) | Dark (new) | Changed? |
|---|---|---|---|---|
| `--background` | `#c0deed` (2010), `#9ae4e8` (2009) | `#c6e2ef` | `#0e1a23` | change |
| `--card` | `#ffffff` | `#ffffff` | `#16283a` | change (dark only) |
| `--text` | `#333333` | `#262c31` | `#e7eef3` | change |
| `--quiet` | `#999999` | `#4d5961` | `#a3b6c4` | change |
| `--author` | `#0084b4` (links) | `#0a6694` | `#6ec3ef` | change |
| `--button` | `#019ad2` | `#1d6fa8` (as today) | `#1d6fa8` (as today) | no |
| `--button-text` | white | `#ffffff` | `#ffffff` | no |
| `--warning` | — | `#b3261e` (as today) | `#ff8a7a` (as today) | no |
| `--border` | `#e8e8e8` | `#5f7d8c` | `#62819a` | change |
| `--hover` *(new)* | `#f5f5f5` | `#eef6fa` | `#1d3448` | add |
| `--avatar-1` … `--avatar-6` *(new)* | — | see below | the same as light | add |

The six circle colours, with a white letter: `#1d6fa8` blue, `#8a4fb0` purple, `#b0413e` red,
`#2e7d4f` green, `#9a5800` brown, `#2f6f7a` teal. They are written
`light-dark(#1d6fa8, #1d6fa8)`, like `--button`, because a white letter reads on them in both modes.

Contrast, worked out with the `ColoursTest` formula (all must be 4.5 or more for text, 3 for edges):

| Pair | Light | Dark |
|---|---|---|
| `--text` on background / card / hover | 10.44 / 14.12 / 12.91 | 15.05 / 12.81 / 10.95 |
| `--quiet` on background / card / hover | 5.32 / 7.20 / 6.58 | 8.44 / 7.18 / 6.14 |
| `--author` on background / card / hover | 4.65 / 6.29 / 5.75 | 9.00 / 7.66 / 6.55 |
| `--warning` on background / card / hover | 4.83 / 6.54 / 5.98 | 7.70 / 6.55 / 5.60 |
| `--button-text` on `--button` | 5.40 | 5.40 |
| `--border` on background / card / hover | 3.24 / 4.38 / 4.00 | 4.31 / 3.66 / 3.13 |
| white on each avatar colour | 5.40, 5.49, 5.72, 5.05, 5.57, 5.71 | the same |

### 3.3 The page (`app.js`)

One new part, added with one `addPostPart(...)` call at the end of the parts. `makePostItem` does
not change.

- `avatarColour(accountName)` *(add)*: adds up the character codes of the account name and returns
  a number from 1 to 6. The same name always gives the same number.
- `avatarPart(post, slots, item)` *(add)*: makes `<span class="avatar avatar-colour-N"
  aria-hidden="true">A</span>` and puts it first in `slots.head`. The letter is
  `Array.from(post.display_name)[0].toUpperCase()` (`Array.from` keeps an emoji or a rare character
  in one piece). It is written with `textContent`, never `innerHTML`. `aria-hidden="true"` means a
  screen reader skips it, because the name comes right after it. It also adds the class
  `with-avatar` to the post's `<li>`, so the CSS makes room for the circle only when there is one.
  (`page-only/` has no avatar part. It shares `style.css`, and without `with-avatar` its posts are
  laid out with no empty space on the left.)

Because the part is added in `makePostItem`'s list, the circle also appears in every other list
built with `makePostItem` (search results, bookmarks, replies).

### 3.4 The look (`style.css`)

**Existing rules that change: only the `:root` block** (the token values in 3.2, plus the new
tokens). Nothing else above the new block is edited. Every other change is a new rule in a
`/* classic-style */` block at the end, which wins because it comes later:

```css
/* classic-style: the feel of the classic light-blue microblog look. */

/* A band of colour across the top of the page (decision 5). */
body { border-top: 10px solid var(--button); }

/* Buttons: rounded rectangles, not pills (decision 6). The heart keeps its own shape. */
button { border-radius: 8px; }

/* The post box sits in a card, like the classic box at the top of the list. */
#post-form {
  padding: 16px 20px;
  border: 2px solid var(--border);
  border-radius: 12px;
  background: var(--card);
}

/* All posts in one card, with a line between them (decisions 2 and 3).
   An empty list shows no card. */
.timeline:not(:empty) {
  border: 2px solid var(--border);
  border-radius: 12px;
  background: var(--card);
  overflow: hidden;
}

.post {
  position: relative;
  margin: 0;
  padding: 16px 20px;
  border: none;
  border-bottom: 2px solid var(--border);
  border-radius: 0;
}

.post:last-child { border-bottom: none; }

/* Room on the left for the circle, only when the post has one. */
.post.with-avatar { padding-left: 100px; }

.avatar {
  position: absolute;
  top: 16px;
  left: 20px;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--button-text);
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
}

.avatar-colour-1 { background: var(--avatar-1); }
/* … the same for 2 to 6 … */

/* The @name and the time: smaller and grey, on the same line as the name. */
.post-handle,
.post-time { font-size: 0.85em; }

.post-handle { margin-left: 8px; }

/* The time on the right of the first line. */
.post-time { float: right; }

/* A light tint under the mouse, only where there is a mouse (decision 9). */
@media (hover: hover) {
  .post:hover { background: var(--hover); }
}

/* On a phone (decision 8). */
@media (max-width: 600px) {
  .post { padding: 12px; }
  .post.with-avatar { padding-left: 64px; }
  .avatar { top: 12px; left: 12px; width: 40px; height: 40px; font-size: 20px; }
}
```

About 90 lines with comments. The same block goes at the end of `page-only/style.css`, which must
stay a copy (an existing test checks it).

Why overriding works without editing: `.post`, `.post-handle`, `.post-time` and `button` above have
the same weight as the new rules, and the later rule wins. `.link-button` (radius 0) has more weight
than `button`, so "Log out" stays a plain link. The slots (`.post-head` etc.) stay
`display: contents`, so the circle, placed with `position: absolute` against the `<li>`, needs no
change to groundwork.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/style.css` | `:root` block: new values for `--background`, `--card`, `--text`, `--quiet`, `--author`, `--border` | change |
| `with-backend/style.css` | `:root` block: new tokens `--hover`, `--avatar-1` … `--avatar-6` (at the end of the block) | add |
| `with-backend/style.css` | `/* classic-style */` block at the end | add |
| `page-only/style.css` | the same two changes (it stays a copy) | change / add |
| `with-backend/app.js` | `avatarColour`, and `addPostPart(function avatarPart …)` after the existing parts | add |
| `with-backend/test_server.py` | `ColoursTest`: two new methods at the end of the class | add |
| `with-backend/test_server.py` | new class `ClassicStyleTest`, at the end, before `if __name__` | add |
| `AGENTS.md` | file table: one sentence each on `style.css` and `app.js` | change |
| `docs/plans/README.md` | the plans table: one row for `classic-style` | add |
| `with-backend/server.py`, `index.html`, `page-only/index.html`, `page-only/app.js` | — | not touched |

## 5. Depends on, and collides with

**Depends on `dark-mode`** (the `light-dark()` tokens and `ColoursTest`) and **`groundwork`**
(`addPostPart`, the slots, `makePostItem`). Both are merged.

**Collides with:**

- **Every plan that adds a CSS block at the end** (`bookmarks`, `block`, `edit-delete`, `pictures`,
  `long-posts`, `replies`, `japanese`, `search`, `links-and-tags`, `timeline-flow`, `place`,
  `timestamps`, `reply-email`): only an easy rebase at the end of the file. One real effect: the
  classic block is a set of overrides, so **merge it last among the look changes, or check after
  each rebase** that a later block does not set `.post` borders again.
- **`replies`**: a reply list sits inside a post. A nested `.post` will also get the line and the
  circle. The `.replies` indent should add to the 100px, not replace it. Check together when both
  have landed.
- **`timestamps`**: the time becomes "5 minutes ago" and may be wrapped in `<time>`. It still has the
  class `post-time`, so the float right still works.
- **`links-and-tags`**: its links use `--author`, so they turn blue with decision 4 (a). Good.
- **`pictures`**: the picture is inside the post text column, so it lines up with the text, as in
  the classic layout. Nothing to do.
- **Any plan that adds a colour** to `:root`: both add lines at the end of the same block. An easy
  rebase.
- **`japanese`**: no new words (the circle is `aria-hidden` and shows a letter of a name). Its font
  list in `body` is not touched here.

## 6. Tests

No server change, so no new `ModelTests`, `RealServerTest` or `JourneyTest`.

**`ColoursTest`, two new methods at the end** (they use the class's existing `check_contrast`):

- `test_text_is_easy_to_read_on_a_hovered_post`: `--text`, `--quiet`, `--author` and `--warning` on
  `--hover`, 4.5 or more, and `--border` on `--hover`, 3 or more, in both modes.
- `test_the_letter_in_each_circle_is_easy_to_read`: `--button-text` on each `--avatar-1` …
  `--avatar-6`, 4.5 or more, in both modes.

The existing tests also check the new tokens: each is in `light-dark()` form, and every `var(--…)`
used is defined.

**New class `ClassicStyleTest`** (reads files as text; no server, no browser):

- `test_there_is_one_colour_rule_for_each_avatar_colour`: `style.css` has `.avatar-colour-1` to
  `.avatar-colour-6`, and `app.js` picks a number from 1 to 6 (`% 6`).
- `test_the_avatar_is_added_as_a_part`: `app.js` has `addPostPart(function avatarPart` and
  `makePostItem` is unchanged in shape (still builds slots and runs parts).
- `test_the_avatar_is_hidden_from_screen_readers_and_written_as_text`: in `avatarPart`,
  `aria-hidden` and `textContent`, and no `innerHTML`.
- `test_room_for_the_avatar_only_when_there_is_one`: the padding for the circle is on
  `.post.with-avatar`, not on `.post`, so `page-only/` has no empty space.
- `test_nothing_names_the_company`: `index.html`, `style.css` and `app.js` contain none of
  "twitter", "tweet", "retweet" (any case). This keeps the "feel only" promise.

`PageAndServerAgreeTest`: no change (no new request).

## 7. Docs to update

- `AGENTS.md`, the file table: `style.css` "how the screen looks: the classic light-blue feel, all
  posts in one card"; `app.js` "each post shows a coloured circle with the first letter of the
  name".
- `docs/plans/README.md`: one row in the plans table, `classic-style` · "The feel of the classic
  light-blue microblog look".

## 8. Not in this plan

- Real profile pictures (that would be like `pictures`, but for accounts).
- A circle next to "Signed in as" for the person using the page.
- Two columns (decision 7 b), a fixed top bar (decision 5 b), hiding the heart until hover
  (decision 9 b).
- The very large newest post of the 2009 profile page.
- A Retweet or Reply link styled like the classic ones (`replies` owns replying).
- Changing the font. Classic used Lucida Grande, then Arial; we keep `system-ui`, and `japanese`
  adds Japanese fonts.
- Any logo, bird, cloud background, wordmark or the company's name.

## 9. Size

**S.** About 200 lines: `style.css` about 100 (10 in `:root`, 90 in the new block), and the same in
`page-only/style.css`; `app.js` about 30; `test_server.py` about 60; docs about 5.

## Changes made at approval (orchestrator)

- All nine decisions approved as recommended.
- **Also: a clear "turned off" look for buttons** (`button:disabled`), in both modes. `rate-limit`
  holds the Post button for some seconds, and in dark mode it looked the same as an active one.
- Built after the features that draw posts (`replies`, `place`, `pictures`), so it styles them all.
- Visible words follow the words contract (`docs/plans/README.md`): the circle has no words; any
  label is a key in `words.js`.
