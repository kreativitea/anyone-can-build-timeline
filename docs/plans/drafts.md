Status: merged

# Drafts

## 1. What it does

You start writing a post, and then the tab closes, the page reloads, or the computer restarts. When
you open the timeline again and you are still logged in, your half-written post is back in the box,
and a short line says so. The draft is kept only in this browser, one for each account, and it is
removed when the post is sent or when you log out.

## 2. Decisions for the owner

**2.1 Which browser storage keeps the draft: `localStorage` or `sessionStorage`?**
Both are small stores inside the browser that a page can write text into.
`sessionStorage` belongs to one tab and is emptied when that tab is closed. `localStorage` belongs
to the whole browser (every tab of this website) and stays until it is removed.

- **A. `localStorage`.** The draft survives a reload *and* a closed tab, and a restart of the
  browser. Cost: two tabs of the same account share one draft, so the last tab you typed in wins.
- **B. `sessionStorage`.** The draft survives a reload only. Closing the tab, which is the main
  case this feature is for, loses it.

**Recommendation: A, `localStorage`.** `page-only/` chose `sessionStorage` on purpose, and that is
still right there: in `page-only/` the storage *is* the timeline, and `localStorage` would make
two windows look shared when nothing is. Here the timeline lives on the server, and the draft is
one person's private note that is not shared with anyone. So the reason for `sessionStorage` does
not apply, and its weakness (lost on close) is exactly what this feature must fix. `page-only/` is
not changed.

**2.2 What happens to the draft when the person logs out?**

- **A. Delete it.** Logging out means "I am leaving this computer". A draft is private text, and
  `localStorage` is plain text on the disk: anyone who uses this browser can read it with the
  browser's developer tools.
- **B. Keep it**, hidden, and show it again when the same account logs in. Handy on your own
  laptop, but it leaves private words behind on a shared computer (for example a university lab).
- **C. Ask** "Keep your draft on this computer?" when logging out.

**Recommendation: A, delete it.** It is the safe default, it is one line, and the box is emptied
too, so the next person never sees it. C is a dialog for a rare case.

**2.3 What happens when the login ends by itself** (the 30-day session runs out, or the server
answers 401 to a post)?

- **A. Keep the draft.** The person did not choose to leave. They log in again and the draft is
  back. The box is emptied while nobody is logged in, so it is not on the screen.
- **B. Delete it**, like a log out.

**Recommendation: A, keep it.** The most likely moment for this is pressing Post on a long draft
after the session has ended; deleting it then would lose exactly what the feature protects. It
adds no new exposure: while the session cookie was alive, anyone at this browser *was* that
person anyway.

**2.4 When is the draft saved?**

- **A. On every change to the box** (the `input` event, which fires on each key, paste or cut).
- **B. "Debounced":** wait until the person stops typing for, say, half a second, then save once.

**Recommendation: A.** A draft is at most a few hundred characters, and writing it to
`localStorage` takes far less than a millisecond. Debouncing adds a timer and a window in which
the last words are lost if the tab closes. Nothing to gain here.

**2.5 Should the page say that a draft came back?**

- **A. Yes:** the status line says "Your unsent post is back." when a draft is put in the box.
- **B. No:** the text just appears.

**Recommendation: A.** Text that appears by itself is confusing, and it is one line using the
existing `showStatus`.

## 3. Design

**Database:** no change. **Model, routes, view:** no change. `server.py` is not touched. A draft
never leaves the browser.

**Page (`with-backend/app.js`).** All new code goes in new functions, in one block under the
comment `// Drafts`, placed after `updateCount`.

- `DRAFT_KEY_START = "timeline-draft:"`, a new constant.
- `draftKey(who)` gives `"timeline-draft:" + who.account_name.toLowerCase()`, for example
  `timeline-draft:aiko`. One key per account, so two people on one computer never see each other's
  drafts. Account names are unique without regard to case on the server, and they may hold only
  letters, numbers and `_`, so the key cannot clash with another account's key.
- `loadDraft(who)` reads the draft for that account. It gives `""` if there is none, or if the
  browser blocks storage.
- `saveDraft()` keeps what is in the box now, under the key of the account logged in. If nobody is
  logged in, it does nothing. If the box is empty or only spaces, it removes the key instead of
  saving an empty draft. A draft over 280 characters is still saved: the person may be cutting it
  down.
