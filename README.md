# Timeline

A small app where people post short messages. Everyone's posts appear on one timeline, newest
first, and each post has a heart: press it to like, press it again to take the like back. It comes
in two versions:

- **`page-only/`**: a demo. Everything runs in the browser. There is no server and no login. Each
  window keeps its own posts, so nothing is shared.
- **`with-backend/`**: people sign up and log in. The page sends each post and each like to a small
  Python server, which saves them in a database. Every window asks the server for new posts and new
  like counts once a second, so every window sees every post, and every heart. Anyone can read the
  timeline; only a signed-in person can post or like, and nobody can post as someone else.

The difference between the two is the reason a backend exists.

You need a web browser. For the backend version you also need `python3`, version 3.9 or newer.
A Mac already has it. There is nothing to install.

## Get your own copy

On GitHub, press **Fork** at the top of this page. That makes a copy under your own account. Then
clone your copy and go into its folder (put your GitHub name where it says `YOUR-NAME`):

```
git clone https://github.com/YOUR-NAME/anyone-can-build-timeline.git
cd anyone-can-build-timeline
make test
```

Every check should pass. If one does not, ask your agent why before you change anything.

## Run the page-only version

Open `page-only/index.html` in a browser. That is all.

## Run the backend version

```
make run
```

Then open <http://localhost:8009>. Each new post prints one line in the terminal: the time, who
wrote it, and what it says, in quotes.

## Sign up and log in

On the page, fill in the **Sign up** form:

- **Account name**: the `@` name, such as `aiko`. Letters, numbers and `_` only, up to 40. It must
  be new: `Aiko` counts as taken if `aiko` exists.
- **Display name**: the name shown on your posts, such as *Aiko Tanaka*. Leave it empty to use your
  account name.
- **Password**: 8 characters or more. Spaces count.

You are logged in at once, and the page says *Signed in as Aiko Tanaka @aiko · Log out*. The login
lasts 30 days in that browser. Next time, use the **Log in** form. A private window is a different
browser, so it can log in as someone else.

If your timeline has posts from before accounts, their names are still there. The first person to
sign up with one of those names gets it, and its old posts. A name with a space in it can never be
taken this way, so its posts stay with no owner. To stop the server, press **Ctrl+C** in the terminal.

Without `make`, the same thing is: `cd with-backend`, then `python3 server.py`.

In the Claude Code desktop app, `.claude/launch.json` starts the same server and opens it for you.

## See the difference

Open the app in two windows side by side, one of them a **private window** (Chrome: Incognito,
Safari: Private Window). Sign up as a different person in each, and post from each. With the backend, a post from one window appears in the
other within a second, and a heart pressed in one window changes the count in the other within a
second. Press the same heart again and the count goes back down, in both windows. Page-only, none of
it happens: each window keeps only its own posts, and has no hearts at all. Open a new
window rather than duplicating a tab, because a duplicated tab copies the first tab's
`sessionStorage`.

Stop the server with **Ctrl+C**, and both windows say *Cannot reach the server*. Start it again with
`make run`, and they recover by themselves.

## Open the store

The backend keeps everything in one file, `with-backend/timeline.db`, in four tables: `users`,
with each person once, `posts`, where each post points at its author by number, `likes`, with
one line for each person who liked each post, and `sessions`, with one line for each logged-in
window. To see what is inside:

```
sqlite3 with-backend/timeline.db 'select * from users; select * from posts; select * from likes; select * from sessions'
```

A user line is `id|name|display_name|password_salt|password_hash|password_rounds`, for example
`1|aiko|Aiko Tanaka|9f3a…|5c1e…|600000`. Look: the password is not there. Only a hash of it is, a
long code made from the password that cannot be turned back into it. A user from before accounts
has nothing after the display name, because nobody has claimed it yet. A session line is
`token_hash|user_id|expires_at`: again only a hash, and logging out deletes the line. A post line is
`id|author_id|text|posted_at`: the `author_id` is the `id` of a user. A like line is just
`post_id|user_id`. Notice what is **not** there: nowhere does
the database keep "post 3 has 5 likes". The number on screen is counted from these lines every time
it is asked for, so the count and the likes can never disagree. Taking a like back deletes its line,
and the count reads one lower because there is one line fewer to count.

To start again with an empty timeline, stop the server and run `make reset`.

## Check it

```
make test
```

This runs the checks in `with-backend/test_server.py`. They test the rules (an empty post and a
post over 280 characters are refused), accounts (passwords kept only as hashes, one message for a
wrong name or password, logging out, old names claimed once), saving a post, asking only for newer
posts, likes (counting them, refusing a second one from the same person, and taking one back), full
trips through the real server, and one whole journey through all three levels at once: two people
signing up, posting, liking and unliking, with the database file opened and read after every step.

## Things to try

1. **Explain it.** Ask your AI agent to explain the architecture of this repository. Write down, in
   your own words, which file or part is the **controller**, which is the **model**, which is the
   **view**, and where the data lives.
2. **Add one feature, with a test.** Pick one from this list:
   - follow someone, and show a "following" timeline
   - reply to a post
   - delete your own post
   - edit your own post
   - show *who* liked a post, not only how many
3. **Say what changed and why.** Which parts did your feature change: the page, the controller, the
   model, the view, the database? Why those parts, and not the others?

Each feature changes a different set of parts.

The heart under each post was built this way, and it is worth reading as an example: it added a
third table, `likes`, one new rule in the model, three new requests, and a heart in the page. See
section 5 of `DESIGN.md` for the two parts that matter most — the three places that stop you liking
the same post twice, and why only the last of them is a guarantee; and why taking a like back
deletes a row instead of marking one.

Keep the three parts of `server.py` separate. A new rule goes in the model. `make test` must pass
when you finish.
