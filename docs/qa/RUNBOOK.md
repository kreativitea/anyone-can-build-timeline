# QA runbook: a manual pass on the server

This is a check you do by hand, step by step, before a release or after a few days away.
`make test` checks the code from the inside. This runbook checks the **running server** from the
outside, the way the page uses it: real HTTP requests, as several different people at once.

Most of the steps are about **people acting on each other**: liking, replying, blocking,
reporting, bookmarking, editing and deleting, and email. Each one has its own case below.

Every run is kept in `docs/qa/runs/`:

- `docs/qa/runs/YYYY-MM-DD.md`: the run entry. What was checked, what passed, what was found.
- `docs/qa/runs/YYYY-MM-DD/`: the evidence. One screenshot or more for each step, the full
  `transcript.md` of every request and answer, and `server.log` (what the server printed).

## Words used here

- **curl**: a command that sends one web request and shows the answer. We use it instead of a
  browser so that every request is exact and written down.
- **Cookie jar**: a file where curl keeps a person's cookies, like their own browser. Each person
  (`aiko`, `ben`, ...) has their own jar, so they are logged in separately.
- **Session cookie**: the small piece of text the server gives you when you log in. It is the only
  way the server knows who you are.
- **Status code**: the number at the start of an answer. `200`/`201` mean yes; `400` means a rule
  was broken; `401` means "log in first"; `403` means "not yours"; `404` means "nothing here";
  `413` means "too big"; `429` means "too fast, wait".
- **Card**: a screenshot of the requests and answers of one step (dark background).
- **Page screenshot**: the real page, drawn by Chrome, as one person sees it.

## What you need

- `python3` and `sqlite3` (already needed by the project).
- `curl` (comes with macOS).
- For screenshots only: Google Chrome and Node 22 or newer. The helper uses no packages. Another
  Chrome-like browser works too: set `QA_CHROME` to its program path.

## Setup

1. Make a worktree for the run, so the run has its own empty database:

   ```bash
   make worktree BRANCH=qa-YYYY-MM-DD
   ```

2. Go into it, and run the automated tests first. They must all pass:

   ```bash
   make test
   ```

3. Start a **fresh** server on its own port, printing into the run's folder. Leave it running in
   its own terminal tab:

   ```bash
   mkdir -p docs/qa/runs/$(date +%Y-%m-%d) && rm -f with-backend/timeline.db && cd with-backend && python3 -u server.py --port 8011 > ../docs/qa/runs/$(date +%Y-%m-%d)/server.log 2>&1
   ```

4. In a second terminal tab, in the worktree, load the helpers:

   ```bash
   source docs/qa/tools/qa.sh
   ```

   Then set two shortcuts used below:

   ```bash
   DB=with-backend/timeline.db
   ```

   ```bash
   PNG=$(python3 -c 'import base64,zlib,struct
   def c(t,d): return struct.pack(">I",len(d))+t+d+struct.pack(">I",zlib.crc32(t+d)&0xffffffff)
   raw=b"\x89PNG\r\n\x1a\n"+c(b"IHDR",struct.pack(">IIBBBBB",8,8,8,2,0,0,0))+c(b"IDAT",zlib.compress(b"".join(b"\x00"+b"\x2e\xa0\x5a"*8 for _ in range(8))))+c(b"IEND",b"")
   print(base64.b64encode(raw).decode())')
   ```

   (`PNG` is a tiny green 8×8 picture, as base64 text.)

## The helpers (`docs/qa/tools/qa.sh`)

| Command | What it does |
|---|---|
| `step G2 "title"` | Starts a check. Everything after it goes under this name in `transcript.md`. |
| `as aiko POST /blocks '{"account_name":"dan"}'` | One request, as Aiko (her cookie jar). `anon` is nobody. Prints the request and the answer. |
| `ids ben '/posts?before=0'` | Lists the posts one person sees, as `id:author`. |
| `note "text"` | Adds a line to the transcript (a count from the database, an explanation). |
| `card` | Screenshot of every request and answer in this step: `STEP-requests.png`. |
| `page aiko / timeline` | Screenshot of the real page as Aiko: `STEP-timeline.jpg`. Add a width for a phone: `page ben / phone 390`. |
| `log_card emails EMAIL 30` | Screenshot of the last 30 lines the server printed (emails and post lines). |
| `done_step` | Closes the last step in the transcript. Use it at the very end. |

**Take a `card` at the end of every step.** Take a `page` screenshot wherever the step says so.
Look at each screenshot: it is the evidence that the step really passed.