- `forgetDraft()` removes the draft of the account logged in.
- `showDraft(who)` puts that account's draft in the box (or empties the box if there is none),
  calls `updateCount()` so the count, and its red colour if too long, is right, and, if a draft came
  back, calls `showStatus("Your unsent post is back.")`.
- `hideDraft()` empties the box and calls `updateCount()`. It does not touch storage.

Every read and write of `localStorage` is inside `try { … } catch (error) { … }`. Storage can be
blocked (a browser set to refuse site data, some private windows) or full (`QuotaExceededError`,
for example after pasting a huge text). Then drafts quietly do nothing, and posting still works.

**Where they are called (the only changes to existing code, one line each):**

| Where | Line added | Why |
|---|---|---|
| `showSignedIn(who)`, at the end | `showDraft(who);` | Covers all three ways in: the page opening (`askWhoIAm`), `logIn` and `signUp`. |
| `showSignedOut(reason)`, before `showStatus(reason)` | `hideDraft();` | The box is emptied whenever nobody is logged in, so one person's words are never in the box when the next person logs in. Today the hidden box keeps its text after a log out; this fixes that too. |
| `sendPost`, after `textBox.value = "";` in the success path | `forgetDraft();` | Clear only after the server said 201. On 400 (a broken rule), 401 (login ended) or no answer, the draft stays. |
| `logOut`, after `await fetch(...)` and before `showSignedOut("")` | `forgetDraft();` | Decision 2.2. Only after the server answered, so a failed log out keeps the draft. It must come before `showSignedOut`, which sets `account` to `null`. |
| Listeners at the bottom | `textBox.addEventListener("input", saveDraft);` | A second listener next to `updateCount`, rather than changing `updateCount`. |

**Edge cases, and what happens.**

- Two tabs, same account: both write the same key. The draft is what was typed last, in either tab.
- Some browsers (Firefox) fill a textarea again by themselves after a reload. `showSignedIn` and
  `showSignedOut` always set the box, so that old text is replaced before the box is shown.
- The person types more while a post is being sent: the box is emptied on success, as today, and
  the draft is forgotten. Not new, and rare.

**`index.html`, `style.css`, `server.py`:** no change.

## 4. Files and functions touched

| File | Function or section | Add or change |
|---|---|---|
| `with-backend/app.js` | `DRAFT_KEY_START` constant | add |
| `with-backend/app.js` | `draftKey`, `loadDraft`, `saveDraft`, `forgetDraft`, `showDraft`, `hideDraft` (new `// Drafts` block after `updateCount`) | add |
| `with-backend/app.js` | `showSignedIn` (one line at the end) | change |
| `with-backend/app.js` | `showSignedOut` (one line) | change |
| `with-backend/app.js` | `sendPost` (one line in the success path) | change |
| `with-backend/app.js` | `logOut` (one line) | change |
| `with-backend/app.js` | event listeners at the bottom (one new line) | add |
| `with-backend/test_server.py` | new class `PageDraftTest`, at the end of the file | add |
| `AGENTS.md` | the `with-backend/app.js` row of the file table; a short "Drafts" note | change (one row) / add |
| `DESIGN.md` | new subsection "Drafts"; new rows at the end of the section 7 table | add |
| `README.md` | one line under "Things to try" | add |

## 5. Depends on, and collides with

- **Depends on `accounts`.** It needs `account`, `showSignedIn`, `showSignedOut`, `logOut` and
  `GET /sessions` from that branch.
- **`edit-delete`:** if editing a post reuses the main post box, the edit text would be saved as a
  draft and overwrite the real one. That plan should edit in its own box, or turn `saveDraft` off
  while editing. Either branch can go first; the second one checks this.
- **`replies`:** the same question if a reply is typed in the main box. A reply typed in its own
  box simply has no draft (see section 8).
- **`rate-limit`, `pictures`, `long-posts`:** all change `sendPost` near the lines this plan
  touches. The overlap is one line, so a rebase is easy. `rate-limit`'s new refusal (429) must not
  clear the draft; it will not, because `forgetDraft` is only in the success path. `long-posts`
  needs nothing from this plan: a draft of any length is saved.
- **`dark-mode`:** also uses `localStorage`. Use a different key (`timeline-theme`, not anything
  starting with `timeline-draft:`). The test in section 6 checks "every function that touches
  `localStorage` has a `try`", which holds for both branches and does not name drafts only, so
  the two do not break each other.
- **`japanese`:** adds the sentence "Your unsent post is back." to the strings to translate.
- **`timeline-flow`, `search`, `block`, `report`, `bookmarks`, `who-liked`, `links-and-tags`,
  `timestamps`, `place`, `reply-email`:** no shared lines.

