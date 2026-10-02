Status: built on branch dark-mode, awaiting merge

# Dark mode

## 1. What it does

A small **Colours** switch at the top of the page has three choices: **Auto**, **Light** and
**Dark**. Auto follows the computer, as the page does today. Light and Dark stay the same whatever
the computer says. The choice is remembered in this browser, so it is still there after the tab is
closed or the computer restarts. It is not shared with other browsers or other devices.

## 2. Decisions for the owner

Already agreed: the choice is kept in **`localStorage`** (storage in the browser that stays after
the tab closes), and the server does not change. Syncing the choice across devices would need the
server, so it is out of scope.

1. **How should `style.css` hold the two sets of colours?**
   - **A. `light-dark()` (recommended).** Each colour is written once, as a pair:
     `--text: light-dark(#002b36, #eee8d5);` (light first, then dark). The browser picks one half
     of the pair from the `color-scheme` property. Auto needs no media query at all. Nothing is
     copied, so the light and dark colours can never drift apart. Bonus: the browser's own parts
     (the scroll bar, the arrow on the switch) also change colour. Cost: `light-dark()` is newer
     (all main browsers since May 2024). In an older browser the colours are missing, and the page
     falls back to plain black text on white: still readable, not pretty.
   - **B. Three blocks of the usual kind.** Dark in one block, light in a second block, and the
     same light colours again in a third block inside `@media (prefers-color-scheme: light)`. It
     works in every browser, but the light colours are written twice, and a test must check that
     the two copies agree.

   Exact selectors for each option are in section 3.

2. **What kind of control?**
   - **A `<select>` with a `<label>` (recommended).** One line of HTML per choice. Every browser
     and every screen reader already knows how to use it: a keyboard user presses Tab, then the
     arrow keys. It takes very little room.
   - Three radio buttons in a `<fieldset>`. All three choices can be seen at once, but it needs more
     HTML and more CSS to look tidy.

3. **Where does the switch go?**
   - **Just under the title, outside the signed-in and signed-out parts (recommended).** Anyone can
     use it, signed in or not.
   - Next to "Log out". It would only show for a signed-in person, but colours have nothing to do
     with an account.

4. **What does a first visit get?**
   - **Auto (recommended).** The same as today: the page follows the computer.
   - Dark, as the CSS default is today when the computer gives no preference. (Almost every
     computer and phone does give one now, so in practice A and B look the same.)

## 3. Design

**Database, model, routes, view:** no change. `server.py` already sends `index.html`, `style.css`
and `app.js` (its `PAGE_FILES`), and this plan adds no new file, so `server.py` is not touched.

### The one stored value

| Where | Key | Value |
|---|---|---|
| `localStorage` of this browser, for this address | `timeline-theme` | `"light"` or `"dark"`. **Auto is no key at all**: choosing Auto removes the key. |

`localStorage` belongs to one address. `http://localhost:8009` and `http://127.0.0.1:8009` are two
different addresses to the browser, so each remembers its own choice. That is expected.

Any other value found in storage (an old value, or one typed by hand in the developer tools) is
treated as Auto. A stored value is only ever compared with `"light"` and `"dark"`; it is never put
into the page as it is.

### The page tells the CSS which colours to use: `data-theme`

The page sets one attribute on the `<html>` element:

- `<html data-theme="light">` — Light was chosen.
- `<html data-theme="dark">` — Dark was chosen.
- no `data-theme` at all — Auto.

### `style.css`, option A (recommended)

The block at the top, "The colours, in one place", is replaced by this. The media query block
below it is deleted. The other rules in the file do not change: they still say `var(--text)` and
so on.

```css
/* The colours, in one place. Each colour is written once, as
   light-dark(LIGHT, DARK). The browser uses the first one when the page is in
   light mode and the second one in dark mode.
   "light dark" means: follow the computer. That is the Auto choice, and it is
   what page-only/ always uses, because it has no switch. */
:root {
  color-scheme: light dark;
  --background: light-dark(#fdf6e3, #002b36);
  --card: light-dark(#ffffff, #073642);
  --text: light-dark(#002b36, #eee8d5);
  --quiet: light-dark(#4f5f63, #a7b5b5);
  --author: light-dark(#7a5a00, #e6b422);
  --button: light-dark(#1d6fa8, #1d6fa8);
  --button-text: light-dark(#ffffff, #ffffff);
  --warning: light-dark(#b3261e, #ff8a7a);
  --border: light-dark(#93a1a1, #586e75);
}

/* Light or Dark chosen by hand with the Colours switch (with-backend/ only).
   Each one only changes color-scheme; the colours above follow by themselves. */
:root[data-theme="light"] {
  color-scheme: light;
}

:root[data-theme="dark"] {
  color-scheme: dark;
}
```

