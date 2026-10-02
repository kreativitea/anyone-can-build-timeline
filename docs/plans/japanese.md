Status: Part A built on branch japanese-words, awaiting merge

# Japanese

This plan is built in **two parts**, at two different times (the owner's decision):

- **Part A, "words mechanism"**, is built right after `accounts`, before every other feature. It
  moves every word the screen shows into one table, keyed by a short **code**. At first the table
  has English only.
- **Part B, "Japanese dictionary"**, is built last, after every other feature. It adds the Japanese
  for every key in the table, and the few things that only matter once there is Japanese.

Between the two, every other feature follows **the contract** in section 3.4. That is the part other
plans should copy.

## 1. What it does

The whole app can be read in Japanese or in English. When you first open it, it uses your
browser's language: Japanese if your browser prefers Japanese, English otherwise. A button at the top
(*日本語* / *English*) switches, and this browser remembers your choice. Posts, display names and
account names are never translated: they are shown exactly as people wrote them.

## 2. Decisions for the owner

1. **Do errors that only the controller makes get a code too?** These are answers like *The request
   must be JSON* or *There is nothing at /x*. The page never causes them.
   - (a) Yes: every answer with `"error"` also has `"code"`. One simple rule, and a test can check it.
   - (b) No: only rules in the model get a code.
   - **Recommendation: (a).** "Every error has a code" is easier to follow and to test than "every
     error except some". It costs nine table entries.

2. **What does the language button do between Part A and Part B?** In Part A there is no Japanese yet.
   - (a) The button is in `index.html` but `hidden`. Part B removes `hidden`.
   - (b) The button shows, and Japanese falls back to English for every key.
   - **Recommendation: (a).** A button that seems to do nothing looks broken. Part A still builds and
     tests the switch; a person just cannot see it yet.

3. **Should later features write their own Japanese, or leave it all for Part B?**
   - (a) Leave it all for Part B. Part B writes every Japanese entry at once.
   - (b) Each feature writes its Japanese as it goes.
   - **Recommendation: (a).** One writer gives one voice: the same polite form and the same word for
     the same thing everywhere. The test in Part B makes sure nothing is forgotten.

4. **The voice and the key words in Japanese.**
   - Polite form (です・ます) for every sentence, short and plain.
   - A post is **投稿** (not ポスト, which also means a letterbox and is X's own word). Like is
     **いいね**. Account name is **アカウント名**, display name is **表示名**. Log in **ログイン**,
     log out **ログアウト**, sign up **新規登録**.
   - **Recommendation:** these words. Before Part B is merged, a native speaker reads the whole
     table once on the real screen. Who will that be?

5. **An account name typed in full-width letters** (`ａｉｋｏ`). A Japanese keyboard often types
   these when the input method is on.
   - (a) Refuse it, as now, with a message that says *half-width* (半角) letters and numbers.
   - (b) Turn full-width letters into normal ones (`unicodedata.normalize("NFKC", …)`) in
     `check_name`, and the same in the page.
   - **Recommendation: (a).** It changes no rule from `accounts`, and nothing is changed silently.
     The Japanese message in Part B says exactly what to type. (b) can be its own small plan later.

6. **Email is written by the server, and the server does not know the reader's language**
   (this matters for `reply-email`).
   - (a) Each email has both languages: English first, then Japanese.
   - (b) Save a language for each user, in a new column.
   - **Recommendation: (a).** It needs no new data. The server still holds no words of the page;
     the email text is that plan's own, and Part B adds the Japanese half.

## 3. Design

### 3.1 Part A: the server (model and view)

The idea: **the server sends a code, and the page chooses the words.** The server never translates.
It keeps one English sentence for each code, so the terminal, the tests and an old page that does
not know codes still read well.

**Model.** One new base class, and the two old ones built on it:

```python
class Problem(Exception):
    """Something the request cannot do. code names the rule; values fill in its sentence."""

    def __init__(self, code, **values):
        Exception.__init__(self, PROBLEMS[code].format(**values))   # str(problem) is English
        self.code = code
        self.values = values


class RuleBroken(Problem):       # 400: a rule was broken
    ...

class NotSignedIn(Problem):      # 401: nobody is logged in, or the login was wrong
    ...
```

A code that is not in `PROBLEMS` raises `KeyError` at once, so a forgotten entry fails the first
test that reaches it. `str(problem)` gives the same English as today, so the old tests that read
`"error"` still pass.

`PROBLEMS` is one table in the model, next to `MAX_TEXT`. It holds every code and its English
sentence. A value is written as `{limit}`, and filled in with Python's `str.format`. The English is
exactly what `server.py` says today:

| Code | English (`{…}` is a value) | Raised by |
|---|---|---|
| `name_empty` | The name must not be empty. | `check_name` |
| `name_too_long` | The name must be {limit} characters or fewer. | `check_name` |
| `name_characters` | The account name may use only letters, numbers and _. | `check_name` |
| `name_taken` | That account name is taken. | `create_account` |
| `display_name_too_long` | The display name must be {limit} characters or fewer. | `check_display_name` |
| `display_name_hidden` | The display name must not have hidden characters or line breaks. | `check_display_name` |
| `password_too_short` | The password must be at least {limit} characters. | `check_password` |
| `password_too_long` | The password must be {limit} characters or fewer. | `check_password` |
| `text_empty` | The post must not be empty. | `check_text` |
| `text_too_long` | The post must be {limit} characters or fewer. | `check_text` |
| `like_post_id_missing` | The like must say which post it is for. | `check_post_id` |
| `post_missing` | That post does not exist. | `add_like` |
| `like_already` | You have already liked that post. | `add_like` (twice) |
| `like_not_there` | You have not liked that post. | `remove_like` |
| `login_wrong` | The account name or password is wrong. | `log_in` (three times) |
| `login_needed` | Please log in first. | `user_for_session` |
| `login_ended` | Your login has ended. Please log in again. | `user_for_session` |
| `after_not_number` | 'after' must be a whole number. | controller, `do_GET` |
| `not_json` | The request must be JSON. | controller, `read_json` (twice) |
| `not_json_object` | The request must be a JSON object. | controller, `read_json` |
| `file_missing` | The file {file} is missing. | controller, `do_GET` |
| `nothing_here` | There is nothing at {path} | controller, `do_GET` |
| `nothing_to_send` | There is nothing to send to {path} | controller, `do_POST` |
| `delete_where` | You can only take back a like at /likes, or log out at /sessions | controller, `do_DELETE` |

`WRONG_LOGIN` stays, but its value becomes the code: `WRONG_LOGIN = "login_wrong"`. So the comment
in `app.js` that points at it stays true.

Every `raise RuleBroken("An English sentence.")` becomes `raise RuleBroken("code", limit=…)`. For
example: `raise RuleBroken("text_too_long", limit=MAX_TEXT)`. Nothing else in the model changes.

**View.** One new function:

```python
def problem_to_json(problem):
    """A refusal: the English sentence, its code, and the values that fill it in."""
    return {"error": str(problem), "code": problem.code, "values": problem.values}
```

So a too-long post is answered with:
`{"error": "The post must be 280 characters or fewer.", "code": "text_too_long", "values": {"limit": 280}}`.
`"error"` stays for old pages, for the terminal and for anyone reading with `curl`.

**Controller.** One new helper, `send_problem(self, status, problem)`, which calls
`self.send_json(status, problem_to_json(problem))`. Every line that now says
`self.send_json(4xx, {"error": …})` becomes `self.send_problem(4xx, problem)`: 15 lines, each a
one-line change. The controller's own errors make a `Problem` without raising it:
`self.send_problem(404, Problem("nothing_here", path=url.path))`. No route, status or JSON key
changes.

`PAGE_FILES` gets one new line: `"/words.js": ("words.js", "text/javascript; charset=utf-8")`.

**Database.** No change. No upgrade function.

### 3.2 Part A: the page

**A new file, `with-backend/words.js`**, holds every word the page shows, and nothing else. It is a
plain script (there is no build step), loaded before `app.js`, so `app.js` can read `WORDS`:

```js
// Every word the page shows, by code. Part B adds a `ja:` line under each `en:`.
// One entry per code, always written in this shape, so test_server.py can read it.
const WORDS = {
  // accounts
  text_too_long: {
    en: "The post must be {limit} characters or fewer.",
  },
  ...
  // <slug of a later feature>
};
```

The shape of an entry is fixed: the code, then `en:` on its own line, then (from Part B) `ja:` on
its own line, each in double quotes. Python reads this file with one regular expression (a pattern
for finding text); see section 6.

It holds every code in `PROBLEMS`, with the **same** English, plus the words that only the page uses:

| Key | English | Where |
|---|---|---|
| `app_name` | Timeline | `<title>`, `<h1>` |
| `log_in_heading` · `log_in_button` | Log in | login form |
| `sign_up_heading` · `sign_up_button` | Sign up | sign-up form |
| `account_name_label` | Account name | both forms |
| `password_label` | Password | login form |
| `new_password_label` | Password ({min} characters or more) | sign-up form |
| `display_name_label` | Display name | sign-up form |
| `display_name_example` | Aiko Tanaka | sign-up placeholder (an example name, so it is translated too) |
| `signed_in_as` | Signed in as | above the post form |
| `log_out` | Log out | button |
| `post_prompt` | What is happening? | label and placeholder |
| `post_button` | Post | button |
| `timeline_label` | Posts, newest first | `aria-label` of the timeline |
| `like_label` | Like this post | heart, `aria-label` |
| `unlike_label` | Unlike this post | heart, `aria-label` |
| `cannot_reach` | Cannot reach the server. Trying again every second. | status line |
| `login_fields_empty` | Please type your account name and your password. | `logIn` |
| `login_to_like` | Please log in to like a post. | `pressHeart` |
| `switch_language` | 日本語 | the language button: always the *other* language, in its own words |

The placeholder `aiko` and the `@` sign are not words, so they stay as they are.

**New functions in `app.js`** (one block, near the top, under `// Words and languages`):

- `language`: `"en"` or `"ja"`, the language now shown.
- `chooseLanguage()`: the saved choice from `localStorage` (key `"language"`), if it is `"en"` or
  `"ja"`. Otherwise the first language in `navigator.languages`: `"ja"` if it starts with `ja`,
  otherwise `"en"`. Reading `localStorage` is inside `try … catch`: some browsers refuse it.
- `fill(template, values)`: replaces each `{name}` with `values[name]`. It only replaces; it never
  reads a value as a template, so a value cannot add words of its own.
- `say(key, values)`: the words for this key in this language, filled in. If there are no words in
  this language, it uses the English (this is how Part A works before there is any Japanese).
- `sayCount(key, n)`: for words with a number, such as *1 new post* and *3 new posts*. It picks
  `key_one` or `key_other` with the browser's own `Intl.PluralRules(language)` (built into every
  browser, so not a library). Japanese has no plural, so it always picks `_other`. No key uses it in
  Part A; it is here so `timeline-flow`, `who-liked` and others do not each invent one.
- `showWords()`: walks every element with a `data-words` attribute and sets its words (see below).
  Then it sets `document.documentElement.lang = language`, and writes the status line and every
  heart's `aria-label` again in the new language.
- `setLanguage(newLanguage)`: saves the choice in `localStorage` (inside `try … catch`), sets
  `language`, and calls `showWords()`.
- `showProblem(answer)`: shows the server's refusal: `say(answer.code, answer.values)` if `WORDS` has
  that code, otherwise `answer.error`. So a page that is older or newer than the server still shows
  something true.

**Changed functions in `app.js`:**

- `showStatus(words)` becomes `showStatus(key, values, fallback)`. It keeps what it was told
  (`statusNow = {key, values, fallback}`) so `showWords()` can write it again after a switch.
  `showStatus("")` still clears the line.
- `showSignedOut(reason)` takes a key instead of a sentence.
- `showLike` uses `say("like_label")` / `say("unlike_label")`.
- `accountProblem` and `textProblem` return `{key, values}` or `null`, instead of a sentence. They use
  the **same codes as the model**, so the page and the server name a rule the same way. For example
  `textProblem` returns `{key: "text_too_long", values: {limit: MAX_TEXT}}`.
- `checkForNewPosts` asks `statusNow.key === "cannot_reach"` instead of comparing two sentences.
- `logIn`, `signUp`, `sendPost`, `pressHeart`: `showStatus(answer.error)` and
  `showSignedOut(answer.error)` become `showProblem(answer)`.
- `CANNOT_REACH` is removed; its words are the key `cannot_reach`.
- At the bottom: `language = chooseLanguage(); showWords();` before `askWhoIAm()`, and one listener
  for the language button.

**`index.html`.** Each visible word gets an attribute that names its key. The English stays inside
the element, so the page reads well even before `app.js` runs.

- `data-words="key"`: the element's text.
- `data-words-placeholder="key"`, `data-words-aria-label="key"`: that attribute.
- *Signed in as* is now inside its own `<span data-words="signed_in_as">`, so the names next to it
  are never touched.
- `<script src="words.js"></script>` before `<script src="app.js"></script>`.
- The language button, at the top of `<main>`, beside the `<h1>`:
  `<button type="button" id="language" class="link-button" lang="ja" hidden>日本語</button>`.
  It carries its own `lang`, because its word is always in the other language. In Part A it is
  `hidden` (decision 2).
- `<html lang="en">` stays as the starting value; `showWords()` changes it.

`<html lang>` matters for two reasons: a screen reader uses it to pick a voice, and the browser
uses it to pick the right shape of a kanji (Chinese and Japanese draw some of them differently).

### 3.3 Part B: the Japanese dictionary

Built last. By then every other feature has added its English keys, so Part B sees them all.

- **`words.js`:** one `ja:` line under every `en:` line. Each entry's diff is one added line.
  The first draft for the keys known today is in the table at the end of this section.
- **`index.html`:** remove `hidden` from the language button.
- **`style.css`** (and its copy in `page-only/`), at the end under `/* japanese */`:
  - Japanese fonts in the list, after the ones there now, so Japanese text (in any post, in either
    language) is drawn with a Japanese font:
    `body { font-family: system-ui, -apple-system, "Segoe UI", "Hiragino Sans", "Yu Gothic UI", "Noto Sans JP", sans-serif; }`
  - `:lang(ja) h1, :lang(ja) h2, :lang(ja) button { word-break: keep-all; }` and
    `word-break: auto-phrase` where the browser knows it, so a short heading is not broken in the
    middle of a word. Post text keeps `overflow-wrap: anywhere`.
- **Time and date:** every place the page shows a time uses the browser's own
  `Intl.DateTimeFormat(language, …)` and `Intl.RelativeTimeFormat(language, …)`, never words of its
  own. Today `posted_at` is `"14:05"`, which reads the same in both languages, so there is nothing to
  do until `timestamps` lands. If it has landed, Part B checks that it passes `language` (see
  section 5).
- **A new test:** every key in `words.js` has `ja:`, with the same `{values}` as its `en:`.
- **Checked by hand** (section 6): the input method, a screen reader, and the whole screen read once
  by a native speaker.

**First draft of the Japanese** (for review, decision 4; Part B will add the keys of later features):

| Key | 日本語 |
|---|---|
| `app_name` | タイムライン |
| `log_in_heading` · `log_in_button` | ログイン |
| `sign_up_heading` · `sign_up_button` | 新規登録 · 登録する |
| `account_name_label` | アカウント名 |
| `password_label` | パスワード |
| `new_password_label` | パスワード（{min}文字以上） |
| `display_name_label` | 表示名 |
| `display_name_example` | 田中 愛子 |
| `signed_in_as` | ログイン中： |
| `log_out` | ログアウト |
| `post_prompt` | いま、何してる？ |
| `post_button` | 投稿する |
| `timeline_label` | 投稿（新しい順） |
| `like_label` · `unlike_label` | この投稿にいいねする · いいねを取り消す |
| `cannot_reach` | サーバーにつながりません。1秒ごとにもう一度試しています。 |
| `login_fields_empty` | アカウント名とパスワードを入力してください。 |
| `login_to_like` | いいねするにはログインしてください。 |
| `switch_language` | English |
| `name_empty` | アカウント名を入力してください。 |
| `name_too_long` | アカウント名は{limit}文字以内にしてください。 |
| `name_characters` | アカウント名には半角の英字・数字・_ だけが使えます。 |
| `name_taken` | そのアカウント名はすでに使われています。 |
| `display_name_too_long` | 表示名は{limit}文字以内にしてください。 |
| `display_name_hidden` | 表示名に見えない文字や改行は使えません。 |
| `password_too_short` | パスワードは{limit}文字以上にしてください。 |
| `password_too_long` | パスワードは{limit}文字以内にしてください。 |
| `text_empty` | 何か書いてから投稿してください。 |
| `text_too_long` | 投稿は{limit}文字以内にしてください。 |
| `like_post_id_missing` | どの投稿へのいいねかがわかりません。 |
| `post_missing` | その投稿は見つかりません。 |
| `like_already` | この投稿にはもういいねしています。 |
| `like_not_there` | この投稿にはまだいいねしていません。 |
| `login_wrong` | アカウント名かパスワードが違います。 |
| `login_needed` | 先にログインしてください。 |
| `login_ended` | ログインの期限が切れました。もう一度ログインしてください。 |
| `after_not_number` | 'after' は整数で指定してください。 |
| `not_json` | リクエストはJSONで送ってください。 |
| `not_json_object` | リクエストはJSONオブジェクトで送ってください。 |
| `file_missing` | ファイル {file} が見つかりません。 |
| `nothing_here` | {path} には何もありません。 |
| `nothing_to_send` | {path} には送れません。 |
| `delete_where` | 取り消せるのは /likes のいいねと /sessions のログインだけです。 |

*Signed in as* works in both languages because it is a label before the names, not a sentence
around them.

### 3.4 The contract: what every later feature does

This is for every plan merged after Part A. Copy it into your plan's section 3.

1. **A new rule in the model** raises a code, never a sentence:
   `raise RuleBroken("reply_parent_missing")`, or with values:
   `raise RuleBroken("picture_too_big", limit=MAX_PICTURE_MB)`.
   Use `NotSignedIn` for 401, and `Problem` for a refusal the controller makes itself
   (`self.send_problem(404, Problem("nothing_here", path=path))`).
2. **The code goes in `PROBLEMS`** in the model, with its English sentence, at the end of the table,
   under a comment with your slug: `# replies`.
3. **The same code goes in `words.js`**, at the end of `WORDS`, under the same comment, with
   **exactly the same English** in `en:`. Do not write `ja:`; Part B writes all of the Japanese.
4. **Naming a code:** lower case with `_`. First the thing it is about (`text_`, `like_`, `reply_`,
   `picture_`, `place_`, `report_`), then what is wrong (`_empty`, `_too_long`, `_too_big`,
   `_missing`, `_not_yours`, `_already`, `_too_fast`). A value is named by what it is: `limit`,
   `seconds`, `count`, `path`. The name inside `{…}` and the keyword in Python are the same word.
5. **A word the page shows** (a button, a label, a status, an `aria-label`) is a key in `words.js`,
   never a string in `app.js` or `index.html`. In `index.html`: `data-words="key"` (or
   `data-words-placeholder`, `data-words-aria-label`), with the English left inside. In `app.js`:
   `say("key", values)` or `showStatus("key", values)`.
6. **Words with a number** are two keys, `key_one` and `key_other`, shown with `sayCount("key", n)`.
7. **One sentence is one key.** Never join pieces into a sentence (`say("a") + name + say("b")`):
   word order is different in Japanese. Write one template with `{name}` in it.
8. **What people wrote is never a key:** posts, display names, account names, tags, place names.
   They go into the page with `textContent`, as today.
9. **A time or a date** is formatted with `Intl.DateTimeFormat(language, …)` or
   `Intl.RelativeTimeFormat(language, …)`, never with words of your own.
10. **The server never translates.** No Japanese in `server.py`, and no `Accept-Language`.

`make test` catches each mistake (section 6): a code raised but missing from `PROBLEMS`; a code in
`PROBLEMS` but missing from `words.js`; English that differs between the two; a `{value}` in one and
not the other; a key used in `app.js` or `index.html` but missing from `words.js`; a refusal sent
without a code; a sentence in `showStatus("…")`; Japanese in `server.py`.

## 4. Files and functions touched

### Part A: words mechanism

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/server.py` | `PAGE_FILES` | change (one line added: `/words.js`) |
| `with-backend/server.py` | controller: `send_problem` | add |
| `with-backend/server.py` | controller: `do_GET`, `do_POST`, `do_DELETE`, `read_json`, `signed_in_user`, `sign_up`, `log_in`, `take_post`, `take_like` | change (each `send_json(4xx, {"error": …})` line becomes `send_problem`; 15 lines) |
| `with-backend/server.py` | model: `PROBLEMS`, `Problem` | add |
| `with-backend/server.py` | model: `RuleBroken`, `NotSignedIn`, `WRONG_LOGIN` | change (built on `Problem`; `WRONG_LOGIN` holds the code) |
| `with-backend/server.py` | model: `check_name`, `check_display_name`, `check_password`, `check_text`, `check_post_id`, `create_account`, `log_in`, `user_for_session`, `add_like`, `remove_like` | change (each `raise` line only) |
| `with-backend/server.py` | view: `problem_to_json` | add |
| `with-backend/words.js` | `WORDS` (English only) | add (new file) |
| `with-backend/app.js` | `language`, `chooseLanguage`, `fill`, `say`, `sayCount`, `showWords`, `setLanguage`, `showProblem`, `statusNow` | add |
| `with-backend/app.js` | `showStatus`, `showSignedOut`, `showLike`, `accountProblem`, `textProblem`, `checkForNewPosts`, `askWhoIAm`, `logIn`, `signUp`, `logOut`, `sendPost`, `pressHeart`, start-up lines at the bottom | change |
| `with-backend/app.js` | `CANNOT_REACH` | remove |
| `with-backend/index.html` | every visible word: `data-words*` attributes; `<span>` round *Signed in as*; language button (`hidden`); `<script src="words.js">` | change |
| `with-backend/style.css` + `page-only/style.css` | none in Part A (the button uses `.link-button`) | — |
| `with-backend/test_server.py` | new tests at the end of `ModelTests`, `RealServerTest`, `PageAndServerAgreeTest` | add |
| `with-backend/test_server.py` | any accounts test that compares a whole error answer with `assertEqual(answer, {"error": …})`, or looks for an English sentence in `app.js` | change (read `answer["error"]`; look in `words.js`) |
| `AGENTS.md`, `DESIGN.md`, `README.md` | new sections (section 7) | add |

### Part B: Japanese dictionary

| File | Function or section | Add / change |
|---|---|---|
| `with-backend/words.js` | every entry: one `ja:` line | change |
| `with-backend/index.html` | language button: remove `hidden` | change |
| `with-backend/style.css` + `page-only/style.css` | `/* japanese */` at the end: font list, `:lang(ja)` line breaks | add |
| `with-backend/app.js` | only if a later feature formats a time without `language` | change (that one call) |
| `with-backend/test_server.py` | new tests at the end of `PageAndServerAgreeTest` and `JourneyTest` | add |
| `AGENTS.md`, `DESIGN.md`, `README.md` | the sections Part A added: one line each | change |

## 5. Depends on, and collides with

- **Depends on `accounts`.** Part A converts the errors `accounts` adds, so it starts from that code.
- **Part A collides with every plan, but only once, and early.** Every plan in progress was written
  with `RuleBroken("An English sentence.")`. After Part A is merged, each of those branches is
  rebased and changes those lines to codes, following section 3.4. The tests make this impossible to
  forget: an English sentence in `RuleBroken` fails `make test`. **The orchestrator should tell the
  other plans about section 3.4 now**, so they are written with codes from the start.
- **Hot spots inside Part A:** the 15 `send_json(4xx, …)` lines in the controller, and
  `showStatus` / `showSignedOut` in `app.js`. Other branches change these same lines. Each change is
  one line, so a conflict is small and easy to read.
- **`words.js` and `PROBLEMS`** become the shared tables. Each branch adds its block at the end,
  under its own slug comment. Two branches that both add at the end will meet there; the fix is to
  keep both blocks.
- **Part B depends on every other plan** having merged: it translates their keys too. It collides
  with none of them, because it changes only `ja:` lines, one button and the end of `style.css`.
- Notes for single plans:
  - `timestamps`: show times with `Intl.RelativeTimeFormat(language)` (*5 minutes ago* /
    *5分前*), not with words of its own. Its `posted_at` change does not touch this plan.
  - `timeline-flow`, `who-liked`, `report`: counts use `sayCount` (*1 new post* / *3 new posts*).
  - `links-and-tags`, `search`: `#東京` is a tag. Match letters with Unicode in mind (in JavaScript,
    `/[\p{L}\p{N}_]+/u`; in Python, `\w`, which already includes kanji and kana). Japanese has no
    spaces between words, so search must look for the text anywhere in a post, not for whole words.
  - `long-posts`: the limit is the value `{limit}`, so no words change.
  - `rate-limit`: its refusal carries `seconds` as a value.
  - `reply-email`: see decision 6. The email is written by the server; Part B adds its Japanese half.
  - `dark-mode`, `drafts`: they also keep things in `localStorage`, under their own keys. `dark-mode`
    adds a button in the same place at the top of the page as the language button; put them side by
    side in one `<div class="top-buttons">` (whichever merges second adds it).
  - `place`: a place name is written by people, so it is never translated.

