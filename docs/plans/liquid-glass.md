Status: approved

# Liquid glass

Written from the owner's request after `glass-style` was merged: "The liquid glass isn't very
glassy. Go look at the actual Apple design language documents. The Apple UI is very, very slick."
This plan reads what that design language really says (section 10 lists every source), and turns
it into plain CSS, one small script and one SVG filter. There is still no build step and no library.

**Words used in this plan.**
- **Layer:** a level of the page, from back to front: the page background, the **content layer**
  (the cards and the posts), and the **control layer** (the bar, the menus and the buttons that float
  above the content).
- **Backdrop filter:** a CSS effect (`backdrop-filter`) that changes what is *behind* an element:
  it can blur it, brighten it or bend it.
- **Refraction** or **lensing:** the way a thick piece of glass bends light, so that what is behind
  its edge looks pulled and curved. Here it is made with an SVG **displacement map**: a picture
  whose red and green colours tell the browser how far to move each pixel left/right and up/down.
- **Specular highlight:** the bright line where light catches the edge of glass.
- **Capsule:** a shape with fully round ends, like a pill.
- **Concentric corners:** corners inside a rounded box are rounded *less*, by exactly the space
  between them, so the two curves share one centre and look like they fit together.
- **Fallback:** what the page shows instead when a browser cannot do an effect, or when the
  computer asks for less transparency, more contrast or less motion.

## 1. What it does

The page keeps its 2012 layout, but the top bar becomes a floating glass **capsule**, set in a
little from the top and the sides, and the posts scroll *under* it: you see them bend at its curved
edge and fade softly as they reach it. The cards and the posts themselves stop being glass. They
become clean, solid surfaces on a calm background, so the glass is kept for the few things you
press: the bar and its controls, the "⋯" menu and "3 new posts". The glass has a bright rim where
light catches it, the current view tab is a pill that slides to the tab you choose, and a menu opens
from its "⋯" instead of just appearing. When the computer asks for less transparency, more
contrast or less motion, the shapes, spacing and depth stay, and only the see-through and the
movement go.

## 2. Decisions for the owner

### D1. Where does the glass go?

The current `glass-style` puts glass on the bar, every card in the left column, the stream, open
disclosures and menus. The design guidelines say the opposite: glass forms "a distinct functional
layer for controls and navigation", it should not be used "in the content layer", and you should
"avoid glass on glass". A list of posts made of glass "would make it compete" with the controls
(WWDC25 "Meet Liquid Glass").

- **(a) Keep glass on the cards and the bar** (today). Most "glassmorphism" looks like this. It is
  the reason it reads as frosted plastic and not as liquid glass.
- **(b) Glass only on the control layer.** The bar becomes a floating capsule, inset from the top
  and the sides, with the posts scrolling under it. The "⋯" menu, "3 new posts" and the view tabs'
  pill are glass. The left column's cards and the stream are the content layer: solid surfaces
  with large concentric corners and a very soft shadow, on a calm page background.
- **(c) As (b), and the left column is a floating glass sidebar** (as on iPad and Mac).
  The left column is mostly forms (the post box, Email, Log in), and long forms on glass are hard
  to read; it also adds a large blurred area to every frame.

**Recommendation: (b).** It is what the guidelines say, it is what makes the real thing look
slick (a small amount of very good glass over real content), and it is faster than today: three or
four small blurred areas instead of one for every card. What it does to the classic layout:

- The **top bar** keeps its contents and order (name, view tabs, search, Colours, Log out) but
  floats: `position: sticky`, 12px from the top, with 12px of room on each side when the window is
  narrow, and a capsule shape. Its controls are put in at most three groups (guidelines: "aim for a
  maximum of three"): the view tabs, search, and Colours with Log out.
- The **columns** do not move. The left column is content: solid cards. The right column is one
  solid card, the stream, whose posts slide under the bar as you scroll.
- **Under 920px wide** the capsule scrolls away with the page as the bar does today (see D6).

### D2. Refraction (the edge that bends what is behind it)

This is the effect people mean by "liquid": the guidelines call lensing "the primary way" the
material defines itself. On the web it needs an SVG filter inside `backdrop-filter: url(#…)`,
which only Chromium browsers (Chrome, Edge, Brave, Arc, Opera) draw today.

- **(a) Refraction in Chromium, frosted glass elsewhere.** A small script draws a displacement
  map for the bar's exact size (and again when it changes size), and only Chromium is given the
  filter. Safari and Firefox get the same glass without the bent edge.
- **(b) No refraction.** The same everywhere, simpler, but still "frosted", which is the
  owner's complaint.
- **(c) Refraction everywhere by refracting a copy of the content** (one library does this for
  glass over a photo). It only works over a still picture, not over a moving timeline of text.

**Recommendation: (a)**, on at most two elements (the bar and "3 new posts"), with the lens
written by us (about 60 lines), not copied. Note the owner will not see it on his own Mac with
Reduce Transparency on (see D7).

### D3. Light on the glass (specular highlights)

- **(a) A still highlight.** A rim that is bright at the top-left and bottom-right corners and
  dim along the sides (a gradient border), a faint inner glow that gives the glass thickness, a
  soft sheen near the top, and a thin dark outer edge so white glass is still seen on a white post.
  All browsers.
- **(b) (a), and the light follows the pointer** over the glass, and the glass "lights up" where
  you press it (the guidelines: the material "illuminates from within" on touch). A few lines of
  script; off with Reduce Motion and on touch screens.
- **(c) (b), and the light follows the tilt of a phone.** Needs a permission prompt on phones.

**Recommendation: (b).** (a) is most of the look; (b) is what makes it feel alive, and it is cheap
(it only changes two CSS values on the element under the pointer). Not (c).

### D4. How much movement and morphing

- **(a) None.** Nothing moves; only the surfaces change.
- **(b) Small, quick, spring-like movement on the controls:** the current view's pill slides to
  the tab you choose; the "⋯" menu grows out of its button ("materialises"); a glass button
  squashes a little while pressed; "3 new posts" slides in. Nothing on the content moves.
- **(c) (b), and controls morph into each other** between states (for example the search box
  turning into the results bar). That needs a lot of script and has no simple web form.

**Recommendation: (b).** With Reduce Motion everything jumps straight to its end, as the
guidelines say ("disables any elastic properties").

### D5. What is behind the glass

- **(a) Keep the colour wash** (blue, lilac and sky spots) across the whole page.
- **(b) A calm, nearly neutral page** (a cool light grey, or near black in dark mode), with the
  wash kept as a faint glow at the top only, so the glass mostly bends and tints *the posts
  themselves*: their words, the coloured letter circles and the pictures. Colour comes from the
  content, as the guidelines say: "imbue color … in the content layer instead".
- **(c) A photo or a moving background.** Not our content, and it fights with the posts.

**Recommendation: (b).** Glass over a soft, even wash has nothing to bend, which is part of why
the current look reads as flat frost. Glass over real, moving posts is what makes it look like
glass.

### D6. Phones (under 920px)

- **(a)** The capsule bar at the top scrolls away with the page, as the bar does today. Same
  surfaces, same fallbacks.
- **(b)** Split it the way phone apps do: a small capsule at the top (name, search), and the view
  tabs as a floating capsule at the bottom of the screen. That is a layout change.

**Recommendation: (a) now; (b) as its own small plan later**, if the owner wants it.

### D7. How does the owner see the glass when his Mac turns it off?

The owner's Mac has **Reduce Transparency** and **Increase Contrast** on. Chromium browsers pass
both to the page (`prefers-reduced-transparency`, `prefers-contrast`); Safari passes only Increase
Contrast. So the owner sees the solid look, which is right. Two things follow:

1. **The solid look must be slick too** (section 3.7): the guidelines' own answer is that Reduce
   Transparency makes the glass "frostier", and Increase Contrast makes elements "predominantly
   black or white" with "a contrasting border". Shape, spacing, depth and motion all stay.
2. To *review* the glass, the options are:
   - **(a)** A "Show as: Glass / Reduced transparency / More contrast" switch on `/design.html`
     only, which applies each look to the style guide whatever the computer says.
   - **(b)** A "Glass" choice next to Colours on the real page (Auto / On / Off), remembered in
     `localStorage`. It needs words in `words.js` and a test like the Colours one.
   - **(c)** No switch: turn the settings off for a moment, or use Chrome's developer tools
     (Rendering → emulate CSS media features).

**Recommendation: (a)**, plus (c) for checking the real page. It needs no words and cannot
change what other people see. (b) can follow if people ask for it.

### D8. Smoother corners

Corners in this design language are not quite circles: they ease in (a "squircle"). CSS has
`corner-shape: squircle` in Chromium (139 and later) only. Elsewhere the corner is round, as today.

**Recommendation: yes**, on the rectangles only (cards, the menu, pictures); capsules stay round.
It is one declaration per component and does nothing where it is not supported.

## 3. Design

No database, model, route, view or words change. One file is added: `with-backend/glass.js`.

### 3.1 The layers, back to front

| z | Layer | What | Glass? |
|---|---|---|---|
| 0 | page | `--background` (neutral) with a faint wash at the top (`body::before`, fixed, gradients only) | no |
| 1 | content | `.card`, `.stream`, the posts, pictures | no: solid `--surface` |
| 2 | scroll edge | a strip under the bar where posts fade out (`.scroll-edge`) | a light blur, masked |
| 3 | controls | `.top-bar`, `.menu[open] > ul`, `.new-posts`, the tab pill | **yes** |

`--layer-edge: 2`, `--layer-bar: 3`, `--layer-sticky: 4` (tokens; today `--layer-bar` is 2 and
`--layer-sticky` is 1, and "3 new posts" now floats over the edge too).

### 3.2 The content layer (solid, "grouped")

- `--surface: light-dark(#ffffff, #151b25)`: every card and the stream. No border in light mode
  (the surface stands out from the grey page); a hairline `--separator` edge in dark mode.
- `--background: light-dark(#eef0f5, #06090f)`; the wash tokens stay, drawn only in the top 45%
  of `body::before` and fading out (D5 b).
- `--shadow-content: 0 1px 2px var(--shadow)`: just enough to lift a card.
- Posts are separated by an **inset** hairline that starts where the words start
  (`margin-inline-start: var(--avatar-indent)`), not edge to edge: a detail that makes lists feel
  light. `--separator: light-dark(#3c435033, #ffffff1f)` (decoration).
- **Concentric corners**, worked out from tokens so they always fit:
  - `--radius-large: 22px` (cards, the stream), with `--card-pad: var(--space-5)` (12px).
  - `--radius-field: calc(var(--radius-large) - var(--card-pad))` (10px): boxes inside a card.
  - `--radius: calc(var(--radius-large) - var(--card-pad))`: pictures inside a post.
  - `--radius-popover: 20px`, `--popover-pad: var(--space-2)`, and a menu row is
    `calc(var(--radius-popover) - var(--popover-pad))`.
  - Everything in the bar is a capsule (`--radius-pill`); a capsule inside a capsule is always
    concentric when the padding is the same on all sides, so the bar's padding is one token,
    `--bar-pad: var(--space-2)`, on all four sides.
- `corner-shape: squircle` on `.card`, `.stream`, `.menu ul`, `.post-picture` (D8).

### 3.3 The glass recipe (one component, `.glass`, used by the control layer)

Glass is four parts, drawn by one element and its two pseudo-elements (the element is
`position: relative; isolation: isolate`, so the pseudo-elements stay inside it):

1. **The body (frost).** `background: var(--glass-tint)` and
   `backdrop-filter: var(--glass-filter)` (and `-webkit-backdrop-filter`), where
   `--glass-filter: blur(var(--glass-blur)) contrast(var(--glass-range)) saturate(var(--glass-saturate))`.
   - `--glass-blur: 10px` (today 24px: real liquid glass is much clearer than frost; the
     builder may tune between 6 and 14px by eye, and must say why).
   - `--glass-range: 0.72`. `contrast()` below 1 squeezes what is behind toward middle grey, so a
     black or white picture under the bar can never be fully black or white. This is the web form
     of what the guidelines describe as shifting "the dynamic range" to keep labels legible, and it
     lets the tint be much more see-through than today.
   - `--glass-saturate: 150%`.
   - `--glass-tint: light-dark(#ffffff80, #0b122099)` (50% / 60%; today 80% / 84%).
     `--glass-tint-thick: light-dark(#ffffffb8, #0b1220c2)` for the menu: larger glass is
     "thicker" in the guidelines ("deeper, richer shadows", more opaque).
   - The worked numbers (sRGB, before blur): behind light glass, black becomes
     `0.5 - 0.5 × 0.72 = 0.14`, and 50% white over it is `0.57`, which is above the `0.54` that
     dark words need for 4.5 to 1. In dark mode white becomes `0.86`, and 60% of the dark tint over
     it is `0.39`, under the `0.42` light words need. The test (3.9) checks the exact values.
2. **The rim** (`::before`). A gradient hairline: a border of `var(--hairline)`, painted with
   `linear-gradient(135deg, var(--rim-bright), var(--rim-dim) 30%, var(--rim-dim) 70%, var(--rim-bright))`
   and cut to the border only with
   `mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0)`
   (and `-webkit-mask-composite: xor` for Safari).
   `--rim-bright: light-dark(#ffffffe6, #ffffff66)`, `--rim-dim: light-dark(#ffffff40, #ffffff14)`.
3. **The depth** (`box-shadow` on the element):
   `--glass-depth: inset 0 1px 1px var(--rim-bright), inset 0 -1px 1px var(--rim-dim), inset 0 0 16px var(--glass-glow)`
   for thickness, and
   `--shadow-float: 0 0 0 0.5px var(--rim-shade), 0 2px 6px var(--shadow), 0 12px 32px var(--shadow)`
   for lift. `--rim-shade: light-dark(#0b1a3326, #000000a6)` is the thin dark outer edge that keeps
   white glass visible over a white post. `--glass-glow: light-dark(#ffffff59, #ffffff0f)`.
4. **The sheen** (`::after`). `radial-gradient(120% 80% at var(--light-x, 30%) var(--light-y, 0%), var(--sheen), transparent 60%)`
   with `mix-blend-mode: screen`, `pointer-events: none`.
   `--sheen: light-dark(#ffffff73, #ffffff1a)`. `glass.js` moves `--light-x` and `--light-y`
   (D3 b). `.glass.is-pressed` raises the sheen's opacity: the glass "lights up" where you press.

`.glass` is used by `.top-bar`, `.menu[open] > ul` (with `--glass-tint-thick`), `.new-posts` and
the tab pill. `.glass-strong` and the use of glass on `.card`, `.disclosure[open]` and `.stream`
are removed. **No glass on glass:** controls *inside* the bar (search box, tabs track, Colours,
buttons) are fills, not glass: `--fill: light-dark(#7880991f, #ffffff1a)`, the tabs track and
the search box use it, and the current tab's pill is `--fill-raised: light-dark(#ffffffd9, #ffffff2e)`
with a small shadow (it is a "thin overlay that is part of the material", as the guidelines put it).

The Post button stays a solid accent capsule: it is the one main action, and the guidelines keep
colour for that ("apply color to the background" of the primary action).

### 3.4 Refraction (D2 a)

- **The filter.** One hidden `<svg width="0" height="0" aria-hidden="true">` at the top of
  `<body>` in `index.html` and `design.html`, holding:

  ```
  <filter id="lens" x="0" y="0" width="100%" height="100%"
          color-interpolation-filters="sRGB">
    <feImage id="lens-map" x="0" y="0" preserveAspectRatio="none" result="map"/>
    <feDisplacementMap in="SourceGraphic" in2="map" scale="0"
                       xChannelSelector="R" yChannelSelector="G"/>
  </filter>
  ```

  `color-interpolation-filters="sRGB"` matters: without it the browser reads the map's colours in
  another colour space, and 128 no longer means "do not move". One filter per glass element that
  refracts (`lens-bar`, `lens-new-posts`), because the map must be the element's own size.
- **The map** (`lensMap(width, height, radius, bezel)` in `glass.js`). For each pixel of a
  `<canvas>` the size of the element: its distance `d` to the capsule's edge (a rounded-rectangle
  distance), and, inside the rim (`d < bezel`), a height `h(t) = (1 - (1 - t)^4)^(1/4)` with
  `t = d / bezel` (a "squircle" profile: flat in the middle, curving smoothly at the edge). The
  slope of `h` says how much the edge bends light; the direction is toward the inside of the
  shape. Red = `128 + 127 × x`, green = `128 + 127 × y`, blue 128, everywhere else 128/128 (no
  move). The canvas becomes a data URL for `#lens-map`; `scale` is `--lens-scale`.
  Tokens: `--lens-bezel: 14px`, `--lens-scale: 24` (pixels at the strongest point).
  The idea (height profile, then its slope, then red and green) is from the kube.io article; our
  code is our own and simpler (no ray tracing: the slope is enough at this size).