The colour values are exactly today's values: the same two sets, now side by side.

### `style.css`, option B (if the owner picks it)

```css
/* Dark: the default, and the choice "Dark". */
:root,
:root[data-theme="dark"] {
  --background: #002b36;  /* … all nine dark colours, as today … */
}

/* Light: the choice "Light". */
:root[data-theme="light"] {
  --background: #fdf6e3;  /* … all nine light colours … */
}

/* Light: the choice "Auto" on a computer set to light mode.
   Keep these the same as the block above; a test checks it. */
@media (prefers-color-scheme: light) {
  :root:not([data-theme]) {
    --background: #fdf6e3;  /* … the same nine light colours again … */
  }
}
```

`:root:not([data-theme])` means "the page, when no choice was made by hand", so the media query
only acts on Auto.

### `style.css`, new rules at the end (either option)

```css
/* dark-mode: the Colours switch under the title. Only with-backend/ has it,
   but both copies of this file stay the same. */
.theme-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin: -8px 0 16px;
}

.theme-row label {
  margin: 0;
}

.theme-row select {
  padding: 6px 12px;
  border: 2px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  color: var(--text);
  font: inherit;
}

.theme-row select:focus {
  outline: 3px solid var(--author);
  outline-offset: 2px;
}
```

### `with-backend/index.html`

**1. A tiny script in `<head>`, before the `<link rel="stylesheet">`.** A script in `<head>` runs
before the browser draws anything. So the right colours are there from the very first moment, and
the page never flashes dark and then turns light (a "flash of the wrong colours"). It is inline (in
the HTML file itself, not in `app.js`), because `app.js` is loaded at the end of `<body>`, which is
too late.

```html
  <script>
    // Before the page is drawn: use the colours chosen in this browser, if any.
    // The same key and the same two values as savedTheme() in app.js.
    try {
      var theme = localStorage.getItem("timeline-theme");
      if (theme === "light" || theme === "dark") {
        document.documentElement.dataset.theme = theme;
      }
    } catch (error) {
      // Storage can be blocked (some private windows). Then follow the computer.
    }
  </script>
  <link rel="stylesheet" href="style.css">
```

`try` / `catch` matters: in some browsers, only *reading* `localStorage` already throws an error
when storage is blocked. Without `catch`, that error would stop the script, and the page would
still work but always follow the computer. With it, the same thing happens on purpose and quietly.

**2. The switch, just after `<h1>Timeline</h1>`** (outside both `<section>`s):

```html
    <div class="theme-row">
      <label for="theme">Colours</label>
      <select id="theme">
        <option value="auto">Auto (follow this computer)</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </div>
```

Accessibility: the `<label for="theme">` gives the switch its name, so a screen reader says
"Colours, Auto (follow this computer), pop-up button" (the words vary by reader). No `aria-` words
are needed, because a native `<select>` already says what it is and what is chosen. The visible
word "Colours" is the same as the spoken name.

### `with-backend/app.js`

Three new functions and two new lines at the start-up at the bottom. Nothing else changes.

```js
// The key for the Colours choice in localStorage. The same key as the small
// script in index.html, which uses it before the page is drawn.
const THEME_KEY = "timeline-theme";
const themeSwitch = document.getElementById("theme");

// The choice saved in this browser: "light", "dark", or "auto" when there is
// none (or storage is blocked, or it holds something else).
function savedTheme() {
  try {
    const theme = localStorage.getItem(THEME_KEY);
    if (theme === "light" || theme === "dark") {
      return theme;
    }
  } catch (error) {
    // Storage is blocked: nothing was saved.
  }
  return "auto";
}

// Tell the CSS which colours to use. Auto is no data-theme at all.
function useTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
  } else {
    delete document.documentElement.dataset.theme;
  }
}

// The Colours switch changed: use the new colours now, and remember them.
function chooseTheme() {
  const theme = themeSwitch.value;
  useTheme(theme);
  try {
    if (theme === "light" || theme === "dark") {
      localStorage.setItem(THEME_KEY, theme);
    } else {
      localStorage.removeItem(THEME_KEY);
    }
  } catch (error) {
    // Storage is blocked: the colours still change in this tab, but are not
    // remembered. Nothing to tell the person; it is not their mistake.
  }
}
```