## 6. Tests

### Part A

**`ModelTests`**
- `RuleBroken("text_too_long", limit=280)` has `code == "text_too_long"`, `values == {"limit": 280}`,
  and `str()` is exactly *The post must be 280 characters or fewer.*
- `save_post` with empty text raises with code `text_empty`; with 281 characters, `text_too_long`
  and `limit` 280.
- A wrong name and a wrong password both raise `NotSignedIn` with code `login_wrong`.
- Every template in `PROBLEMS` can be filled: for each code, find its `{names}` and call `format`
  with a value for each. None fails.

**`RealServerTest`**
- An empty post answers 400 with `error`, `code: "text_empty"` and `values: {}`.
- A post with no cookie answers 401 with `code: "login_needed"`.
- A request that is not JSON answers 400 with `code: "not_json"`.
- `GET /nothing` answers 404 with `code: "nothing_here"` and `values: {"path": "/nothing"}`.
- `GET /words.js` answers 200 with `text/javascript`.

**`PageAndServerAgreeTest`** (Python reads `server.py`, `words.js`, `app.js` and `index.html` as text)
- Reading `words.js`: the number of entries found equals the number of `en:` lines, so an entry
  written in the wrong shape is not quietly skipped.
- Every code in `server.PROBLEMS` is in `words.js`, and its `en:` is exactly the same English.
- Every code raised in `server.py` (found with the pattern `(RuleBroken|NotSignedIn|Problem)\("([a-z_]+)"`)
  is in `PROBLEMS`. No `RuleBroken("` is followed by a capital letter (a sentence).