- **When.** A `ResizeObserver` redraws the map when the element changes size, at most once per
  animation frame. The bar is about 1180 × 46 pixels: about 54,000 pixels, a few milliseconds.
  Moving or scrolling never redraws it.
- **Who gets it.** Only when `glass.js` adds `class="refracts"` to `<html>`, which it does only if
  all are true: `navigator.userAgentData` exists (Chromium), `CSS.supports("backdrop-filter",
  "url(#lens)")`, and the computer asks for neither less transparency nor more contrast. The CSS
  is `html.refracts .top-bar { backdrop-filter: url(#lens-bar) var(--glass-filter); }`, written
  *after* the plain rule. **`@supports` alone is not trusted**: reports differ on whether Safari
  rejects the value (then the plain blur stays) or accepts it and draws no backdrop at all (then the
  bar loses its blur too). Firefox may draw it; it is left out until someone checks.
- The bar's words never sit on the bent rim: the rim is `--lens-bezel` wide, and a test checks
  that `--lens-bezel` is at most half of `--bar-height`, so the rim stays inside the capsule's
  round ends and its padding, where there are no words.

### 3.5 Scroll edge

A fixed `<div class="scroll-edge" aria-hidden="true">` right after the bar (wide screens only,
`display: none` under 920px): `height: calc(var(--bar-inset) * 2 + var(--bar-height))`,
`background: linear-gradient(var(--background) 30%, transparent)`,
`backdrop-filter: blur(var(--edge-blur))` (`--edge-blur: 4px`),
`mask-image: linear-gradient(#000 50%, transparent)`, `pointer-events: none`,
`z-index: var(--layer-edge)`. Posts fade softly into the page as they reach the bar instead of
being cut by a line (guidelines: scroll edge effects replace "hard dividers with subtle blur").
`--sticky-top` becomes `calc(var(--bar-inset) + var(--bar-height) + var(--space-3))`.