At the start-up, next to the other `addEventListener` lines:

```js
themeSwitch.value = savedTheme();
themeSwitch.addEventListener("change", chooseTheme);
```

The constants go with the other constants at the top; the functions go just before
`clickOnTimeline`, so they sit together.

### `page-only/`

`page-only/style.css` is replaced by an exact copy of `with-backend/style.css`. `page-only/index.html`
and `page-only/app.js` do not change. The page-only page has no script in `<head>` and no switch,
so `<html>` never has `data-theme`: it is always Auto and follows the computer, the same as today.
The `.theme-row` rules are simply never used there, like `.account-forms` and `.like` today.
Check by hand: open `page-only/index.html`, switch the computer between light and dark mode, and
see the page follow.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/style.css` | "The colours, in one place" block at the top, and the `@media (prefers-color-scheme: light)` block under it | change (replace both with the block in section 3) |
| `with-backend/style.css` | `/* dark-mode */` rules `.theme-row`, `.theme-row label`, `.theme-row select`, `.theme-row select:focus` at the end | add |
| `page-only/style.css` | whole file | change (an exact copy of `with-backend/style.css`) |
| `with-backend/index.html` | inline `<script>` in `<head>`, before `<link rel="stylesheet">` | add |
| `with-backend/index.html` | `<div class="theme-row">` with `<label for="theme">` and `<select id="theme">`, just after `<h1>` | add |
| `with-backend/app.js` | constants `THEME_KEY`, `themeSwitch` | add |
| `with-backend/app.js` | `savedTheme`, `useTheme`, `chooseTheme` | add |
| `with-backend/app.js` | start-up lines at the bottom: `themeSwitch.value = savedTheme();` and the `change` listener | add (two lines) |
| `with-backend/test_server.py` | new class `ColoursTest`, at the end, before `if __name__` | add |
| `with-backend/test_server.py` | `RealServerTest.test_the_served_page_has_the_colours_switch`, at the end of the class | add |
| `with-backend/server.py` | — | not touched |
| `page-only/index.html`, `page-only/app.js` | — | not touched |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new lines / sections (see section 7) | add |

## 5. Depends on, and collides with

**Depends on `accounts`.** The plan is written against the accounts `index.html` (the two
`<section>`s after `<h1>`) and the accounts start-up lines at the end of `app.js`. It also leans on
the accounts test that both `style.css` files are the same; if that test is not there when this is
built, `ColoursTest` adds it.

**Collides with:**

- **Every plan that adds a colour** (likely `links-and-tags`, `report`, `pictures`, `who-liked`,
  `block`). This plan changes the shape of the colour block. A new colour must be written as
  `--name: light-dark(LIGHT, DARK);` inside `:root` (option A), or in all three blocks (option B).
  `ColoursTest` fails if a colour is missing its light or dark value. **Build `dark-mode` early**,
  so later plans add colours in the new shape; if one lands first, this branch converts its colour
  when it rebases.
- **`japanese`**: "Colours", "Auto (follow this computer)", "Light" and "Dark" are new words to
  translate. The `value`s (`auto`, `light`, `dark`) and the storage key are not translated.
- **`drafts`**: also uses browser storage from `app.js`, and also adds start-up lines at the end.
  Different keys (`timeline-theme` is ours), so only a small line-level merge.
- **`search`, `timeline-flow`**: may add something near the top of `index.html`, just after `<h1>`,
  the same spot as the switch. A small merge; the switch stays directly under the title.
- **All plans:** new CSS at the end of `style.css`. Each block has its own slug comment, so a merge
  only puts the blocks one after another.

## 6. Tests

The page's JavaScript is never run by the tests (that needs a browser). But Python can read
`style.css`, `index.html` and `app.js` as text, and check the things that would break quietly.

**`ModelTests`:** none. No model change.

**`RealServerTest`** (one new method at the end):

- `test_the_served_page_has_the_colours_switch`: `GET /` from the real server holds
  `id="theme"` and `localStorage.getItem("timeline-theme")`, so the page the server sends is the new
  one.

**`JourneyTest`:** none. The choice never reaches the server or the database, so there is no
journey through three levels. (One could add a check that the database has no new table, but the
other tests already list the tables.)

**`PageAndServerAgreeTest`:** no change. The page makes no new request, so the existing checks
("the page asks for nothing but…", "the page names only the methods…") must still pass as they are.

**New class `ColoursTest`** (reads files; no server):

- `test_every_colour_has_a_light_and_a_dark_value`: every `--name:` line in the `:root` block is
  `light-dark(#xxxxxx, #xxxxxx)`. (Option B instead: the three blocks name the same colours, and the
  two light blocks are equal.)