- No `send_json(4…, {"error"` is left in `server.py`: every refusal goes through `send_problem`.
- Every key `app.js` uses (`say("…"`, `sayCount("…"`, `showStatus("…"`, `showSignedOut("…"`) and every
  `data-words…="…"` in `index.html` is in `words.js`. For `sayCount`, both `_one` and `_other`.
- `showStatus(` and `showSignedOut(` are never called with a sentence (a string with a space in it).
- `index.html` loads `words.js` before `app.js`.
- `server.py` has no Japanese characters (kana or kanji): the server never translates.

### Part B

**`PageAndServerAgreeTest`**
- Every entry in `words.js` has `ja:`, not empty.
- In every entry, `en:` and `ja:` have the same `{names}`.

**`JourneyTest`** (a whole journey, with rows read with SQL after each step)
- Sign up with the display name *田中 愛子*; the `users` row holds exactly *田中 愛子*.
- Post Japanese text; `GET /posts` gives it back unchanged, and the `posts` row holds the same text.
- A post of 280 Japanese characters is saved; 281 is refused with `code: "text_too_long"` and no row.
- An account name in full-width letters (`ａｉｋｏ`) is refused with `code: "name_characters"`, and
  no `users` row is added.

**Checked by hand**, in a browser (the tests never run JavaScript):
- With the browser set to Japanese, the page opens in Japanese; set to English, in English.
- The button switches every word on the screen at once, including the status line and the hearts'
  `aria-label`; a reload keeps the choice.