### 3.6 Movement (D3 b, D4 b)

- Tokens: `--duration-quick: 160ms`, `--duration-morph: 360ms`,
  `--ease-spring: linear(…)` (a spring curve with a small overshoot, written as a `linear()`
  list of about 12 points), with `--ease-spring-plain: cubic-bezier(0.34, 1.3, 0.64, 1)` used
  where `linear()` is not supported (`@supports not (transition-timing-function: linear(0, 1))`).
- **The tab pill.** `.tabs.has-pill` gets one `::before` that is the pill:
  `translate: var(--pill-x) 0; width: var(--pill-width)`, moved with
  `transition: translate var(--duration-morph) var(--ease-spring), width …`. `glass.js` watches the
  view tabs with a `MutationObserver` (for `aria-current`) and sets `--pill-x` and `--pill-width`,
  so `showView` in `app.js` does not change. Without the script the current tab keeps its own
  raised look, as today.
- **The menu.** `.menu[open] > ul` grows from its "⋯" (`transform-origin: top right`) with
  `@starting-style { opacity: 0; scale: 0.9; }` and a transition on `opacity` and `scale`.
- **Press.** A button on glass: `:active { scale: 0.96 }`. `glass.js` adds `.is-pressed` to the
  glass under a pointer press (the sheen brightens) and sets `--light-x`/`--light-y` on
  `pointermove`, once per animation frame, only for `(hover: hover)` pointers.
