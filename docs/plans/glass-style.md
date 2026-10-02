Status: built on branch glass-style, awaiting merge

# Glass style

Written by the orchestrator, from the owner's request: "the bootstrappy look is a little dated —
modernify it with thinner lines and cleaner edges; think Apple liquid glass". The owner chose the
three decisions below. It keeps the classic 2012–2013 layout and changes the surface.

## 1. What it does

The page keeps its layout (top bar, left column, stream) but looks current: frosted, see-through
glass for the bar, the cards and the menus, over a soft colour wash; hairline edges with a faint
light highlight; large soft corners; pill-shaped buttons, search box and tabs; soft shadows
instead of hard borders. Text stays easy to read, and people who ask their computer for less
transparency or more contrast get solid surfaces.

## 2. Decisions (made by the owner)

1. **Glass on the bar, the cards and the menus** (the top bar, the left-column cards, the stream
   card, the "⋯" menu, the "N new posts" button, open `<details>` boxes). Posts inside the stream
   card are plain rows with hairline lines between them, so scrolling stays fast.
2. **A soft colour wash behind the glass:** a large, fixed blend of blue and lilac (light) or deep
   blue and violet (dark), in CSS only (gradients), no picture file.
3. **Large soft corners (about 18px) and pill buttons:** every button, the search box and the view
   tabs (as a segmented control) have fully round ends. Edges are hairlines (1px, or thinner on
   sharp screens) with a faint light highlight on the top edge.

## 3. Design (orchestrator; the builder may refine and must say why)

- **Tokens first** (`tokens.css`): `--radius-card` ~18px, `--radius-pill`; `--hairline` (1px, and
  0.5px on high-density screens where it renders); glass tokens: `--glass` (a see-through fill, in
  `light-dark()`), `--glass-strong` (menus, the bar), `--glass-edge` (the hairline colour),
  `--glass-highlight` (the light top edge), `--glass-blur` (e.g. 20px) and `--glass-saturate`;
  `--shadow-soft`, `--shadow-raised`; the wash colours `--wash-1..3`. The bar's dark tokens become
  glass. The accent stays blue (names, links, the Post button), tuned to sit well on glass.
- **Components** (`components.css`): a `.glass` surface (fill, `backdrop-filter: blur()
  saturate()` with the `-webkit-` form for Safari, hairline edge, highlight as an inset shadow, soft
  shadow), used by `.top-bar`, `.card`, `.disclosure[open]`, `.menu`, the new-posts button. Pills
  for `.button`, the search field and `.tabs` (segmented, the current tab a raised pill). Fields get
  soft fills instead of heavy borders, with a clear focus ring.
- **The wash** is on `body` (fixed, so it doesn't scroll), in `base.css`.
- **Accessibility fallbacks, required:**
  - `@supports not (backdrop-filter: blur(1px))` → glass becomes nearly solid.
  - `@media (prefers-reduced-transparency: reduce)` → solid surfaces.
  - `@media (prefers-contrast: more)` → solid surfaces and stronger edges.
  - Focus rings stay clearly visible on glass.
- **Contrast tests:** `ColoursTest` today reads solid hex colours. Glass fills are see-through, so
  the test must check text against the glass **composited over the worst wash colour behind it**
  (blend the fill over each wash colour, then check ≥ 4.5 for text, ≥ 3 for edges that matter, like
  focus and field outlines). Hairlines between posts are decoration and may be fainter than 3:1;
  say which edges are decoration.
- **Performance:** no `backdrop-filter` on individual posts. Check scrolling a long timeline stays
  smooth.
- The raw-value warning list stays at 0. Every new component is shown on `/design.html`.

## 4. Files touched

`with-backend/tokens.css`, `base.css`, `components.css`, `features.css` (small), `design.html`,
copies in `page-only/`; `test_server.py` (`ColoursTest` composited contrast, new glass tests);
`AGENTS.md`, `DESIGN.md` (a "Glass style" section; why posts are not glass; the fallbacks).
No server, database or words change.

## 5. Depends on

Everything merged (design system, classic layout). Nothing else is being built.

## 6. Tests

Composited contrast in both modes over each wash colour; the three fallbacks exist; no
`backdrop-filter` on `.post`; every new token used and defined; the style guide shows `.glass`;
both pages load the same files; "no company name". Browser: light and dark, 1280 / 900 / 375 px,
signed in and out, a long timeline scrolled, the ⋯ menu open, search results, My bookmarks, a
picture, a reply thread, a deleted post, and with reduced transparency emulated if possible.

## 8. Not in this plan

Animated or moving glass, a picture as the background, glass on each post, any layout change.

## 9. Size

**S–M.** Mostly tokens and components, plus the contrast test and the style guide.