> Tips. The helpers work in the old `bash` that comes with macOS. If you open a new terminal,
> `source` the helpers again: the run's folder and the cookie jars stay.
> Posts are limited to 5 a minute per person, so the cases spread posts across people.
> If you see `429` where you did not expect it, wait a minute.

## The people

| Person | Account | Password (test only) |
|---|---|---|
| Aiko Tanaka | `aiko` | `correct-horse-aiko` |
| Ben Ito | `ben` | `correct-horse-ben` |
| Chika Mori | `chika` | `correct-horse-chika` |
| Dan Sato | `dan` | `correct-horse-dan` |
| Eve New | `eve` (made in I1, never posts before I1) | `correct-horse-eve` |

Post ids below are the ones a fresh database gives when you follow the steps in order. If yours
differ, use `ids anon '/posts?before=0'` to find them.

---

## A. The page

### A1 The page loads signed out; unknown paths are 404

```bash
step A1 "The page loads signed out; unknown paths are 404"
as anon GET /sessions
as anon GET /nope
as anon GET /pictures/../server.py
card
page anon / signed-out
```

Expect: `401 login_needed`; `404 nothing_here` twice (the picture path never reaches a file).
The screenshot shows the Log in and Sign up forms and an empty timeline.

## B. Accounts and sessions

### B1 Four people sign up; each gets a session

```bash
step B1 "Four people sign up; each gets a session"
as aiko POST /accounts '{"account_name":"aiko","display_name":"Aiko Tanaka","password":"correct-horse-aiko"}'
as ben POST /accounts '{"account_name":"ben","display_name":"Ben Ito","password":"correct-horse-ben"}'
as chika POST /accounts '{"account_name":"chika","display_name":"Chika Mori","password":"correct-horse-chika"}'
as dan POST /accounts '{"account_name":"dan","display_name":"Dan Sato","password":"correct-horse-dan"}'
as aiko GET /sessions
note "$(sqlite3 $DB "select group_concat(id||':'||name||' hash='||length(password_hash), '  ') from users")"
note "rows holding the password text: $(sqlite3 $DB "select count(*) from users where password_hash like '%horse%'")"
card
```

Expect: four `201`; `GET /sessions` gives Aiko with `post_count 0, like_count 0`; every hash is 64
characters; `0` rows hold the password text.

### B2 Sign-up rules

```bash
step B2 "Sign-up rules: names unique in any case, password length, characters, empty name"
as x POST /accounts '{"account_name":"AIKO","display_name":"Dup","password":"longenough1"}'
as x POST /accounts '{"account_name":"eve","display_name":"Eve","password":"short"}'
as x POST /accounts '{"account_name":"bad name!","display_name":"Eve","password":"longenough1"}'
as x POST /accounts '{"account_name":"","display_name":"Eve","password":"longenough1"}'
as x POST /accounts '{"account_name":"eve","display_name":"Eve‮","password":"longenough1"}'
note "users still: $(sqlite3 $DB 'select count(*) from users')"
card
```

Expect: `name_taken`, `password_too_short`, `name_characters`, `name_empty`,
`display_name_hidden`, all `400`; still 4 users.

### B3 Log in

```bash
step B3 "Log in: wrong password and unknown name give the same answer; name is any case"
as x POST /sessions '{"account_name":"aiko","password":"wrong-password"}'
as x POST /sessions '{"account_name":"nobody","password":"wrong-password"}'
as aiko2 POST /sessions '{"account_name":"AIKO","password":"correct-horse-aiko"}'
as aiko2 GET /sessions
card
```