- **"3 new posts"** slides down from under the bar with `@starting-style`.
- **Reduce Motion:** `@media (prefers-reduced-motion: reduce)` sets both durations to `0s`, and
  `glass.js` does not follow the pointer. A test checks every `transition` uses the duration
  tokens.

### 3.7 The fallbacks: the solid look must be slick too

All fallbacks only change tokens at the end of `tokens.css` (as today), so every surface follows.
Order matters, and is tested: no backdrop filter → Reduce Transparency → Increase Contrast, so
with both settings on (the owner) Increase Contrast wins.

| When | Glass becomes | Stays |
|---|---|---|
| No `backdrop-filter` | `--glass-tint: var(--glass-solid)`, `--glass-filter: none` | rim, depth, sheen, capsule, motion |
| Safari/Firefox (no lens) | the same glass without the bent edge | everything else |
| Reduce Transparency | **frosted solid**: `--glass-solid: light-dark(#f7f8fb, #1b2230)` (a little off the surface colour, so the bar still reads as its own layer), no blur, scroll edge without blur, no lens | capsule, floating inset, rim (now a crisp `--rim-shade` hairline), shadows, motion |
| Increase Contrast | **black or white**: `--glass-solid` and `--surface` become `#ffffff` / `#000000`; `--text` `#000000` / `#ffffff`; every control (bar, fields, buttons, menu, tab pill) gets a 1px `--border` edge ("a contrasting border"); the sheen and the glow go | capsule, shadows, motion; the lines *between posts* become 1px `--separator-more` (darker, but not a table grid) |
| Reduce Motion | nothing changes in looks | all of it; movement jumps to its end |

`--separator-more: light-dark(#6b7280, #9aa3b2)`.

### 3.8 Performance limits

- At most **four** elements with a backdrop filter on screen at once: the bar, the scroll edge,
  an open "⋯" menu, "3 new posts". The cards, the stream, the posts and the lists never have one
  (a test). That is fewer than today.
- At most **two** use the lens (`url(#lens-…)`): the bar and "3 new posts". The menu is plain
  glass: its size changes with its contents.
- `glass.js` never runs work on scroll. Pointer work runs at most once per frame, on one element.
- Check by hand: scroll 300 posts in Chrome with the performance panel; no long frames.

### 3.9 How the tests change (`ColoursTest`, `GlassStyleTest`)

A see-through colour has no contrast of its own. The test does what the browser does, with the new
filter chain:

- It reads `--glass-filter` and applies its steps in order to each colour behind: `contrast(c)` is
  `x → (x − 0.5) × c + 0.5` per channel, `saturate(s)` as today (Filter Effects standard), clipped
  to 0..1; then lays the tint on top. The builder checks, by sampling a pixel in Chrome and Safari,
  which colour space the browser applies `contrast()` in, and the test follows it.
- **What sits behind the glass** is now: the page background, the faint wash colours, `--surface`,
  a post under the mouse, and pure black and pure white (pictures). Refraction only *moves* pixels
  that are already there, so it adds no new colour and needs no new case.
- **Surfaces checked:** words on the bar, the tab pill on its track on the bar, the menu (thick
  tint), "3 new posts", the fields, the content `--surface`, the page; each **also with the sheen
  laid on at its brightest**, because the sheen covers words. Text ≥ 4.5, focus ring and field edges
  ≥ 3, as today.
- **Fallbacks:** the frosted solid look ≥ 4.5; the Increase Contrast look ≥ **7** for words (the
  higher WCAG level, since that setting asks for more).
