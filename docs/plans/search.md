Status: merged

# Search

## 1. What it does

A search box at the top of the page finds every post that has a word in it, such as `library`, or a
tag, such as `#cat`. The results show newest first, in place of the timeline, with a **Back to the
timeline** button. Anyone can search, signed in or not, because reading is open to everyone. A
search has its own address (`/?q=%23cat`), so the browser's Back button works, and the plan
`links-and-tags` can open a search when someone clicks a `#tag`.

## 2. Decisions for the owner

**2.1 How does the database find the posts?**

- **A. `LIKE '%word%'`** on `posts.text`. `LIKE` is SQLite's "does this text contain this
  pattern?" test; `%` means "any characters here". No new table. It reads every post each time,
  so it gets slower as posts grow, but this timeline is far too small for that to matter (the same
  reason `DESIGN.md` gives for having no `like_count` column). Two signs need care: in a `LIKE`
  pattern, `%` means "anything" and `_` means "any one character", so a search for `100%` or
  `a_b` must *escape* them (put `\` in front, and say `ESCAPE '\'`) to mean the signs themselves.
  It finds Japanese words of any length, because it looks for the characters, not for words.
- **B. SQLite FTS5 with the `trigram` tokenizer.** FTS5 is SQLite's full-text search: a second,
  *virtual* table (a table SQLite builds and reads in its own way) that keeps an *index*, like the
  index at the back of a book, so a search does not read every post. It is available in this
  Python (SQLite 3.53.4, `trigram` checked). The cost: the index is a second copy of every post's
  text. It must be kept in step with `posts` by three *triggers* (SQL that runs by itself after
  every `INSERT`, `UPDATE` and `DELETE` on `posts`), so that `edit-delete` editing or deleting a
  post also changes the index. It needs an upgrade function to build the index for old posts. And
  `trigram` cuts text into pieces of three characters, so a search of one or two characters
  cannot use the index at all. Many Japanese words are two characters (東京, 天気, 大学), so B still
  needs A's `LIKE` for those.
- **C. FTS5 with its default tokenizer (`unicode61`).** It splits text into words at spaces and
  punctuation. Japanese has no spaces, so a whole sentence such as 東京は雨です becomes **one**
  "word", and a search for 東京 finds nothing. Not usable while the `japanese` plan exists.

**Recommendation: A.** It is short, needs no new table and no upgrade, follows `edit-delete` for
free (it always reads the real text), and handles Japanese. All of it is inside one model function,
`search_posts`, so moving to B later changes that function and adds `upgrade_to_search`; nothing
else (route, JSON, page) changes. Section 3 says what B would add, for that day.

**2.2 Do tags get their own table?**

- **A. Found in the text.** `#cat` is searched with `LIKE '%#cat%'`, and then the model checks each
  found post with the tag rule (`TAG`, below), so `#cat` does not find `#catalog`.
- **B. A `tags` table**, one row per post per tag, `PRIMARY KEY (post_id, tag)`, like `likes`.
  Exact and fast. But a tag is already in the text, so the table is a second copy of a fact, and
  every change to a post's text (`edit-delete`) must rebuild its rows, in Python, because a SQL
  trigger cannot pick tags out of text.

**Recommendation: A.** One fact, one place. B is worth it only if the app later needs "the most
used tags", which is not asked for.

**2.3 Several words: all of them, or the exact phrase?**

- **A. Every word must appear**, in any order. `library late` finds "the library is open late
  tonight". Words are split at spaces; at most 5 words.
- **B. The exact phrase.**

**Recommendation: A.** It is what people expect from a search box. Japanese is usually typed
without spaces, so a Japanese search is one "word" and works as a phrase anyway.

**2.4 The route: `GET /search?q=…` or `GET /posts?q=…`?**

**Recommendation: `GET /search?q=…`.** `GET /posts?after=` is asked every second by every window;
mixing a second meaning into it would make `do_GET` guess which one was meant. A route of its own
is a new branch, not a change to an old one, and its answer can say more (`more`, below).

**2.5 Order and limit.**

**Recommendation:** newest first, at most **50** posts (`SEARCH_LIMIT`). The answer says
`"more": true` when there were more, and the page says "Showing the newest 50". No "load older
results" button (that belongs with `timeline-flow`).

**2.6 Can you like a post from the results?**

**Recommendation: not in this plan.** The results show each post's like count, but the heart is
shown greyed out (disabled), with the label "Open the timeline to like". Each post's heart is kept
by post id in `likeParts`; a second heart for the same post would need that changed, which every
like test depends on. A later small plan can add it.

**2.7 Do results update by themselves?**

**Recommendation: no.** Results are a snapshot of the moment you searched. The timeline underneath
keeps updating every second while hidden, so **Back to the timeline** shows it up to date at once.
Pressing **Search** again refreshes the results.

**2.8 Should the server print searches in its terminal?**

**Recommendation: no.** What a person searched for is their own business, and the terminal is
shown on a screen in class. `GET /search` joins `GET /posts` and `GET /likes` in the list
`log_message` does not print.

## 3. Design

### Database

**None** with the recommended choices: no new table, no new column, no upgrade function. Search
reads `posts` and `users` through `POSTS_WITH_AUTHORS`, which it does not change.

(If the owner picks 2.1 B: `upgrade_to_search(connection)` makes
`CREATE VIRTUAL TABLE posts_search USING fts5(text, content='posts', content_rowid='id',
tokenize='trigram')`, three triggers `posts_search_after_insert`, `…_after_delete`,
`…_after_update` (the delete and update ones write the special `'delete'` row FTS5 needs), and
`INSERT INTO posts_search(posts_search) VALUES ('rebuild')` for the old posts, all in one
transaction like `upgrade_to_accounts`. `search_posts` uses `MATCH` for words of 3 or more
characters and `LIKE` for shorter ones. About +40 lines and two more tests: an edited post is found
by its new text, a deleted one is not found.)

### Model (`server.py`, MODEL part)

New constants, next to `MAX_TEXT`:

```python
MAX_QUERY = 100        # characters in a search
MAX_QUERY_WORDS = 5    # words in a search
SEARCH_LIMIT = 50      # posts in one answer
# A tag: # and then letters, digits or _. Japanese counts as letters:
# 々, hiragana, katakana (with ー), kanji, and half-width katakana.
# Written with \u codes so app.js can hold exactly the same text.
TAG = re.compile(r"#([0-9A-Za-z_々぀-ヿ㐀-鿿ｦ-ﾟ]+)")
```

A tag ends at the first character that is not in that list: a space, punctuation, or an emoji. So
`#東京 は雨` has the tag `#東京`, but `#東京は雨` has the tag `#東京は雨`, because は is a letter.
Twitter works the same way. Tags match without caring about capital letters: `#Cat` is `#cat`.

New functions:

| Function | What it does |
|---|---|
| `check_query(query)` | Trims it. Refuses it if empty ("Type a word to search for."), longer than `MAX_QUERY`, or more than `MAX_QUERY_WORDS` words, with `RuleBroken`. Returns a list of words. A word that is a whole tag (`TAG.fullmatch`) stays as `#cat`; a lone `#` is an ordinary word. |
| `escape_like(word)` | Puts `\` in front of `\`, `%` and `_`, so `LIKE` reads them as themselves. |
| `tags_in(text)` | The set of tags in a text, in small letters, without the `#`: `{"cat", "東京"}`. `links-and-tags` may use it too. |
| `search_posts(db_path, query)` | `check_query`, then `POSTS_WITH_AUTHORS + " WHERE posts.text LIKE ? ESCAPE '\\' AND …"`, one `LIKE` per word, `ORDER BY posts.id DESC`. For each tag word it keeps only posts where `tags_in(text)` holds that tag. Returns `(rows, more)`: at most `SEARCH_LIMIT` rows, and whether there were more. Reads only: it never adds a user or changes a row. |

The search is not case-sensitive for A–Z (SQLite's `LIKE` already works this way). It is exact for
everything else: `ＡＢＣ` (full-width) is not `ABC`, and ひらがな is not カタカナ. See section 8.

### Route (CONTROLLER part)

| Request | In | Answer |
|---|---|---|
| `GET /search?q=library%20late` | `q`, the search, in the address | `200 {"posts": [post, …], "more": false}`, newest first; each post exactly as `post_to_json` makes it |
| `GET /search` (no `q`, or only spaces) | | `400 {"error": "Type a word to search for."}` |
| `GET /search?q=` + 101 characters, or 6 words | | `400` with the rule it broke |

No cookie is needed. `do_GET` gets one new branch, `elif url.path == "/search": self.give_search(url)`.
`give_search` reads `q` with `parse_qs`, calls `search_posts`, sends `400` on `RuleBroken`, and
otherwise `200 search_to_json(rows, more)`. The controller checks nothing itself.

### View (VIEW part)

`search_to_json(rows, more)` returns `{"posts": posts_to_json(rows), "more": more}`.

### Page

`index.html`, just under `<h1>`, visible signed in or not:

```html
<form id="search-form" role="search">
  <label for="search-box">Search posts</label>
  <input id="search-box" type="search" maxlength="100" placeholder="a word or #tag">
  <button type="submit">Search</button>
</form>
<section id="results" hidden aria-live="polite">
  <p class="results-row"><span id="results-title"></span>
    <button type="button" id="back-to-timeline" class="link-button">Back to the timeline</button></p>
  <ol id="results-list" class="timeline" aria-label="Search results, newest first"></ol>
</section>
```

`app.js`:

- Constants `MAX_QUERY`, `MAX_QUERY_WORDS`, `SEARCH_LIMIT` and `TAG`, with the same values and
  the same pattern text as the model (`TAG` written with the same `\u` codes, so a test can find
  the model's pattern inside `app.js`).
- `makePostItem(post)`: the part of `showPost` that builds one post's `<li>`, moved out unchanged.
  `showPost` keeps its `lastId` check and its `likeParts` line, and calls `makePostItem`. This is
  the one change to a shared function; it means a post looks the same in the timeline and in the
  results, and any later plan that changes how a post looks changes it in both.
- `queryProblem(query)`: the rules of `check_query`, returning the broken rule or `""`.
- `searchFor(query)`: **the contract for `links-and-tags`.** Checks the query, sets the address to
  `/?q=` + `encodeURIComponent(query)` with `history.pushState`, asks
  `fetch("/search?q=" + encodeURIComponent(query))`, and calls `showResults`. It puts the query in
  the search box too, so the person sees what was searched.
- `showResults(query, answer)`: hides `#timeline`, empties and fills `#results-list` with
  `makePostItem`, disables each heart in it, writes the title ("3 posts with “cat”", "No posts
  with “cat”", or "Showing the newest 50 posts with “cat”" when `more`), and shows `#results`.
- `showTimeline()`: hides `#results`, shows `#timeline`, empties the search box, and sets the
  address back to `/` with `history.pushState`.
- `searchFromAddress()`: on opening the page and on `popstate` (the browser's Back and Forward),
  reads `q` from `location.search`; runs the search if there is one, otherwise `showTimeline`
  without pushing a new address.
- Listeners: the search form's `submit`, the Back button's `click`, `Escape` in the search box,
  and `window` `popstate`.

**Contract for `links-and-tags`.** A tag in a post is a link to `/?q=` +
`encodeURIComponent("#" + tag)`, for example `<a href="/?q=%23cat">#cat</a>`, made with
`createElement`, never `innerHTML`. A click on it calls `event.preventDefault()` and then
`searchFor("#" + tag)`, so the page does not reload. Opening the link in a new tab also works,
because `searchFromAddress` reads the address. Which characters make a tag is `TAG`, in
`server.py` and `app.js`; `links-and-tags` uses it and does not define its own.

**Look.** New rules at the end of `style.css` under `/* search */`, using only the existing colour
variables, so `dark-mode` needs nothing extra. The same block is copied into `page-only/style.css`.
`page-only/` gets no search.

## 4. Files and functions touched

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | `do_GET`: one `elif` for `/search` | change |
| `with-backend/server.py` | `give_search` (controller) | add |
| `with-backend/server.py` | `log_message`: also skip `GET /search` | change |
| `with-backend/server.py` | `MAX_QUERY`, `MAX_QUERY_WORDS`, `SEARCH_LIMIT`, `TAG` | add |
| `with-backend/server.py` | `check_query`, `escape_like`, `tags_in`, `search_posts` (model) | add |
| `with-backend/server.py` | `search_to_json` (view) | add |
| `with-backend/app.js` | constants `MAX_QUERY`, `MAX_QUERY_WORDS`, `SEARCH_LIMIT`, `TAG` | add |
| `with-backend/app.js` | `showPost`: body moved into `makePostItem` | change |
| `with-backend/app.js` | `makePostItem`, `queryProblem`, `searchFor`, `showResults`, `showTimeline`, `searchFromAddress` | add |
| `with-backend/app.js` | the listeners at the end, and a call to `searchFromAddress()` | change (lines added) |
| `with-backend/index.html` | `#search-form` and `#results`, under `<h1>` | add |
| `with-backend/style.css`, `page-only/style.css` | `/* search */` block at the end | add |
| `with-backend/test_server.py` | new methods at the end of all four classes | add |
| `with-backend/test_server.py` | the expected set in the "the page asks only for these routes" test gains `/search` | change |
| `AGENTS.md` | file table rows for `server.py`/`app.js`; the model and view function lists | change (names added) |
| `DESIGN.md` | new section "Search"; new rows in the adversarial review | add |
| `README.md` | one line under the things to try | add |

No upgrade function, no `POSTS_WITH_AUTHORS` change, no `post_to_json` change, no
`checkForNewPosts` change.

## 5. Depends on, and collides with

- **`accounts`** (depends): built against its `server.py`. Search needs no sign-in, so it uses
  neither `user_for_session` nor `user_or_none`.
- **`links-and-tags`** (it depends on this): it uses `TAG`, `tags_in` and `searchFor`, and the
  `/?q=` address. **Build `search` first.** Both change how a post is drawn: after this plan, that
  is `makePostItem`, not `showPost`.
- **`edit-delete`**: with 2.1 A there is no index to keep in step; search reads the current text.
  If `edit-delete` hides deleted posts with a condition (for example `deleted_at IS NULL`) rather
  than deleting the row, `search_posts` needs the same condition; whichever plan merges second
  adds it, with a `JourneyTest` that an edited post is found by its new words and not its old
  ones, and a deleted post is not found. Old versions of a post are never searched.
- **`block`, `report`**: the same as above. Any post hidden from the timeline must be hidden from
  search. Whichever merges second adds its condition to `search_posts`.
- **`replies`, `timestamps`, `timeline-flow`, `pictures`, `who-liked`, `place`, `edit-delete`**:
  all change how a post is drawn. They collide with the `makePostItem` move in `app.js`. Merging
  `search` early keeps this small: later branches put their change inside `makePostItem`.
- **`japanese`**: search adds new words on the screen (the label, the button, the titles, the
  error messages); `japanese` must translate them. Japanese search works already with 2.1 A.
  Matching full-width with half-width letters would need Unicode normalisation (NFKC), which
  belongs to `japanese` if wanted.
- **`long-posts`**: no collision; the query has its own limit, `MAX_QUERY`.
- **`rate-limit`**: search is not limited by this plan. `LIKE` reads every post, so a script asking
  thousands of times a second would slow the server; `rate-limit` may add `/search` to its list.
- **`dark-mode`**: none; the new CSS uses only the colour variables.

## 6. Tests

**`ModelTests`** (new methods at the end):

- A word is found, and capital letters do not matter (`Library` finds `library`).
- Results are newest first.
- `100%` finds "100% sure" and not "100 sure"; `a_b` finds `a_b` and not `axb`; a `\` is
  searched as itself.
- Two words: only posts with both are found, in any order.
- An empty search, a search of only spaces, a 101-character search, and a 6-word search are each
  refused with their own sentence.
- `#cat` finds "#cat" and "#Cat", and not "#catalog" or "cat".
- A Japanese word of two characters is found inside a sentence (東京 in 東京は雨です), and the tag
  `#東京` is found in "#東京 は雨".
- 51 matching posts give 50 rows and `more` true; 50 give 50 and `more` false.
- Searching changes no row: the row counts of `users`, `posts` and `likes` are the same after.

**`RealServerTest`**:

- `GET /search?q=cat` without a cookie answers `200` with `posts` and `more`.
- `GET /search?q=%23cat` (the `#` encoded) finds the tag.
- `GET /search` with no `q` answers `400` and a reason.

**`JourneyTest`** (one new method): two people sign up and post, one with `#cat`, one with
`catalog`; the page's own request `GET /search?q=%23cat` returns only the first; after every
search, the ids returned are the same as the ids SQL finds with `LIKE` on the database file.

**`PageAndServerAgreeTest`**:

- `app.js` asks for `/search`, and the server answers `GET /search?q=x` with neither 404 nor 501.
- `server.TAG.pattern` appears in `app.js` exactly.
- `MAX_QUERY`, `MAX_QUERY_WORDS` and `SEARCH_LIMIT` have the same numbers in both.
- `app.js` has a function `searchFor` (the contract `links-and-tags` calls).

## 7. Docs to update

- `AGENTS.md`: add `check_query`, `escape_like`, `tags_in`, `search_posts` to the model list and
  `search_to_json` to the view list; say in the `app.js` row that it also searches.
- `DESIGN.md`: a new section "Search", with the `GET /search` interface row, why `LIKE` and not
  FTS5, why tags are found in the text and not kept in a table, and what Japanese search can and
  cannot do. New rows in the adversarial review table for those choices.
- `README.md`: one thing to try: "Post `#cat`, then click Search with `#cat`."

## 8. Not in this plan

- Liking from the results, and results that update by themselves.
- Highlighting the matched word in the results.
- Matching full-width and half-width letters, or hiragana and katakana, as the same (`japanese`).
- Tags in languages other than English and Japanese (for example `#café` ends at `é`).
- Searching by author (`@aiko`), by date, or a list of the most used tags.
- Loading older results after the first 50 (`timeline-flow`).
- Search in `page-only/`.
- FTS5 (section 2.1 B), until the timeline is big enough to need it.

## 9. Size

**M**, about 450 lines: `server.py` about 80, `app.js` about 110, `index.html` about 15, CSS about
35 in each of the two files, tests about 140, docs about 40.

## Changes made at approval (orchestrator)

- **No paging: at most 50 results**, newest first, with `"more": true` when there are more. That
  is what decision 5 recommended; the owner confirmed it.
- **This plan owns the `TAG` pattern.** `links-and-tags` uses it.
- `makePostItem` (splitting `showPost`) is built in `groundwork`, not here. Results are listed
  through the shared visibility filter from `groundwork`.