Expect: the same `401 login_wrong` twice (an attacker cannot tell which names exist); `AIKO`
logs in as `aiko` (`aiko2` is Aiko's second window).

### B4 Log out ends only that window's session

```bash
step B4 "Log out ends only that window's session"
as aiko2 DELETE /sessions
as aiko2 GET /sessions
as aiko GET /sessions
note "cookie: $(curl -s -i -X POST -H 'Content-Type: application/json' --data '{"account_name":"ben","password":"correct-horse-ben"}' $QA_BASE/sessions | grep -i set-cookie | sed -E 's/session=[^;]+/session=<token>/' | tr -d '\r')"
card
page aiko / aiko-signed-in
```

Expect: the second window is logged out (`401`), the first is still Aiko (`200`). The cookie has
`HttpOnly` and `SameSite=Strict`. The screenshot shows Aiko's profile card and the post box.

## C. Request guards

### C1 Login needed, JSON only, JSON object only, size limit

```bash
step C1 "Request guards: login needed, JSON only, JSON object only, size limit"
as anon POST /posts '{"text":"hi"}'
note "text/plain with aiko's cookie: $(curl -s -w ' %{http_code}' -X POST -H 'Content-Type: text/plain' -b $QA_JARS/aiko --data '{"text":"csrf"}' $QA_BASE/posts)"
as aiko POST /posts '[1]'
as aiko POST /posts 'not json'
note "Content-Length 5000000: $(curl -s -w ' %{http_code}' -X POST -H 'Content-Type: application/json' -H 'Content-Length: 5000000' -b $QA_JARS/aiko $QA_BASE/posts --data x --max-time 3)"
as dan PATCH /accounts '{}'
note "posts saved: $(sqlite3 $DB 'select count(*) from posts')"
card
```

Expect: `401`; `400 not_json` (a form on another website cannot post as Aiko); `400
not_json_object`; `400 not_json`; `413 request_too_big`; `404`; 0 posts saved.

## D. Posts

### D1 Each person posts; the author comes from the cookie

```bash
step D1 "Each person posts; the author comes from the cookie, never the JSON"
as aiko POST /posts '{"text":"Good morning from the library #study","place":"Osaka"}'
as ben POST /posts '{"text":"Lunch at the cafeteria #food"}'
as chika POST /posts '{"text":"Hello @aiko see https://example.com/page."}'
as dan POST /posts '{"text":"Dan here, first post #study"}'
as aiko POST /posts '{"text":"pretending to be ben","author":"ben","user_id":2}'
note "post 5 author in the database: $(sqlite3 $DB 'select u.name from posts p join users u on u.id=p.author_id where p.id=5')"
card
```

Expect: posts 1–5 are `201`; post 5's author is `aiko`, not `ben`.

### D2 Post rules

```bash
step D2 "Post rules: empty, too long, place too long, place with hidden characters"
as aiko POST /posts '{"text":"   "}'
as aiko POST /posts "{\"text\":\"$(python3 -c 'print("a"*561)')\"}"
as aiko POST /posts "{\"text\":\"ok\",\"place\":\"$(python3 -c 'print("p"*41)')\"}"
as aiko POST /posts '{"text":"bidi","place":"Osa‮ka"}'
as aiko POST /posts '{"text":"newline","place":"Osa\nka"}'
note "posts saved: $(sqlite3 $DB 'select count(*) from posts') (still 5)"
card
```

Expect: `text_empty`, `text_too_long` (560), `place_too_long` (40), `place_hidden` twice. Still 5.

### D3 Pictures

```bash
step D3 "Pictures: a PNG is kept; SVG and a missing description are refused; safe headers"
as dan POST /posts "{\"text\":\"My desk today #study\",\"picture\":\"$PNG\",\"picture_alt\":\"A small green square\"}"
as dan POST /posts '{"text":"svg","picture":"'$(printf '<svg xmlns="http://www.w3.org/2000/svg"/>' | base64)'","picture_alt":"x"}'
as dan POST /posts "{\"text\":\"no description\",\"picture\":\"$PNG\"}"
note "GET /pictures/6 headers: $(curl -s -D - -o /dev/null $QA_BASE/pictures/6 | grep -i 'content-type\|nosniff\|security' | tr -d '\r' | tr '\n' ' ')"
card
```

Expect: post 6 with `"picture": {"url": "/pictures/6", ...}`; `picture_wrong_kind`;
`picture_alt_empty`; headers `image/png`, `nosniff`, `default-src 'none'; sandbox`.

### D4 Pages of posts

```bash
step D4 "Pages of posts: newest first, before/after rules"
ids anon '/posts?before=0'
ids anon '/posts?after=0'
ids anon '/posts?before=3'
as anon GET '/posts?before=0&after=0'
as anon GET '/posts?before=abc'
as anon GET '/posts?after=x'
card
page anon / timeline-signed-out
```

Expect: `before=0` newest first (6..1); `after=0` oldest first (1..6); `before=3` is `2, 1`;
`before_and_after`, `id_bound_not_number`, `after_not_number`.

## E. Likes (between people)

### E1 One like each, take it back

```bash
step E1 "Likes between people: one each, take back, counts from rows"
as ben POST /likes '{"post_id":1}'
as chika POST /likes '{"post_id":1}'
as dan POST /likes '{"post_id":1}'
as ben POST /likes '{"post_id":1}'
as aiko POST /likes '{"post_id":1}'
as ben POST /likes '{"post_id":999}'
as ben POST /likes '{"post_id":"x"}'
as anon POST /likes '{"post_id":1}'
as ben DELETE /likes '{"post_id":1}'
as ben DELETE /likes '{"post_id":1}'
as anon GET /likes
as chika GET '/likes?from=1'
note "likes rows for post 1: $(sqlite3 $DB 'select group_concat(u.name) from likes l join users u on u.id=l.user_id where post_id=1')"
card
```

Expect: counts go 1, 2, 3; Ben's second like is `like_already`; Aiko may like her own post (4);
`post_missing`; `like_post_id_missing`; `401`; Ben takes his back (3), and again is
`like_not_there`. `mine` is `[]` for nobody and `[1]` for Chika. Rows: `aiko,chika,dan`.

### E2 Who liked, and likes received

```bash
step E2 "Who liked: names A to Z, the summary line, and likes received on the profile"
as anon GET '/likers?post_id=1'
as chika GET '/likesummary?post_ids=1,2'
as aiko GET /sessions
card
```

Expect: likers A to Z; Chika's summary has `"you": true`; Aiko's `like_count` is **2** (Chika and
Dan; her own like does not count).

## F. Replies (between people)

### F1 One level only

```bash
step F1 "Replies between people: one level only; own post allowed; counts"
as ben POST /posts '{"text":"Nice, see you there @aiko","parent_id":1}'
as aiko POST /posts '{"text":"reply to a reply","parent_id":7}'
as aiko POST /posts '{"text":"reply to nothing","parent_id":999}'
as aiko POST /posts '{"text":"Thanks! See you at 3","parent_id":1}'
ids anon '/posts?before=0'
card
page chika / timeline-as-chika
```

Expect: reply 7 (`parent_author: aiko`); `reply_to_reply`; `post_missing`; reply 8. Post 1 has
`reply_count 2`, `newest_reply_id 8`. The screenshot shows both replies under post 1, and "You,
Aiko Tanaka, and 1 other liked this post".

## G. Blocking (between people)

Aiko blocks Dan. Then: what Aiko sees, what Dan can still do, what everyone else sees.

### G1 Guards

```bash
step G1 "Block: guards (login, self, unknown name, any case, twice); never adds a user"
as aiko POST /bookmarks '{"post_id":6}'
as aiko POST /bookmarks '{"post_id":2}'
as anon POST /blocks '{"account_name":"dan"}'
as aiko POST /blocks '{"account_name":"aiko"}'
as aiko POST /blocks '{"account_name":"ghost"}'
as aiko POST /blocks '{"account_name":"DAN"}'
as aiko POST /blocks '{"account_name":"dan"}'
as aiko GET /blocks
as dan GET /blocks
as anon GET /blocks
note "blocks rows: $(sqlite3 $DB 'select blocker_id||"->"||blocked_id from blocks')   users: $(sqlite3 $DB 'select count(*) from users')"
card
```

Expect: bookmarks `201`; `401`; `block_self`; `account_missing` (and no new user); `DAN` blocks
`dan`; `block_already`; Aiko's list has Dan, Dan's is empty (Dan is never told); `401`.

### G2 Dan's posts leave every list Aiko reads

```bash
step G2 "Aiko blocked Dan: Dan's posts leave every list Aiko reads"
ids aiko '/posts?before=0'
ids aiko '/posts?after=0'
ids aiko '/search?q=%23study'
ids aiko '/bookmarks'
as aiko GET /pictures/6
as aiko GET /trends
ids ben '/posts?before=0'
ids ben '/search?q=%23study'
as ben GET /trends
card
page aiko / timeline-as-aiko-blocker
page aiko '/?q=%23study' search-as-aiko-blocker
```

Expect: no `dan` in Aiko's timeline (both directions), search, bookmarks (post 6 gone, 2 stays);
picture 6 is `404` for Aiko; Aiko's `#study` trend counts 1, Ben's counts 3. Ben still sees
everything.

### G3 Dan still reads Aiko, but cannot like or reply

```bash
step G3 "Dan (blocked) still reads Aiko's posts, but cannot like or reply to them"
ids dan '/posts?before=0'
as dan POST /likes '{"post_id":5}'
as dan POST /posts '{"text":"reply to the blocker","parent_id":5}'
as dan POST /bookmarks '{"post_id":5}'
as dan POST /posts '{"text":"Dan still posts"}'
card
page dan / timeline-as-dan-blocked
```

Expect: Dan sees every post; `like_blocked`; `reply_blocked`; a private bookmark is allowed;
Dan can still post (post 9).

### G4 Likes stay counted

```bash
step G4 "Likes: Dan's old like still counts; only Aiko stops seeing his name"
as aiko GET '/likers?post_id=1'
as ben GET '/likers?post_id=1'
as aiko GET '/likesummary?post_ids=1'
as dan DELETE /likes '{"post_id":1}'
as dan POST /likes '{"post_id":1}'
card
```

Expect: count 3 for both; Dan's name is missing only for Aiko. Dan may take his like back (2),
but `like_blocked` when he gives it again.

### G5 Reply counts

```bash
step G5 "Reply counts leave out replies by people the viewer blocked"
as dan POST /posts '{"text":"Dan replies to Chika","parent_id":3}'
```

Then, for Aiko and Ben, read post 3's `reply_count`:

```bash
for who in aiko ben; do note "$who sees post 3: $(curl -s -b $QA_JARS/$who $QA_BASE'/posts?before=0' | python3 -c "import json,sys; p=[p for p in json.load(sys.stdin) if p['id']==3][0]; print('reply_count', p['reply_count'])")"; done
card
```

Expect: Aiko `0`, Ben `1`.

### G6 Changes feed and old versions

```bash
step G6 "Changes feed and old versions: an edit by Dan reaches Ben, not Aiko"
L=$(curl -s $QA_BASE/changes | python3 -c 'import json,sys; print(json.load(sys.stdin)["latest"])')
as dan PATCH /posts '{"post_id":9,"text":"Dan still posts (edited)"}'
as aiko GET "/changes?after=$L"
as ben GET "/changes?after=$L"
as aiko GET '/versions?post_id=9'
as ben GET '/versions?post_id=9'
card
```

Expect: Aiko's change has `"post": null` (take it away); Ben's has the edited post. Versions:
`[]` for Aiko, the old words for Ben.

### G7 What the blocker can still do

```bash
step G7 "The blocker can still like and reply to the blocked person's posts (by id)"
as aiko POST /likes '{"post_id":4}'
as aiko POST /posts '{"text":"reply to someone I blocked","parent_id":4}'
card
```

Today: both `201`. The rules only limit the blocked person. Write down if this changes.

### G8 Unblock

```bash
step G8 "Unblock: everything comes back; Dan can like again"
as anon DELETE /blocks '{"account_name":"dan"}'
as aiko DELETE /blocks '{"account_name":"dan"}'
as aiko DELETE /blocks '{"account_name":"dan"}'
as aiko GET /blocks
ids aiko '/posts?before=0'
ids aiko '/bookmarks'
as aiko GET /pictures/6
as dan POST /likes '{"post_id":1}'
card
page aiko / timeline-as-aiko-after-unblock
```

Expect: `401`; `200`; `block_not_there`; empty list; Dan's posts are back, bookmark 6 is back,
picture 6 is `200`; Dan's like is `201`.

### G9 Both block each other

```bash
step G9 "Both block each other: neither sees, likes or replies to the other; one unblock leaves the other block"
as ben POST /blocks '{"account_name":"chika"}'
as chika POST /blocks '{"account_name":"ben"}'
ids ben '/posts?before=0'
ids chika '/posts?before=0'
as ben POST /likes '{"post_id":3}'
as chika POST /likes '{"post_id":2}'
as chika POST /posts '{"text":"reply to ben","parent_id":2}'
as ben DELETE /blocks '{"account_name":"chika"}'
ids ben '/posts?before=0'
as ben POST /likes '{"post_id":3}'
as chika DELETE /blocks '{"account_name":"ben"}'
as ben POST /likes '{"post_id":3}'
card
```

Expect: neither sees the other's posts; `like_blocked` both ways; `reply_blocked`. After Ben
unblocks, Ben sees Chika's posts again but still gets `like_blocked` (Chika still blocks him).
After Chika unblocks, Ben's like is `201`.

## H. Edit and delete (between people)

### H1 Only the author

```bash
step H1 "Only the author may edit or delete a post; an edit keeps the old words"
as ben PATCH /posts '{"post_id":1,"text":"hacked by ben"}'
as ben DELETE /posts '{"post_id":1}'
as anon PATCH /posts '{"post_id":1,"text":"hacked"}'
as anon DELETE /posts '{"post_id":1}'
as aiko PATCH /posts '{"post_id":1,"text":""}'
as aiko PATCH /posts '{"post_id":999,"text":"x"}'
as aiko PATCH /posts '{"post_id":8,"text":"Thanks! See you at 3 (edited)"}'
as anon GET '/versions?post_id=8'
card
```

Expect: `403 post_not_yours` twice; `401` twice; `text_empty`; `post_missing`; Aiko's edit is
`200` with `"edited": true`; the old words are in versions.

### H2 Delete a post with no replies

```bash
step H2 "Delete a post with no replies: its likes and other people's bookmarks go too"
as aiko POST /posts '{"text":"This one will be deleted"}'
NEW=$(sqlite3 $DB 'select max(id) from posts')
as chika POST /likes "{\"post_id\":$NEW}"
as chika POST /bookmarks "{\"post_id\":$NEW}"
as aiko PATCH /posts "{\"post_id\":$NEW,\"text\":\"This one will be deleted (edited)\"}"
as aiko DELETE /posts "{\"post_id\":$NEW}"
note "rows -> posts $(sqlite3 $DB "select count(*) from posts where id=$NEW"), likes $(sqlite3 $DB "select count(*) from likes where post_id=$NEW"), bookmarks $(sqlite3 $DB "select count(*) from bookmarks where post_id=$NEW"), versions $(sqlite3 $DB "select count(*) from post_versions where post_id=$NEW")"
ids chika /bookmarks
card
```

Expect: `"post": null`; all four counts `0`; Chika's bookmark is gone.

### H3 Delete a post that has replies

```bash
step H3 "Delete a post that has replies: it stays as 'deleted' so the replies keep their place"
L=$(curl -s $QA_BASE/changes | python3 -c 'import json,sys; print(json.load(sys.stdin)["latest"])')
as aiko DELETE /posts '{"post_id":1}'
note "row 1 -> text='$(sqlite3 $DB 'select text from posts where id=1')' place=$(sqlite3 $DB 'select quote(place) from posts where id=1') likes=$(sqlite3 $DB 'select count(*) from likes where post_id=1')"
ids ben '/posts?before=0'
as aiko PATCH /posts '{"post_id":1,"text":"bring it back"}'
as ben POST /likes '{"post_id":1}'
as ben POST /bookmarks '{"post_id":1}'
as chika POST /posts '{"text":"reply to a deleted post","parent_id":1}'
as chika POST /reports '{"post_id":1}'
as anon GET '/search?q=library'
as ben GET "/changes?after=$L"
card
page ben / deleted-post-as-ben
```

Expect: `"deleted": true`, text `''`, place `NULL`, 0 likes; Ben sees `1:aiko(deleted)`;
`post_deleted`; `post_missing` (like, bookmark, report); `reply_to_deleted`; search finds
nothing. The screenshot shows "This post was deleted" with both replies under it.

### H4 The last reply goes, the empty post goes

```bash
step H4 "Ben deletes his reply, Aiko deletes hers: the empty post goes away too"
as aiko DELETE /posts '{"post_id":7}'
as ben DELETE /posts '{"post_id":7}'
as aiko DELETE /posts '{"post_id":8}'
note "rows for posts 1,7,8: $(sqlite3 $DB 'select count(*) from posts where id in (1,7,8)')"
as anon GET "/changes?after=$L"
card
```

Expect: Aiko cannot delete Ben's reply (`403`); after both replies go, `0` rows; the feed has
`deleted`, `replies_changed` and a last `deleted` for post 1.

## I. Reports (between people)

Three people report Dan's post. You may report only when you posted something before it.

### I1 Rules

```bash
step I1 "Report rules: login, own post, too early, once each, reason length"
as dan POST /posts '{"text":"Buy cheap watches here #spam"}'
T=$(sqlite3 $DB 'select max(id) from posts')
as eve POST /accounts '{"account_name":"eve","display_name":"Eve New","password":"correct-horse-eve"}'
as anon POST /reports "{\"post_id\":$T}"
as dan POST /reports "{\"post_id\":$T}"
as eve POST /reports "{\"post_id\":$T}"
as ben POST /reports "{\"post_id\":$T,\"reason\":\"$(python3 -c 'print("r"*201)')\"}"
as ben POST /reports "{\"post_id\":$T,\"reason\":\"spam\"}"
as ben POST /reports "{\"post_id\":$T}"
as chika DELETE /reports "{\"post_id\":$T}"
card
```

Expect: `401`; `report_own_post`; `report_too_early` (Eve has no earlier post);
`report_reason_too_long`; `201`; `report_already`; `report_not_there`.

### I2 Three reports hide it

```bash
step I2 "Three reports hide the post from everyone but its author"
as chika POST /reports "{\"post_id\":$T}"
ids anon '/posts?before=0'
L=$(curl -s $QA_BASE/changes | python3 -c 'import json,sys; print(json.load(sys.stdin)["latest"])')
as aiko POST /reports "{\"post_id\":$T,\"reason\":\"selling things\"}"
ids anon '/posts?before=0'
ids ben '/posts?before=0'
ids anon '/search?q=%23spam'
as anon GET "/changes?after=$L"
as dan GET /reports
as ben GET /reports
as anon GET /reports
card
page dan / hidden-post-as-author-dan
page eve / timeline-as-eve
```

Expect: after 2 reports the post is still there; after 3 it is gone for everyone and from search.
The feed has `"kind": "hidden", "post": null`. `GET /reports`: Dan has `mine_hidden: [T]`, Ben
has `reported: [T]`; no counts and no names anywhere. Dan's screenshot shows his post faded, with
"Hidden from others: several people reported it."

### I3 A report taken back

```bash
step I3 "One report taken back: the post is shown again"
L=$(curl -s $QA_BASE/changes | python3 -c 'import json,sys; print(json.load(sys.stdin)["latest"])')
as aiko DELETE /reports "{\"post_id\":$T}"
as aiko DELETE /reports "{\"post_id\":$T}"
as anon GET "/changes?after=$L"
ids anon '/posts?before=0'
card
```

Expect: `200`; `report_not_there`; a `shown` change with the post; the post is back.

## J. Bookmarks are private

### J1

```bash
step J1 "Bookmarks are private: nobody else can see or count them"
as ben POST /bookmarks '{"post_id":3}'
as ben POST /bookmarks '{"post_id":3}'
as ben POST /bookmarks '{"post_id":999}'
ids ben /bookmarks
ids chika /bookmarks
as anon GET /bookmarks
as chika GET '/bookmarks?user_id=2'
note "'bookmark' in GET /posts: $(curl -s $QA_BASE'/posts?before=0' | grep -c bookmark)"
as ben DELETE /bookmarks '{"post_id":3}'
as ben DELETE /bookmarks '{"post_id":3}'
card
```

Expect: `201`; `bookmark_already`; `post_missing`; Ben sees post 3; Chika (the author) sees
nothing; `401`; `?user_id=2` is ignored (Chika gets her own, empty list); `0`; `200`;
`bookmark_not_there`.

## K. Email (between people)

Nothing is really sent: the server prints each email in its terminal (`server.log`).

### K1 Save an address

```bash
step K1 "Email: save an address (unconfirmed); a confirm email is printed, not sent"
as anon GET /email
as aiko POST /email '{"email":"not-an-address"}'
as aiko POST /email '{"email":"a@b.com, c@d.com"}'
as aiko POST /email '{"email":"aiko@example.com"}'
as aiko POST /email '{"email":"aiko2@example.com"}'
as aiko GET /email
as ben GET /email
card
log_card confirm-email EMAIL 30
```

Expect: `401`; `email_not_valid` twice (one address can never become two); `201` unconfirmed;
`429 confirm_email_too_fast` (one confirm email per 5 minutes); Ben's answer never shows Aiko's
address. The terminal screenshot shows the confirm email, English then Japanese, framed by
`EMAIL` and `END OF EMAIL`.

### K2 Confirm

```bash
step K2 "Confirm with the token from the link; a wrong or reused token is refused"
TOKEN=$(grep -o 'confirm-email=[A-Za-z0-9_-]*' "$QA_LOG" | tail -1 | cut -d= -f2)
as anon POST /email-confirmations '{"token":"wrong-token"}'
as anon POST /email-confirmations "{\"token\":\"$TOKEN\"}"
as anon POST /email-confirmations "{\"token\":\"$TOKEN\"}"
as aiko GET /email
card
```

Expect: `email_link_wrong`; `200 confirmed: true` (no login needed); the same link again is
`email_link_wrong`.

### K3 A reply makes an email for the post's author

```bash
emails() { grep -c 'EMAIL (printed here' "$QA_LOG"; }
step K3 "Reply emails: Ben's reply to Aiko makes an email for Aiko; her own reply does not"
as aiko POST /posts '{"text":"Who is coming to the study group on Friday? #study"}'
P=$(sqlite3 $DB 'select max(id) from posts'); note "emails so far: $(emails)"
as ben POST /posts "{\"text\":\"Me! I will bring snacks\",\"parent_id\":$P}"
sleep 1; note "emails: $(emails)"
as aiko POST /posts "{\"text\":\"Great, thanks Ben\",\"parent_id\":$P}"
sleep 1; note "emails: $(emails)"
as chika POST /posts '{"text":"Reply to Ben (Ben has no address)","parent_id":2}'
sleep 1; note "emails: $(emails)"
card
log_card reply-email EMAIL 24
```

Expect: one more email after Ben's reply (to aiko@example.com); none for Aiko's reply to her
own post; none for a reply to Ben (no address).

### K4 The switch, and removing the address

```bash
step K4 "Switch off: no reply emails; remove the address"
as aiko DELETE /reply-emails
as chika POST /posts "{\"text\":\"I can come too\",\"parent_id\":$P}"
sleep 1; note "emails: $(emails)"
as aiko DELETE /email
as aiko GET /email
card
```

Expect: switch off → no new email; after removing, `email: null` and no row in `emails`.

### K5 Switch on, and an unconfirmed address

Every POST needs a JSON body, so send `{}` (the page does the same).

```bash
step K5 "Switch on (with {}), and no reply emails while unconfirmed"
as anon POST /reply-emails '{}'
as ben POST /reply-emails '{}'
as dan POST /email '{"email":"dan@example.com"}'
as dan POST /reply-emails '{}'
as chika POST /posts '{"text":"Reply to unconfirmed Dan","parent_id":4}'
sleep 1; note "emails: $(emails)"
as aiko GET /email
card
```

Expect: `401`; `email_missing` (Ben has no address); Dan's confirm email is printed, but no reply
email for Chika's reply (Dan has not confirmed). Aiko's answer never shows Dan's address.

## L. Search and trends

### L1

```bash
step L1 "Search and trends"
as anon GET '/search?q=%23study'
as anon GET '/search?q=study%20group'
as anon GET '/search?q=%25'
as anon GET '/search?q=a%20b%20c%20d%20e%20f'
as anon GET '/search?q='
as anon GET /trends
card
page anon '/?q=%23study' search-signed-out
```

Expect: `#study` finds only posts with that tag; two words must both match; `%` means itself
(nothing found); `search_too_many_words` (5); `search_empty`; trends count each tag once per post.

## M. Limits and sessions

### M1 Posts: 5 a minute per person

```bash
step M1 "Rate limit: 5 posts a minute per person; a refused post does not use one up"
as eve POST /posts '{"text":""}'
for i in 1 2 3 4 5; do as eve POST /posts "{\"text\":\"Eve post $i\"}"; done
as eve POST /posts '{"text":"Eve post 6"}'
note "$(curl -s -D - -o /dev/null -X POST -H 'Content-Type: application/json' -b $QA_JARS/eve --data '{"text":"7"}' $QA_BASE/posts | grep -i retry-after | tr -d '\r')"
as ben POST /posts '{"text":"Ben is not slowed down by Eve"}'
card
```

Expect: `text_empty`, then five `201`, then `429 post_too_fast` with `Retry-After: 60`; Ben's
post is `201`.

### M2 Logins: 5 tries in 10 minutes per account name

```bash
step M2 "Rate limit: 5 login tries in 10 minutes per account name"
for i in 1 2 3 4 5; do as x POST /sessions '{"account_name":"eve","password":"wrong-password"}'; done
as x POST /sessions '{"account_name":"eve","password":"correct-horse-eve"}'
as x2 POST /sessions '{"account_name":"ben","password":"correct-horse-ben"}'
as eve GET /sessions
card
```

Expect: five `401`, then `429 login_too_fast` even with the right password; Ben can still log in;
Eve's open session still works.

### M3 A made-up or old cookie is nobody

```bash
step M3 "A made-up or logged-out session cookie is nobody"
note "made-up cookie: $(curl -s -w ' %{http_code}' -b 'session=made-up-token' $QA_BASE/sessions)"
OLD=$(token aiko); as aiko DELETE /sessions
note "aiko's old token after log out: $(curl -s -w ' %{http_code}' -b "session=$OLD" $QA_BASE/sessions)"
as aiko POST /sessions '{"account_name":"aiko","password":"correct-horse-aiko"}'
card
page ben / final-timeline-as-ben
page ben / final-timeline-phone-as-ben 390
```

Expect: `401 login_ended` for both; Aiko logs in again. The last two screenshots show the whole
timeline, wide and at phone width.

## N. Last checks

### N1 Page files

```bash
step N1 "Page files and the style guide load"
for f in / /index.html /design.html /app.js /words.js /glass.js /tokens.css /base.css /components.css /features.css; do note "GET $f -> $(curl -s -o /dev/null -w '%{http_code} %{content_type}' $QA_BASE$f)"; done
card
page anon /design.html style-guide
done_step
```

Expect: every file `200` with the right type.

## Not covered by this runbook

These are covered by `make test` only, because a manual check would take too long or need a
clock: the like limit (30 a minute), the sign-up limit (30 an hour), the confirm link's 24 hours,
upgrading an old `timeline.db`, and `page-only/`.

## Finishing a run

1. Stop the server (Ctrl+C in its tab).
2. Look at every screenshot. A step passes only if its answers match "Expect".
3. Write `docs/qa/runs/YYYY-MM-DD.md` from the last run's entry: the version tested (`git log
   --oneline -1`), the result of `make test`, a table of steps, and anything found. Link the
   screenshots.
4. If something fails, write it under "Found", with the step, the request and the answer.
5. Commit the run's files on the run's branch.

If the server changes (a new route, a new rule between people), add a step here in the same
section, with its command and what to expect.