- **Decoration, not checked:** the rim, the glow, `--rim-shade`, `--separator`, the shadows, the
  scroll edge.
- `GlassStyleTest` becomes: no backdrop filter on `.card`, `.stream`, `.dashboard`, `.post`,
  `.timeline`; at most four rules with a backdrop filter; `url(#lens` only under `html.refracts`
  and after a plain rule for the same element; the `<filter>` has
  `color-interpolation-filters="sRGB"`; the four fallback blocks exist, in order; the
  reduced-motion block sets every duration to `0s`; every `transition` and `animation` uses the
  duration tokens; `--lens-bezel` ≤ half of `--bar-height`; the design guide's "Show as" blocks
  are exactly the same declarations as the media-query blocks.

### 3.10 The style guide (`/design.html`)

- The "Show as" switch (D7 a): three buttons that set `data-look="glass" | "frosted" | "contrast"`
  on the guide. In `tokens.css`, `[data-look="frosted"]` and `[data-look="contrast"]` repeat the
  Reduce Transparency and Increase Contrast blocks exactly (custom properties work on any element,
  so the guide can show a look the computer did not ask for). A test checks they match.
- New entries: the layers (a mock bar over a few sample posts, so the lens and the scroll edge can
  be seen), `.glass` with its four parts named, the tab pill, the menu opening, the concentric
  corner tokens drawn nested.
- The guide loads `glass.js` too.

### 3.11 `glass.js`

A new file, loaded by `index.html` and `design.html` after `app.js` (`<script src="glass.js">`), served
by the server like the other files. Plain functions, no `innerHTML`, and nothing kept in `localStorage`:

- `glassCanRefract()`: the checks in 3.4. `startGlass()`: sets `html.refracts`, starts the
  observers.
- `lensMap(width, height, radius, bezel)`: returns the data URL. `fitLens(element, filterId)`:
  the `ResizeObserver` that redraws it.
- `followLight(element)`: pointer light and `.is-pressed`. `moveTabPill(nav)`: the pill.
- It reads the tokens with `getComputedStyle`, so numbers live in `tokens.css` only.
- If anything throws, the page is as it would be without the script (CSS already has the
  fallback).