- `test_every_colour_used_is_defined`: every `var(--name)` in `style.css` is one of the colours in
  `:root`. A typo such as `var(--txet)` fails here instead of quietly showing no colour.
- `test_text_is_easy_to_read_in_both_modes`: Python works out the contrast ratio (the WCAG formula
  for how different two colours are; 4.5 or more is the rule for normal text) of each pair, in the
  light set and in the dark set, and every one must be 4.5 or more:
  `--text` on `--background` and on `--card`; `--quiet`, `--author` and `--warning` on
  `--background` and on `--card`; `--button-text` on `--button`. Today's colours pass: the lowest
  is 5.4 (white on the blue button). About 12 lines of Python, standard library only.
- `test_there_are_exactly_three_choices`: the `<option value="…">`s in `index.html` are exactly
  `auto`, `light`, `dark`; `style.css` has `:root[data-theme="light"]` and
  `:root[data-theme="dark"]`.
- `test_the_choice_is_used_before_the_page_is_drawn`: in `index.html`, the script that reads
  `localStorage` is inside `<head>`, comes before `<link rel="stylesheet"`, and has `try` and
  `catch`.
- `test_the_head_script_and_app_js_agree`: the key `"timeline-theme"` appears in both `index.html`
  and `app.js`, and both compare with `=== "light"` and `=== "dark"` (the same values on both
  sides, the way the page and server share their rules).
- `test_the_switch_has_a_label`: `index.html` has `<label for="theme">` and `<select id="theme">`.
- `test_page_only_follows_the_computer`: `page-only/index.html` has no `data-theme` and no
  `localStorage`, and `style.css` sets `color-scheme: light dark` on `:root` (option B: has the
  `prefers-color-scheme` block). So the page-only page still follows the computer.
- `test_both_style_files_are_the_same`: only if `accounts` did not already add it.

**By hand** (in the README's "Things to try"): choose Dark, reload, close and reopen the tab: still
dark, and no flash of light on reload. Choose Auto and switch the computer's mode: the page follows.
Open a private window that blocks storage: the switch still works for that tab.

## 7. Docs to update

- `AGENTS.md`, the file table: `index.html` gains "a tiny script in `<head>` that sets the colours
  before the page is drawn, and the Colours switch"; `style.css` gains "each colour written once
  for light and dark"; `app.js` gains "remembers the Colours choice in `localStorage`". Add one line
  under the table: the choice is the only thing the page keeps in `localStorage`, and it never goes
  to the server.
- `DESIGN.md`, section 3 (Screens): add one paragraph about the Colours switch and the three
  choices. Section 2 stays as it is.
- `README.md`, "Things to try": a new item. Choose Dark, reload. Then open the browser's developer
  tools, find Local Storage, see `timeline-theme`, and delete it: the page goes back to Auto. A good
  way to compare `localStorage` (stays) with the `sessionStorage` that `page-only/` uses (one window
  only).

## 8. Not in this plan

- Keeping the choice in the account, so it follows a person to another device (needs the server).
- A switch in `page-only/`. It is a demo and is not changed; it follows the computer.
- Changing the colours themselves. They are today's two sets, unchanged. (Seen while planning: the
  `--border` colour is about 2.4 to 2.8 against the background, under the 3 to 1 that WCAG asks for
  the edge of a box or button. A separate small fix, if wanted.)
- Telling other open tabs at once when the choice changes (the `storage` event). Each tab picks up
  the new choice when it is next opened or reloaded.
- More themes (high contrast, sepia).

## 9. Size

**S.** About 170 lines in all: `style.css` about 40 (the colour block changes, the new rules are
added), `index.html` about 20, `app.js` about 45, `test_server.py` about 90 (mostly
`ColoursTest`), docs about 15. Option B adds about 15 more lines of CSS.

## Changes made at approval (orchestrator)

- All four decisions approved as recommended (option A, `light-dark()`).
- **Also fix the faint edges in this plan.** `--border` gets a value with at least 3:1 contrast
  against the background and the cards in both modes, and the contrast test checks it.
- Build this early in step 3: later plans that add a colour use the `light-dark()` form.