## 6. Tests

The tests never run JavaScript (that would need a browser or Node). So they cannot prove a draft
comes back after a reload. What they *can* do is read `app.js` as text, the way
`PageAndServerAgreeTest` does, and check that the code is wired the agreed way. The rest is a
check by hand.

- **`ModelTests`, `RealServerTest`, `JourneyTest`:** none. Nothing on the server or in the database
  changes, so there is nothing new for them to check.
- **New class `PageDraftTest`** (reads `with-backend/app.js`; starts no server). A small helper,
  `functions_in(code)`, cuts the file into its top-level functions by the pattern
  `^(async )?function name(...) { ... ^}`, giving a name → body map.
  - `test_a_draft_is_kept_per_account`: `"timeline-draft:"` is in the file, and the body of
    `draftKey` uses `account_name`.
  - `test_every_use_of_local_storage_is_inside_a_try`: every function whose body says
    `localStorage` also has `try {` and `catch`, and no `localStorage` appears outside a function.
  - `test_the_page_uses_no_session_storage`: `sessionStorage` is not in this `app.js` (decision 2.1).
  - `test_the_draft_is_forgotten_only_after_a_saved_post_and_on_log_out`: the functions that call
    `forgetDraft()` are exactly `sendPost` and `logOut`; in `sendPost`, `forgetDraft()` comes after
    `if (!response.ok)`.
  - `test_the_box_follows_who_is_logged_in`: `showDraft(` is in `showSignedIn` and `hideDraft()` is
    in `showSignedOut`.
  - `test_saving_listens_to_the_box`: `textBox.addEventListener("input", saveDraft)` is in the file.
  - `test_a_draft_is_never_sent`: no `JSON.stringify(...)` argument mentions `draft`. (The existing
    test on the routes the page asks for already stops a new `/drafts` request.)
- **By hand, in the pull request** (the checklist to tick):
  1. Log in, type, reload: the text is back, with the count and "Your unsent post is back."
  2. Type, close the tab, open a new one at <http://localhost:8009>: the text is back.
  3. Type, press Post: reload shows an empty box.
  4. Type a post over 280 characters, press Post (refused), reload: the text is back, count in red.
  5. Type, log out: the box is empty; log in again: still empty. In developer tools, under
     Application → Local Storage, there is no `timeline-draft:` key.
  6. `aiko` types, then her session is ended by hand
     (`sqlite3 with-backend/timeline.db 'delete from sessions'`), then
     `ben` logs in on the same browser: `ben` sees an empty box. `aiko` logs in again: her draft is
     back.
  7. Block site data for `localhost` in the browser settings: the page still loads and posting
     works; there are no errors in the console.

## 7. Docs to update

- `AGENTS.md`: in the file table, the `with-backend/app.js` row adds "and keeps a half-written post
  in this browser's `localStorage`, one per account, removed after posting or logging out". A short
  note under "How to test it" that `PageDraftTest` reads `app.js` as text.
- `DESIGN.md`: a new subsection "Drafts" with decision 2.1 (why `localStorage` here and
  `sessionStorage` in `page-only/`) and 2.2. New rows at the end of the adversarial review table,
  for example: "A draft on a shared computer is private text left behind" → accept → deleted on log
  out; "Debounce the saving" → reject → nothing to gain at this size; "Keep drafts on the server so
  they follow you to another device" → reject → a new table and route for a rare need.
- `README.md`: under "Things to try": "Type half a post, close the tab, and open the page again."

## 8. Not in this plan

- Drafts for `page-only/` (no accounts there, and it is a demo).
- Keeping drafts on the server, so they follow you to another computer.
- Keeping two tabs in step while typing (the `storage` event).
- Drafts for replies or edits, and more than one draft per account.
- Deleting old drafts after some days. A draft stays until it is posted or the person logs out.
- Hiding the draft from someone who uses the same browser while the owner is still logged in.
  That person can already post as the owner; a draft adds nothing to that.

## 9. Size

**S.** About 45 lines in `app.js` (six small functions and five one-line hooks), about 60 lines
of tests, about 20 lines of docs. Roughly 125 lines in all.

## Changes made at approval (orchestrator)

- All five decisions approved as recommended.
- A draft remembers the post it replies to (`parent_id`), as well as its text, once `replies`
  exists. Whichever of the two is built second adds this.
