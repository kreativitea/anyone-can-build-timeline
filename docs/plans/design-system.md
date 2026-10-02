Status: built on branch design-system, awaiting merge

# Design system

Written by the orchestrator, at the owner's request: "add a design system so the design stays
modular". It comes before `classic-layout`, which then becomes mostly a change of values.

## 1. What it does

Nothing changes on screen. The look is rebuilt from a small, named set of parts, so every feature
uses the same sizes, spaces, corners and buttons, and the whole look can be changed in one place.
A **design system** is three things here: **tokens** (named values, like `--space-3` or
`--text-small`), **components** (a few shared pieces, like a card or a button, each with one
class), and **rules** that `make test` checks, so the system stays in use.

Today the colours are already tokens (from `dark-mode`). Everything else is scattered: 190 raw
pixel values (26 different ones), 13 separate font sizes and 7 corner styles, across 17 feature
blocks of `style.css`.

## 2. Decisions for the owner (recommendation first)

1. **Files.** *Split `style.css` into a few files, loaded in order (recommended):*
   `tokens.css` (every token), `base.css` (the page and its elements), `components.css` (the
   shared pieces), `features.css` (each feature's own small block, under its slug). No build
   step: `index.html` links the four, and `PAGE_FILES` serves them. `page-only/` links the same
   four files, so "the two style.css files are identical" becomes one shared set. *Or:* keep one
   `style.css` with the same four sections in order (CSS `@layer`).
2. **A style guide page.** *Yes (recommended):* `/design.html`, served by the server, shows every
   token and every component, in light and dark, with sample posts. It is the place to look
   before adding a feature, and the place the browser check looks to see the whole system at
   once. It uses only the real CSS files. *Or:* only a written reference in `DESIGN.md`.
3. **How strict the tests are.** *Strict (recommended):* outside `tokens.css`, `make test` refuses
   a raw colour, a raw font size, a raw corner radius or a raw spacing value in `px`. A one-pixel
   hairline and `0` are allowed. *Or:* a warning list only.

## 3. Design

### Tokens (`tokens.css`)

All values are chosen to give **exactly today's look** (the screenshots before and after must
match); `classic-layout` then changes only values.

| Group | Tokens |
|---|---|
| Colour | the existing `light-dark()` tokens, unchanged |
| Type | `--font-family`; sizes `--text-small`, `--text-body`, `--text-large`, `--text-title`; `--line-height`; weights `--weight-normal`, `--weight-bold` |
| Space | `--space-1` … `--space-6` (a scale; today's 26 pixel values map to it) |
| Corners | `--radius-small`, `--radius`, `--radius-large`, `--radius-pill`, `--radius-round` (today's 7 become these 5) |
| Lines | `--line-thin` (hairline), `--line` (2px edges, the 3:1 contrast edge) |
| Sizes | `--avatar`, `--avatar-small`, `--avatar-indent`, `--control-height`, `--page-width` |
| Layers and motion | `--layer-sticky` (the new-posts button, later the top bar), `--focus-ring` |

### Components (`components.css`)

Each is one class (with a few modifiers), documented with its parts and states:

| Component | What it is | Used by today |
|---|---|---|
| `.button` (`.button-primary`, `.button-quiet`, `.button-link`, `.button-pill`) | every button; disabled and focus states once | everywhere |
| `.field` | a label and its input, with its hint and count | log in, sign up, post box, place, picture, email, search |
| `.card` | a box with the edge colour and corners | forms, the timeline card, Email, Blocked accounts |
| `.avatar` | the letter circle (sizes by token) | posts, replies, later the profile card |
| `.post` | the post's anatomy: `head`, `body`, `foot`, `menu` slots (groundwork's), and its states `deleted`, `hidden-by-reports`, `reply` | every list of posts |
| `.menu` | the ⋯ menu | block, report, edit-delete |
| `.tabs` | a row of view buttons, one current | the views nav (later in the top bar) |
| `.count` | a small number beside an icon or in a line | hearts, replies, character count |
| `.status` | a one-line message (`.status-error`, `.status-quiet`) | status line, empty lists |
| `.disclosure` | a `<details>` box | Email, Blocked accounts |

### Feature CSS (`features.css`)

Each feature keeps its own block under its slug comment, but it may only **arrange** components
and use tokens; it doesn't make new buttons, cards or sizes. Blocks that do today are moved to use
the components. `app.js` adds component classes where it builds elements (e.g. `button button-pill`
on the heart), which is a class-name change only.

### Rules checked by `make test` (a new `DesignSystemTest`)

- Outside `tokens.css`: no colour literal, no raw `font-size`, `border-radius`, `margin`, `padding`
  or `gap` in `px` (only `0`, `1px` hairlines and tokens).
- Every `var(--x)` used is defined in `tokens.css`; every token defined is used somewhere.
- Every component class in `components.css` appears on `/design.html`, and the guide links only
  the real CSS files.
- The existing colour, contrast and "no company name" tests keep passing.
- `page-only/` and `with-backend/` load the same CSS files.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/tokens.css`, `base.css`, `components.css`, `features.css` | new (from today's `style.css`) | add |
| `with-backend/style.css`, `page-only/style.css` | removed (split into the four) | change |
| `with-backend/index.html`, `page-only/index.html` | the four `<link>`s instead of one | change |
| `with-backend/design.html` | the style guide | add |
| `with-backend/server.py` | `PAGE_FILES` lists the new files | change |
| `with-backend/app.js` | component class names where elements are built | change (class names only) |
| `with-backend/test_server.py` | `DesignSystemTest`; the tests that read `style.css` read the four files | add, change |
| `AGENTS.md`, `DESIGN.md`, `README.md` | the design system, its rules, the style guide | add, change |

## 5. Depends on, and collides with

Depends on everything merged. Nothing else is being built. **`classic-layout` is built after it**,
and changes token values plus one layout component (`.columns`, the top bar).

## 6. Tests

`DesignSystemTest` (above), plus: every test that read `style.css` now reads the four files; the
page looks the same — checked in the browser by comparing screenshots before and after, in light
and dark, wide and phone width, with posts, a reply thread, a deleted post, a picture, the menus
and every form.

## 7. Docs

`DESIGN.md`: a "Design system" section (tokens, components, rules, and how to add a feature's
style). `AGENTS.md`: "use components and tokens; never a raw value; look at `/design.html`
first", and the file table. `README.md`: open `/design.html`.

## 8. Not in this plan

Any visible change. New components nobody uses yet. A build step or CSS library.

## 9. Size

**M–L.** About 600 lines moved and tidied (most of it existing CSS), 150 for the style guide,
120 for tests.

## Changes made at approval (owner)

- Decision 1: **split into four files** (`tokens.css`, `base.css`, `components.css`, `features.css`).
- Decision 2: **yes, a style guide page**, `/design.html`.
- Decision 3: **a list of warnings, not strict failures.** `make test` prints every raw colour,
  font size, corner, or spacing value in `px` found outside `tokens.css` (file, line, value), and
  still passes. The other design-system tests (every `var(--x)` defined, every component on the
  style guide, both pages loading the same files) stay real tests. The migration still moves every
  existing value it can to a token, so the list starts short.
