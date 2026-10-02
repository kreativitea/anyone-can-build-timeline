Status: approved

# Classic layout

Written by the orchestrator, after the owner chose the era, the type size and the side column.

## 1. What it does

The page is laid out like Twitter in 2012–2013, not only coloured like it. A dark bar is fixed
across the top, with the app's name, search, the views, the Colours switch and Log out. Under it
are two columns. The narrow **left column** holds your profile card, the post box and the
trending `#tags`. The wide **right column** holds the timeline, search results or bookmarks. The
type is Twitter-sized (about 15px), not the large classroom size used until now. On a narrow
screen the two columns stack, the left one first.

## 2. Decisions

**Made by the owner:**
- The 2012–2013 layout: fixed dark top bar; left: profile card, post box, trends; right: the
  stream.
- Twitter-sized type. This **replaces** the old rule "the type is large because the page is read
  from the back of a room". `DESIGN.md` and the comment at the top of `style.css` must say so,
  so nobody puts the large type back by mistake.
- The side column shows all four: profile card, post box, trending tags, and search (search
  goes in the top bar, as in 2012).

**Made by the orchestrator (the owner can change any of these):**
- **Sizes**, taken from the 2013 page the `classic-style` research measured: body 15px; names
  15px bold; `@name` and time 13px; a 48px letter circle with the text 58px in; the left column
  300px wide and the right column 590px, with a 20px gap, centred (890px together). The bar is
  46px tall. Buttons and boxes keep the classic-style colours and corners.
- **When to stack:** under 920px wide, the columns stack (left column first) and the bar wraps
  onto two lines if it must. At phone width the circle is 40px.
- **The profile card** shows your circle, display name, `@name`, and two counts: **posts** (your
  posts that are not deleted) and **likes** (likes your posts have received). Both are counted
  from rows when asked, never stored, like every other count in this app. They come with
  `GET /sessions`, and the page asks again after you post, delete, or log in.
- **Signed out**, the left column holds the Log in and Sign up forms instead of the card and the
  post box. The trends are shown to everyone.
- **Trends** = the 10 `#tags` used in the most posts during the last 24 hours, counted with
  `search`'s `tags_in`, over posts this viewer may see (`select_posts`, so `block` and `report`
  apply) that are not deleted. Ties: A–Z. Each tag is a link to its search (`searchFor`). New
  route `GET /trends`, open to everyone, asked when the page opens and every 60 seconds (not every
  second). Old posts with "date unknown" have no date, so they never count.
- **Email** and **Blocked accounts** (both `<details>`) move into the left column, under the
  profile card.
- **The views** (Timeline, Search results, My bookmarks) become tabs in the top bar. The right
  column starts with a header naming the view, like the classic stream header.

## 3. Design

**Server (`server.py`), small:**
- Model: `account_counts(connection, user_id)` (two `COUNT(*)` queries; deleted posts don't
  count) and `trending_tags(db_path, viewer_id, now=None)` (reads through `select_posts`, then
  counts with `tags_in`; `now` lets tests fix the clock).
- View: `account_to_json` gains `post_count` and `like_count`; new `trends_to_json`.
- Controller: one `elif` for `GET /trends`, using `user_or_none`. It is quiet in the terminal,
  like the other polled routes.
- No database change. No new rule, so no new refusal codes.

**Page:**
- `index.html` is rearranged, not rewritten: a `<header class="top-bar">` (title, search form,
  `#views`, Colours, log-out), then `<div class="columns">` with `<aside class="dashboard">` and
  `<div class="stream">`. Every existing element keeps its `id`, so `app.js` keeps finding it.
- `app.js`: a `profileCard` drawn from the `GET /sessions` answer; `askForTrends` +
  `showTrends`; one line in each place that should refresh the counts. Words through
  `words.js` (`profile_posts_one/_other`, `profile_likes_one/_other`, `trends_heading`,
  `trends_none`, `stream_heading_*`).
- `style.css`: the new type sizes and the layout go in a `/* classic-layout */` block at the end;
  existing `font-size` rules for 24px, 44px and the like are changed where they are, because the
  size rule itself is what changed. `page-only/` stays a copy; it has no top bar or columns, so a
  test checks it still reads well (its selectors are untouched).

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/index.html` | top bar, columns, moved sections (ids kept) | change |
| `with-backend/style.css` + `page-only/style.css` | font sizes; `/* classic-layout */` block | change, add |
| `with-backend/app.js` | `profileCard`, `askForTrends`, `showTrends`, refresh lines | add, change |
| `with-backend/words.js` | new keys | add |
| `with-backend/server.py` | `account_counts`, `trending_tags`, `account_to_json`, `trends_to_json`, `GET /trends`, `log_message` | add, change |
| `with-backend/test_server.py` | new tests; route list | add, change |
| `AGENTS.md`, `DESIGN.md`, `README.md` | the layout, the new type-size rule, trends | change, add |

## 5. Depends on, and collides with

Depends on everything merged, and on **`design-system`**, which is built first. With it, the new
sizes are token values in `tokens.css`, and the top bar and the two columns are layout components;
features keep their blocks unchanged.
`japanese` Part B adds the Japanese for the new keys later.

## 6. Tests

- Model: counts ignore deleted posts and count likes received; trends count posts not tags (a
  post with `#cat #cat` counts once), only the last 24 hours, never old "date unknown" posts,
  leave out posts hidden by `block` and `report`, A–Z on ties, at most 10.
- Real server: `GET /trends` with and without a cookie; `GET /sessions` has the counts.
- Journey: post with a tag → it trends → delete the post → it stops trending.
- Page: every id `app.js` uses is still in `index.html`; both `style.css` files the same; the
  colour tests still pass; base font is 15px; no company name anywhere.
- Browser: wide (two columns), 900px (stacked), phone; light and dark; signed in and out.

## 7. Docs

`DESIGN.md`: a "Classic layout" section, and change the type-size sentence. `AGENTS.md`: the
page's three areas, `GET /trends`, the counts. `README.md`: one line.

## 8. Not in this plan

Following people, "who to follow", a profile page per person, the 2012 tweet box opening as a pop-up.

## 9. Size

**M.** About 400 lines, most of it CSS and tests.