`page-only/` gets the four CSS files as copies (as today) but not `glass.js` or the bar: it has
no bar and only content-layer surfaces.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/tokens.css` | colours: `--background`, `--surface`, glass tints, rim, sheen, glow, fills, separators; non-colours: `--glass-*`, `--lens-*`, `--bar-inset`, `--bar-pad`, `--card-pad`, radii (concentric), durations, easing, layers, `--edge-blur`; the four fallback blocks and the two `[data-look]` blocks; reduced motion | change (most of the work) |
| `with-backend/base.css` | `body`, `body::before` (wash at the top only) | change |
| `with-backend/components.css` | `.glass` (rewrite: four parts), remove `.glass-strong`; `.card`, `.disclosure`, `.stream` become solid; `.tabs` (fills, `.has-pill`); `.menu` (thick glass, concentric rows, opening); buttons (press, fills in the bar); post separators (inset); `.top-bar` (capsule, inset, sticky, groups); `.scroll-edge` (add); `html.refracts` rules (add) | change |
| `with-backend/features.css` | `.new-posts` (glass, slide in); any block that used `--glass-*` names that change | change (small) |
| `with-backend/glass.js` | `glassCanRefract`, `startGlass`, `lensMap`, `fitLens`, `followLight`, `moveTabPill` | add |
| `with-backend/index.html` | the hidden `<svg>` with two filters; `<div class="scroll-edge">`; `<script src="glass.js">`; the bar's three groups (wrapping `<div>`s; every `id` stays) | change (small) |
| `with-backend/design.html` | the same `<svg>` and script; "Show as" switch; new entries | change |
| `with-backend/server.py` | the static file table: `"/glass.js"` (one line, controller) | change |
| `with-backend/test_server.py` | `ColoursTest.surfaces`, a `filter_chain` helper, new cases; `GlassStyleTest` (rewritten checks, new methods at the end); `DesignSystemTest` (both pages load `glass.js`); `RealServerTest` (GET `/glass.js`); `ClassicStyleTest.test_nothing_names_the_company` (also "apple" except `-apple-system`, "iphone", "ios", "macos") | change / add |
| `page-only/tokens.css`, `base.css`, `components.css`, `features.css` | copies | change |
| `AGENTS.md`, `DESIGN.md`, `docs/plans/README.md` | see section 7 | change |

`app.js` and `words.js` do **not** change.

## 5. Depends on, and collides with

- **Depends on** `glass-style` and `classic-layout` (both merged). It replaces most of
  `glass-style`'s surface rules; it keeps its tests' method (composited contrast) and its three
  fallbacks.
- **Collides with** any branch that touches `tokens.css` or `components.css` (all of them, at
  the end of the file), the head or body start of `index.html`, and the static table in
  `server.py`. No other plan is being built now. Build it alone.
- `japanese` Part B: no collision (no words change).
- A later "phone tab bar" plan (D6 b) would build on this.

## 6. Tests

- **`ModelTests`:** none (no model change).
- **`RealServerTest`:** `GET /glass.js` answers 200 with a JavaScript type.
- **`JourneyTest`:** none.
- **`PageAndServerAgreeTest`:** none new; the copies of the four CSS files still match.
- **`ColoursTest`:** as in 3.9: the new filter chain, the new surfaces, the sheen, both fallbacks
  (≥ 4.5, and ≥ 7 with more contrast), the bar over black and white.
- **`GlassStyleTest`** (and new methods at its end): as in 3.9.
- **`DesignSystemTest`:** every new token defined and used; the raw-value warning list stays at
  0; both pages and the guide load the same four CSS files in order, and `glass.js`; every new
  component is on the guide.
- **By hand, in a browser:** Chrome, Safari and Firefox; light and dark; 1280 / 900 / 375 px;
  signed in and out; a long timeline scrolled under the bar (with pictures); the ⋯ menu; search;
  My bookmarks; a reply thread; a deleted post; the tab pill moving; and each of Reduce
  Transparency, Increase Contrast (and both), Reduce Motion, emulated in Chrome's Rendering panel
  and set on a Mac. Screenshots of each go with the branch.

## 7. Docs to update

- `DESIGN.md`: a new section **"Liquid glass"**: the layers; why only controls are glass; the
  recipe; the lens and which browsers get it; the movement; the fallbacks table; how the
  contrast test works now; the performance limits. One line at the end of "Glass style" says
  which parts were replaced. Sources go in the doc, not in the code (the code names no company).
- `AGENTS.md`: a row for `with-backend/glass.js` in the file table; a short "Liquid glass" section
  (glass only on the control layer; at most four backdrop filters; the lens only through
  `html.refracts`; no glass on glass; the fallbacks are tokens).
- `docs/plans/README.md`: a row for `liquid-glass`.

## 8. Not in this plan

- Glass that switches between light and dark by itself depending on what is under it (the
  guidelines do this for small bars; on the web it would need reading pixels under the bar on
  every frame).
- Colour fringes at the edge (chromatic aberration): three displacement passes, too costly.
- Controls morphing into each other (D4 c); tilt with the phone (D3 c).
- A bottom tab bar on phones (D6 b), a bar that shrinks while scrolling.
- A "Glass" choice on the real page (D7 b).
- Any company's name, logos, icons or fonts. The font stays `system-ui`.
- Any change to the server's logic, the database or the words.

## 9. Size

**L, about 650 lines** (≈ 300 CSS changed or added, 150 `glass.js`, 30 HTML, 1 server, 150
tests, 60 docs). It can be built in two parts, each **M**:

- **Part A** (no new script): the layers, solid content surfaces, the capsule bar, the scroll
  edge, the glass recipe (frost, rim, depth, sheen), concentric corners, `corner-shape`, the
  fallbacks, the menu's opening and the press with CSS only, the contrast tests, the guide's
  "Show as" switch (a few lines of inline script in the guide). About 400 lines. This is most of
  the "slick".
- **Part B:** `glass.js`: the lens, the pointer light, the sliding tab pill. About 250 lines.

Recommendation: build A, show the owner, then B.

## 10. Sources and prior art

### What the design language says (read first)

- Human Interface Guidelines, *Materials*:
  <https://developer.apple.com/design/human-interface-guidelines/materials>. Glass is the layer
  for "controls and navigation"; not in the content layer; use it "sparingly"; regular vs. clear
  variants; a dimming layer for clear glass over bright content.
- *Adopting Liquid Glass*:
  <https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass>.
  Remove custom bar backgrounds; scroll edge effects; concentric shapes; group toolbar items;
  inset sheets so content peeks through; combine glass effects for performance.
- *Applying Liquid Glass to custom views*:
  <https://developer.apple.com/documentation/swiftui/applying-liquid-glass-to-custom-views>.
  Glass blurs, "reflects color and light", reacts to the pointer; limit the number of effects on
  screen.
- WWDC25 *Meet Liquid Glass*: <https://developer.apple.com/videos/play/wwdc2025/219/>. Lensing,
  the highlight and shadow layers, illuminating on touch, "avoid glass on glass", larger glass is
  thicker, and what Reduce Transparency, Increase Contrast and Reduce Motion do.
- WWDC25 *Get to know the new design system*:
  <https://developer.apple.com/videos/play/wwdc2025/356/>. Concentricity (fixed, capsule and
  concentric shapes), at most three bar groups, scroll edge effects in place of dividers, inset
  sidebars.
- HIG *Color*, *Toolbars*, *Tab bars*, *Layout* (same site): monochrome bar labels, colour on
  the primary action's background, extending content under bars.

### Prior art: people who rebuilt it on the web

| Who | Technique | How convincing | Browsers | Cost | What we take |
|---|---|---|---|---|---|
| kube.io, *Liquid Glass in the Browser: Refraction with CSS and SVG* <https://kube.io/blog/liquid-glass-css-svg/> | A height profile (convex squircle) → slope → refraction (Snell's law) → displacement vectors as red/green in a map → `feImage` + `feDisplacementMap` in `backdrop-filter: url()`; a separate rim highlight blended on | The most convincing: real bending at the edge, physically shaped | Chrome only (the author says so) | Cheap to move, costly to resize (the map is rebuilt) | **The method**: profile → slope → red/green map, built at runtime for the element's size. Written by us, simpler (no ray tracing). |
| LogRocket, *How to create Liquid Glass effects with CSS and SVG* <https://blog.logrocket.com/how-create-liquid-glass-effects-css-and-svg/> | Displacement and rim maps drawn in a design tool as PNGs; `feImage`, `feDisplacementMap`, `feColorMatrix`, `feComposite`, `feBlend` | Good when the maps are made with care | Chromium only (stated) | "Each filter instance reserves GPU" resources: keep it to a few floating elements | The **budget rule** (only toolbars, menus, main buttons). Not the PNG maps: no picture files in the repo, and they fit one size only. |
| WebTricks, *Liquid glass in CSS — frost, rim, sheen and real refraction* <https://webtricks.dev/blog/liquid-glass-css> | Four layers: frost (`backdrop-filter`), rim (inset `box-shadow`s and a light border), sheen (`::after` gradient, `screen` blend), refraction (`feTurbulence` noise into `feDisplacementMap`), gated for Chromium | Layers 1–3 look good everywhere; the noise refraction looks wobbly, not like a lens | 1–3 everywhere; 4 Chromium | SVG filters cost frames on weak devices; not on large scrolling areas | **The four-part structure** and the cross-browser base. Not `feTurbulence` (noise is not how glass bends). |
| nikdelvin/liquid-glass <https://github.com/nikdelvin/liquid-glass> (MIT) | Pre-made displacement and specular PNG maps; colour fringes by splitting channels with `feColorMatrix`; falls back to plain frosted glass | Close to the real thing in screenshots | Its README claims Firefox too; other sources say Chromium only; we treat it as Chromium only | Three displacement passes for the fringes | The idea of a **clean fallback** to frost. Not the fringes (cost) or the PNGs. |
| gentpan/liquidglass <https://github.com/gentpan/liquidglass> | Refracts an aligned *copy* of the picture behind, with a plain CSS `filter`, which all browsers draw; the map is made at runtime per shape | Works in all three browsers, but only over pictures; over page content Safari/Firefox get frost | All, over pictures | Map cached; reshaping costs | Confirms the map should be **made at runtime and cached**. The copy trick does not fit a moving timeline. |
| specy.app, *Liquid Glass in the Browser* <https://specy.app/blog/posts/liquid-glass-in-the-web> | Took a screenshot of the page (html2canvas) and drew glass with Three.js (WebGL) | Real 3D glass, but out of date the moment the page changes | Any with WebGL | Heavy: two libraries, screenshots | Nothing: libraries and a build are not allowed, and it is too slow. |
| Hacker News, *Show HN: CSS generator for a high-def glass effect* <https://news.ycombinator.com/item?id=44445238> | `::before`/`::after` layers, box-shadow bevel, `backdrop-filter` | Frosted, not liquid; commenters say leaving out refraction loses the "strong visual separation" | All | Blur is heavy on wide elements; slow scrolling reported on mobile Firefox | The **warnings**: keep glass small, keep text legible (people complained they could not read text on glass). |

Also read: the W3C SVG working group issue on making backdrop displacement work the same in every
browser, <https://github.com/w3c/svgwg/issues/1142> (it is not interoperable yet), and
`corner-shape` support, <https://caniuse.com/mdn-css_properties_corner-shape_squircle>
(Chromium 139+ only).

**Which technique this plan chooses, and why:** WebTricks' four-part structure (frost, rim, sheen,
plus depth) as the base everywhere, with the frost changed to squeeze the backdrop's range so the
glass can be clearer and still pass the contrast test; and kube.io's method for the lens,
written as our own small runtime map, only in Chromium, only on the bar and "3 new posts". It needs
no picture files, no library and no build; it degrades to good frosted glass in Safari and Firefox
and to a crisp solid look with the accessibility settings; and it keeps the number of blurred
areas small.

## Changes made at approval (owner)

- **All decisions (D1–D8) approved as recommended.** Cards are not glass: glass is only for the
  floating control layer.
- **Order:** Part A first (merged on its own), then Part B on top of it.
