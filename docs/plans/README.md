# Feature plans

One file per feature: `docs/plans/<slug>.md`. A plan is written first, the owner approves it in
the orchestrator thread, and only then is it built, on its own branch, in its own worktree
(`make worktree BRANCH=<slug>`). The orchestrator rebases finished branches and merges them to
`main`.

Each plan has a status line at the top: `Status: draft`, `approved`, `building` or `merged`.

## What every plan assumes

- **Accounts have landed** (see `accounts.md`). A person is a signed-in user. The server learns who
  is asking from the `session` cookie, through `user_for_session` in the model, never from a name
  in the JSON. Posting and liking need sign-in. Reading does not.
- The rules in `AGENTS.md` hold: `server.py` keeps **controller**, **model** and **view** apart; a
  new rule goes in the model and is checked again in the page; the database enforces what it can;
  Python 3.9 and the standard library only; no packages and no build step.
- `with-backend/` is the real app. `page-only/` is a demo and is not changed, except that
  `page-only/style.css` stays a copy of `with-backend/style.css`.
- Write for a reader who is new to programming and may read English as a second language: short,
  plain sentences, and a technical word explained the first time it is used.

## What every plan contains

1. **What it does**, for the person using the app, in two to four sentences.
2. **Decisions for the owner.** Each one a question, with the options and a recommendation.
3. **Design.** Database (tables, columns, constraints), model functions, routes (method, path,
   JSON in and out, status codes), view functions, and page changes.
4. **Files and functions touched.** A table: file · function or section · *add* or *change*.
   Be exact. The orchestrator uses this table to decide what can be built at the same time.
5. **Depends on, and collides with,** other plans, by slug, and why.
6. **Tests**, by kind: `ModelTests`, `RealServerTest`, `JourneyTest`, `PageAndServerAgreeTest`.
7. **Docs to update.**
8. **Not in this plan.**
9. **Size:** S, M or L, and roughly how many lines.

## How to keep collisions small

Several branches are built at the same time, and they all touch the same few files. So:

- **Add rather than change.** Put new code in new functions. When a shared function must change
  (`showPost`, `checkForNewPosts`, `POSTS_WITH_AUTHORS`, `post_to_json`, the `do_GET`/`do_POST`/
  `do_DELETE` routing), keep the change as small as possible and list it in section 4.
- **Database changes are an upgrade function**, `upgrade_to_<slug>(connection)`, written like
  `upgrade_to_accounts`. Do not choose a `user_version` number: the orchestrator numbers the
  upgrades in the order the branches are merged.
- **Tests:** add new test methods, or a new test class, at the end of the right class. Don't
  reorder or rewrite other tests.
- **CSS:** new rules go at the end of `style.css`, under a comment with the slug.
- **Docs:** add a new section. Don't rewrite other sections.

## The plans

| Slug | Feature |
|---|---|
| `accounts` | Sign up, log in, log out, salted password hashes, sessions |
| `groundwork` | Shared pieces, no visible change: post slots, one ⋯ menu, one click handler, views, one visibility filter, `insert_post`, safe table rebuild, post ids never reused |
| `timestamps` | Save the full date and time in UTC; show "5 minutes ago" |
| `drafts` | Keep a half-written post if the tab closes |
| `edit-delete` | Edit or delete your own post, keep each old version, and tell open windows |
| `rate-limit` | Stop someone posting too fast |
| `replies` | A post that answers another post |
| `search` | Search posts for a word or `#tag` |
| `links-and-tags` | Make links and `#tags` in a post clickable |
| `timeline-flow` | A "3 new posts" button, and older posts loaded on scroll |
| `pictures` | Attach a picture to a post, checked by the server |
| `block` | Block someone, so you never see their posts |
| `report` | Report a post; hide it after enough reports |
| `reply-email` | An email when someone replies to you |
| `bookmarks` | Save a post only you can see |
| `dark-mode` | Choose light or dark by hand, remembered in this browser |
| `who-liked` | Show who liked a post |
| `long-posts` | Posts up to 500 characters |
| `place` | Where a post was written |
| `japanese` | The app in Japanese as well as English |
| `classic-style` | The look of classic (2009–2014) Twitter, in our own colours: one card, letter circles, names in blue |

Already done, so no plan: the live character count, refusing empty or too-long posts, and unique
account names (part of `accounts`).

## The words contract

Every plan merged after `japanese` Part A follows `japanese.md` section 3.4: a new rule raises a
code, never a sentence; the code and its English go in `PROBLEMS` and in `words.js`; every word
the page shows is a key in `words.js`; nobody but Part B writes Japanese. `make test` catches a
missing or different key.