- Type a Japanese display name with the input method on, and press Enter to choose the kanji: the
  form must **not** be sent until you press Enter again. (Safari has been known to send it.)
- A screen reader reads Japanese with a Japanese voice.
- A native speaker reads every screen once (decision 4).

## 7. Docs to update

- **`AGENTS.md`** (Part A): a row for `words.js` in the file table; `Problem`, `PROBLEMS` in the model
  list; `problem_to_json` in the view list; a new short section *Words* that holds section 3.4 (the
  contract). Part B: one line, that Japanese is complete and every new key needs `ja:` too, from
  then on.
- **`DESIGN.md`** (Part A): a new section *Languages*: the server sends codes, the page holds the
  words; the error answer shape in the interfaces table. Two rows in the adversarial review: *the
  server could translate, using `Accept-Language`* (rejected: then the words live in two places and
  the server must know the reader); *`words.js` could be inside `app.js`* (rejected: one file that
  only grows by adding is easier to merge, and easier for a translator).
- **`README.md`** (Part B): under *Things to try*: switch to 日本語, then reload.

## 8. Not in this plan

- `page-only/` stays in English. It is a demo (see `docs/plans/README.md`), and it has no server codes.
- Translating posts or names. People's own words are never changed.
- A third language. The mechanism allows it, but the tests check for `en` and `ja` exactly.
- Turning full-width account names into normal ones (decision 5).
- Saving a language on the server, for each user (decision 6).
- Counting characters the same way on both sides. JavaScript counts 😀 as 2 and Python as 1, so the
  page may refuse a post the server would take. This is true today, for every language; it belongs
  with `long-posts` or a small plan of its own.
- Furigana (small reading guides above kanji), and vertical writing.

## 9. Size

- **Part A: M**, about 300 lines. `server.py` about +45 and 25 changed lines (the table is most of
  it); `words.js` about 130 (about 43 entries); `app.js` about +70 and 30 changed; `index.html`
  about 25 changed; tests about +120.
- **Part B: S**, about 150 lines, nearly all of it one `ja:` line per key (about 43 today, more by
  the time it is built), +10 in `style.css` (twice), and about +60 in tests.

## Changes made at approval (orchestrator)

- Decisions 1, 2, 3, 5 and 6 approved as recommended. **Decision 4 (owner): super casual.** Plain
  casual Japanese (タメ口, no です・ます), the way friends write to each other, short and light.
  Part B writes every entry in that voice; the first draft in this plan is rewritten to match.
- **Open before Part B merges:** a native speaker must read the whole screen. The owner will name
  who. Part B is not merged until then.
- Part A is built right after `groundwork`, and turns `groundwork`'s few new words into keys.
