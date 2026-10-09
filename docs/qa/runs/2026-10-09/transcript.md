### A1 The page loads signed out; unknown paths are 404

```
[anon] GET /sessions
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[anon] GET /nope
  -> 404 {"error": "There is nothing to GET at /nope.", "code": "nothing_here", "values": {"method": "GET", "path": "/nope"}}
[anon] GET /pictures/../server.py
  -> 404 {"error": "There is nothing to GET at /server.py.", "code": "nothing_here", "values": {"method": "GET", "path": "/server.py"}}
[screenshot A1-requests.png]
[screenshot A1-signed-out.jpg: the page as anon]
```

### B1 Four people sign up; each gets a session

```
[aiko] POST /accounts {"account_name":"aiko","display_name":"Aiko Tanaka","password":"correct-horse-aiko"}
  -> 201 {"account_name": "aiko", "display_name": "Aiko Tanaka"}
[ben] POST /accounts {"account_name":"ben","display_name":"Ben Ito","password":"correct-horse-ben"}
  -> 201 {"account_name": "ben", "display_name": "Ben Ito"}
[chika] POST /accounts {"account_name":"chika","display_name":"Chika Mori","password":"correct-horse-chika"}
  -> 201 {"account_name": "chika", "display_name": "Chika Mori"}
[dan] POST /accounts {"account_name":"dan","display_name":"Dan Sato","password":"correct-horse-dan"}
  -> 201 {"account_name": "dan", "display_name": "Dan Sato"}
[aiko] GET /sessions
  -> 200 {"account_name": "aiko", "display_name": "Aiko Tanaka", "post_count": 0, "like_count": 0}
# 1:aiko hash=64  2:ben hash=64  3:chika hash=64  4:dan hash=64
# passwords are stored only as hashes: 0 rows hold the password text
[screenshot B1-requests.png]
```

### B2 Sign-up rules: names unique in any case, password length, characters, empty name

```
[x] POST /accounts {"account_name":"AIKO","display_name":"Dup","password":"longenough1"}
  -> 400 {"error": "That account name is taken.", "code": "name_taken", "values": {}}
[x] POST /accounts {"account_name":"eve","display_name":"Eve","password":"short"}
  -> 400 {"error": "The password must be at least 8 characters.", "code": "password_too_short", "values": {"limit": 8}}
[x] POST /accounts {"account_name":"bad name!","display_name":"Eve","password":"longenough1"}
  -> 400 {"error": "The account name may use only letters, numbers and _.", "code": "name_characters", "values": {}}
[x] POST /accounts {"account_name":"","display_name":"Eve","password":"longenough1"}
  -> 400 {"error": "The name must not be empty.", "code": "name_empty", "values": {}}
[x] POST /accounts {"account_name":"eve","display_name":"Eve‮","password":"longenough1"}
  -> 400 {"error": "The display name must not have hidden characters or line breaks.", "code": "display_name_hidden", "values": {}}
# users still: 4
[screenshot B2-requests.png]
```

### B3 Log in: wrong password and unknown name give the same answer; name is any case

```
[x] POST /sessions {"account_name":"aiko","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[x] POST /sessions {"account_name":"nobody","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[aiko2] POST /sessions {"account_name":"AIKO","password":"correct-horse-aiko"}
  -> 201 {"account_name": "aiko", "display_name": "Aiko Tanaka"}
[aiko2] GET /sessions
  -> 200 {"account_name": "aiko", "display_name": "Aiko Tanaka", "post_count": 0, "like_count": 0}
[screenshot B3-requests.png]
```

### B4 Log out ends only that window's session

```
[aiko2] DELETE /sessions
  -> 200 {}
[aiko2] GET /sessions
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[aiko] GET /sessions
  -> 200 {"account_name": "aiko", "display_name": "Aiko Tanaka", "post_count": 0, "like_count": 0}
# sessions rows: 4 (one per window still logged in; tokens stored as hashes)
# cookie: Set-Cookie: session=<token>; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict
[screenshot B4-requests.png]
[screenshot B4-aiko-signed-in.jpg: the page as aiko]

### C1 Request guards: login needed, JSON only, JSON object only, size limit

```
[anon] POST /posts {"text":"hi"}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
# text/plain with aiko's cookie (what a form on another site could send): {"error": "The request must be JSON.", "code": "not_json", "values": {}} 400
[aiko] POST /posts [1]
  -> 400 {"error": "The request must be a JSON object.", "code": "not_json_object", "values": {}}
[aiko] POST /posts not json
  -> 400 {"error": "The request must be JSON.", "code": "not_json", "values": {}}
# Content-Length 5000000: {"error": "The request is too big.", "code": "request_too_big", "values": {}} 413
[dan] PATCH /accounts {}
  -> 404 {"error": "There is nothing to PATCH at /accounts.", "code": "nothing_here", "values": {"method": "PATCH", "path": "/accounts"}}
# posts saved: 0
[screenshot C1-requests.png]
```

### D1 Each person posts; the author comes from the cookie, never the JSON

```
[aiko] POST /posts {"text":"Good morning from the library #study","place":"Osaka"}
  -> 201 {"id": 1, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Good morning from the library #study", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": "Osaka", "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[ben] POST /posts {"text":"Lunch at the cafeteria #food"}
  -> 201 {"id": 2, "author": "ben", "display_name": "Ben Ito", "text": "Lunch at the cafeteria #food", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[chika] POST /posts {"text":"Hello @aiko see https://example.com/page."}
  -> 201 {"id": 3, "author": "chika", "display_name": "Chika Mori", "text": "Hello @aiko see https://example.com/page.", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[dan] POST /posts {"text":"Dan here, first post #study"}
  -> 201 {"id": 4, "author": "dan", "display_name": "Dan Sato", "text": "Dan here, first post #study", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[aiko] POST /posts {"text":"pretending to be ben","author":"ben","user_id":2}
  -> 201 {"id": 5, "author": "aiko", "display_name": "Aiko Tanaka", "text": "pretending to be ben", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# post 5 author in the database: aiko
[screenshot D1-requests.png]
```

### D2 Post rules: empty, too long, place too long, place with hidden characters

```
[aiko] POST /posts {"text":"   "}
  -> 400 {"error": "The post must not be empty.", "code": "text_empty", "values": {}}
[aiko] POST /posts {"text":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  -> 400 {"error": "The post must be 560 characters or fewer.", "code": "text_too_long", "values": {"limit": 560}}
[aiko] POST /posts {"text":"ok","place":"ppppppppppppppppppppppppppppppppppppppppp"}
  -> 400 {"error": "The place must be 40 characters or fewer.", "code": "place_too_long", "values": {"limit": 40}}
[aiko] POST /posts {"text":"bidi","place":"Osa‮ka"}
  -> 400 {"error": "The place must not have hidden characters or line breaks.", "code": "place_hidden", "values": {}}
[aiko] POST /posts {"text":"newline","place":"Osa\nka"}
  -> 400 {"error": "The place must not have hidden characters or line breaks.", "code": "place_hidden", "values": {}}
# posts saved: 5 (still 5)
[screenshot D2-requests.png]
```

### D3 Pictures: a PNG is kept; SVG and a missing description are refused; safe headers

```
[dan] POST /posts {"text":"My desk today #study","picture":"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGPQWxCFFTEMLQkA32xKAZlSJv4AAAAASUVORK5CYII=","picture_alt":"A small green square"}
  -> 201 {"id": 6, "author": "dan", "display_name": "Dan Sato", "text": "My desk today #study", "posted_at": "2026-10-09T07:49:52Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": {"url": "/pictures/6", "alt": "A small green square"}, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[dan] POST /posts {"text":"svg","picture":"PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=","picture_alt":"x"}
  -> 400 {"error": "The picture must be a PNG, JPEG, GIF or WebP file.", "code": "picture_wrong_kind", "values": {}}
[dan] POST /posts {"text":"no description","picture":"iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGPQWxCFFTEMLQkA32xKAZlSJv4AAAAASUVORK5CYII="}
  -> 400 {"error": "Please describe the picture in a few words.", "code": "picture_alt_empty", "values": {}}
# GET /pictures/6 headers: Content-Type: image/png X-Content-Type-Options: nosniff Content-Security-Policy: default-src 'none'; sandbox 
[screenshot D3-requests.png]
```

### D4 Pages of posts: newest first, before/after rules

```
# anon sees /posts?before=0 -> 6:dan 5:aiko 4:dan 3:chika 2:ben 1:aiko
# anon sees /posts?after=0 -> 1:aiko 2:ben 3:chika 4:dan 5:aiko 6:dan
# anon sees /posts?before=3 -> 2:ben 1:aiko
[anon] GET /posts?before=0&after=0
  -> 400 {"error": "Ask for 'before' or 'after', not both.", "code": "before_and_after", "values": {}}
[anon] GET /posts?before=abc
  -> 400 {"error": "'before' must be a whole number, 0 or more.", "code": "id_bound_not_number", "values": {"name": "before"}}
[anon] GET /posts?after=x
  -> 400 {"error": "'after' must be a whole number.", "code": "after_not_number", "values": {}}
[screenshot D4-requests.png]
[screenshot D4-timeline-signed-out.jpg: the page as anon]
```

### E1 Likes between people: one each, take back, counts from rows

```
[ben] POST /likes {"post_id":1}
  -> 201 {"post_id": 1, "like_count": 1}
[chika] POST /likes {"post_id":1}
  -> 201 {"post_id": 1, "like_count": 2}
[dan] POST /likes {"post_id":1}
  -> 201 {"post_id": 1, "like_count": 3}
[ben] POST /likes {"post_id":1}
  -> 400 {"error": "You have already liked that post.", "code": "like_already", "values": {}}
[aiko] POST /likes {"post_id":1}
  -> 201 {"post_id": 1, "like_count": 4}
[ben] POST /likes {"post_id":999}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
[ben] POST /likes {"post_id":"x"}
  -> 400 {"error": "The like must say which post it is for.", "code": "like_post_id_missing", "values": {}}
[anon] POST /likes {"post_id":1}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[ben] DELETE /likes {"post_id":1}
  -> 200 {"post_id": 1, "like_count": 3}
[ben] DELETE /likes {"post_id":1}
  -> 400 {"error": "You have not liked that post.", "code": "like_not_there", "values": {}}
[anon] GET /likes
  -> 200 {"counts": {"1": 3}, "mine": []}
[chika] GET /likes?from=1
  -> 200 {"counts": {"1": 3}, "mine": [1]}
# likes rows for post 1: aiko,chika,dan
[screenshot E1-requests.png]
```

### E2 Who liked: names A to Z, the summary line, and likes received on the profile

```
[anon] GET /likers?post_id=1
  -> 200 {"post_id": 1, "like_count": 3, "likers": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}, {"account_name": "chika", "display_name": "Chika Mori"}, {"account_name": "dan", "display_name": "Dan Sato"}]}
[chika] GET /likesummary?post_ids=1,2
  -> 200 {"summaries": {"1": {"like_count": 3, "you": true, "leaders": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}]}, "2": {"like_count": 0, "you": false, "leaders": []}}}
[aiko] GET /sessions
  -> 200 {"account_name": "aiko", "display_name": "Aiko Tanaka", "post_count": 2, "like_count": 2}
# aiko's like_count counts only likes from other people (chika, dan), not her own
[screenshot E2-requests.png]
```

### F1 Replies between people: one level only; own post allowed; counts

```
[ben] POST /posts {"text":"Nice, see you there @aiko","parent_id":1}
  -> 201 {"id": 7, "author": "ben", "display_name": "Ben Ito", "text": "Nice, see you there @aiko", "posted_at": "2026-10-09T07:50:12Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 1, "parent_author": "aiko", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[aiko] POST /posts {"text":"reply to a reply","parent_id":7}
  -> 400 {"error": "You can only reply to a post, not to a reply.", "code": "reply_to_reply", "values": {}}
[aiko] POST /posts {"text":"reply to nothing","parent_id":999}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
[aiko] POST /posts {"text":"Thanks! See you at 3","parent_id":1}
  -> 201 {"id": 8, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Thanks! See you at 3", "posted_at": "2026-10-09T07:50:12Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 1, "parent_author": "aiko", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# anon sees /posts?before=0 -> 8:aiko 7:ben 6:dan 5:aiko 4:dan 3:chika 2:ben 1:aiko
# post 1 as seen: reply_count 2 newest_reply_id 8
# reply 7 parent_author: aiko
[screenshot F1-requests.png]
[screenshot F1-timeline-as-chika.jpg: the page as chika]
```

### G1 Block: guards (login, self, unknown name, any case, twice); never adds a user

```
[aiko] POST /bookmarks {"post_id":6}
  -> 201 {"post_id": 6, "bookmarked": true}
[aiko] POST /bookmarks {"post_id":2}
  -> 201 {"post_id": 2, "bookmarked": true}
[anon] POST /blocks {"account_name":"dan"}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[aiko] POST /blocks {"account_name":"aiko"}
  -> 400 {"error": "You cannot block yourself.", "code": "block_self", "values": {}}
[aiko] POST /blocks {"account_name":"ghost"}
  -> 400 {"error": "There is no account @ghost.", "code": "account_missing", "values": {"name": "ghost"}}
[aiko] POST /blocks {"account_name":"DAN"}
  -> 201 {"account_name": "dan", "display_name": "Dan Sato"}
[aiko] POST /blocks {"account_name":"dan"}
  -> 400 {"error": "You have already blocked @dan.", "code": "block_already", "values": {"name": "dan"}}
[aiko] GET /blocks
  -> 200 {"blocked": [{"account_name": "dan", "display_name": "Dan Sato"}]}
[dan] GET /blocks
  -> 200 {"blocked": []}
[anon] GET /blocks
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
# blocks rows: 1->4   users: 4
[screenshot G1-requests.png]
```

### G2 Aiko blocked Dan: Dan's posts leave every list Aiko reads

```
# aiko sees /posts?before=0 -> 8:aiko 7:ben 5:aiko 3:chika 2:ben 1:aiko
# aiko sees /posts?after=0 -> 1:aiko 2:ben 3:chika 5:aiko 7:ben 8:aiko
# aiko sees /search?q=%23study -> 1:aiko
# aiko sees /bookmarks -> 2:ben
[aiko] GET /pictures/6
  -> 404 {"error": "There is nothing to GET at /pictures/6.", "code": "nothing_here", "values": {"method": "GET", "path": "/pictures/6"}}
[aiko] GET /trends
  -> 200 {"trends": [{"tag": "food", "count": 1}, {"tag": "study", "count": 1}]}
# ben sees /posts?before=0 -> 8:aiko 7:ben 6:dan 5:aiko 4:dan 3:chika 2:ben 1:aiko
# ben sees /search?q=%23study -> 6:dan 4:dan 1:aiko
[ben] GET /trends
  -> 200 {"trends": [{"tag": "study", "count": 3}, {"tag": "food", "count": 1}]}
[screenshot G2-requests.png]
[screenshot G2-timeline-as-aiko-blocker.jpg: the page as aiko]
[screenshot G2-search-as-aiko-blocker.jpg: the page as aiko]
```

### G3 Dan (blocked) still reads Aiko's posts, but cannot like or reply to them

```
# dan sees /posts?before=0 -> 8:aiko 7:ben 6:dan 5:aiko 4:dan 3:chika 2:ben 1:aiko
[dan] POST /likes {"post_id":5}
  -> 400 {"error": "You cannot like this post.", "code": "like_blocked", "values": {}}
[dan] POST /posts {"text":"reply to the blocker","parent_id":5}
  -> 400 {"error": "You cannot reply to this post.", "code": "reply_blocked", "values": {}}
[dan] POST /bookmarks {"post_id":5}
  -> 201 {"post_id": 5, "bookmarked": true}
[dan] POST /posts {"text":"Dan still posts"}
  -> 201 {"id": 9, "author": "dan", "display_name": "Dan Sato", "text": "Dan still posts", "posted_at": "2026-10-09T07:50:42Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[screenshot G3-requests.png]
[screenshot G3-timeline-as-dan-blocked.jpg: the page as dan]
```

### G4 Likes: Dan's old like still counts; only Aiko stops seeing his name

```
[aiko] GET /likers?post_id=1
  -> 200 {"post_id": 1, "like_count": 3, "likers": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}, {"account_name": "chika", "display_name": "Chika Mori"}]}
[ben] GET /likers?post_id=1
  -> 200 {"post_id": 1, "like_count": 3, "likers": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}, {"account_name": "chika", "display_name": "Chika Mori"}, {"account_name": "dan", "display_name": "Dan Sato"}]}
[aiko] GET /likesummary?post_ids=1
  -> 200 {"summaries": {"1": {"like_count": 3, "you": true, "leaders": [{"account_name": "chika", "display_name": "Chika Mori"}]}}}
[dan] DELETE /likes {"post_id":1}
  -> 200 {"post_id": 1, "like_count": 2}
[dan] POST /likes {"post_id":1}
  -> 400 {"error": "You cannot like this post.", "code": "like_blocked", "values": {}}
# Dan may take his like back, but not give it again
[screenshot G4-requests.png]
```

### G5 Reply counts leave out replies by people the viewer blocked

```
[dan] POST /posts {"text":"Dan replies to Chika","parent_id":3}
  -> 201 {"id": 10, "author": "dan", "display_name": "Dan Sato", "text": "Dan replies to Chika", "posted_at": "2026-10-09T07:51:03Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 3, "parent_author": "chika", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# aiko sees post 3: reply_count 0 newest_reply_id None
# ben sees post 3: reply_count 1 newest_reply_id 10
[screenshot G5-requests.png]
```

### G6 Changes feed and old versions: an edit by Dan reaches Ben, not Aiko

```
[dan] PATCH /posts {"post_id":9,"text":"Dan still posts (edited)"}
  -> 200 {"id": 9, "author": "dan", "display_name": "Dan Sato", "text": "Dan still posts (edited)", "posted_at": "2026-10-09T07:50:42Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": true, "deleted": false, "hidden_by_reports": false}
[aiko] GET /changes?after=0
  -> 200 {"latest": 1, "changes": [{"id": 1, "post_id": 9, "kind": "edited", "post": null}]}
[ben] GET /changes?after=0
  -> 200 {"latest": 1, "changes": [{"id": 1, "post_id": 9, "kind": "edited", "post": {"id": 9, "author": "dan", "display_name": "Dan Sato", "text": "Dan still posts (edited)", "posted_at": "2026-10-09T07:50:42Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": true, "deleted": false, "hidden_by_reports": false}}]}
[aiko] GET /versions?post_id=9
  -> 200 []
[ben] GET /versions?post_id=9
  -> 200 [{"text": "Dan still posts", "replaced_at": "2026-10-09T07:51:05Z"}]
[screenshot G6-requests.png]
```

### G7 The blocker can still like and reply to the blocked person's posts (by id)

```
[aiko] POST /likes {"post_id":4}
  -> 201 {"post_id": 4, "like_count": 1}
[aiko] POST /posts {"text":"reply to someone I blocked","parent_id":4}
  -> 201 {"id": 11, "author": "aiko", "display_name": "Aiko Tanaka", "text": "reply to someone I blocked", "posted_at": "2026-10-09T07:51:06Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 4, "parent_author": "dan", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# OBSERVATION: the spec only limits the blocked person. Aiko cannot see post 4, yet can act on it.
[screenshot G7-requests.png]
```

### G8 Unblock: everything comes back; Dan can like again

```
[anon] DELETE /blocks {"account_name":"dan"}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[aiko] DELETE /blocks {"account_name":"dan"}
  -> 200 {"account_name": "dan", "display_name": "Dan Sato"}
[aiko] DELETE /blocks {"account_name":"dan"}
  -> 400 {"error": "You have not blocked @dan.", "code": "block_not_there", "values": {"name": "dan"}}
[aiko] GET /blocks
  -> 200 {"blocked": []}
# aiko sees /posts?before=0 -> 11:aiko 10:dan 9:dan 8:aiko 7:ben 6:dan 5:aiko 4:dan 3:chika 2:ben 1:aiko
# aiko sees /bookmarks -> 6:dan 2:ben
# aiko sees post 3: reply_count 1 newest_reply_id 10
[aiko] GET /pictures/6
  -> 200 <image/png, 8x8 PNG>
[dan] POST /likes {"post_id":1}
  -> 201 {"post_id": 1, "like_count": 3}
# blocks rows: 0
[screenshot G8-requests.png]
[screenshot G8-timeline-as-aiko-after-unblock.jpg: the page as aiko]
```

### G9 Both block each other: neither sees, likes or replies to the other; one unblock leaves the other block

```
[ben] DELETE /likes {"post_id":3}
  -> 200 {"post_id": 3, "like_count": 0}
# (reset: ben's like on post 3 came from a first try of this step, before the helper fix)
[ben] POST /blocks {"account_name":"chika"}
  -> 201 {"account_name": "chika", "display_name": "Chika Mori"}
[chika] POST /blocks {"account_name":"ben"}
  -> 201 {"account_name": "ben", "display_name": "Ben Ito"}
# ben sees /posts?before=0 -> 11:aiko 10:dan 9:dan 8:aiko 7:ben 6:dan 4:dan 2:ben 1:aiko
# chika sees /posts?before=0 -> 11:aiko 10:dan 9:dan 8:aiko 6:dan 4:dan 3:chika 1:aiko
[ben] POST /likes {"post_id":3}
  -> 400 {"error": "You cannot like this post.", "code": "like_blocked", "values": {}}
[chika] POST /likes {"post_id":2}
  -> 400 {"error": "You cannot like this post.", "code": "like_blocked", "values": {}}
[chika] POST /posts {"text":"reply to ben","parent_id":2}
  -> 400 {"error": "You cannot reply to this post.", "code": "reply_blocked", "values": {}}
[ben] DELETE /blocks {"account_name":"chika"}
  -> 200 {"account_name": "chika", "display_name": "Chika Mori"}
# ben sees /posts?before=0 -> 11:aiko 10:dan 9:dan 8:aiko 7:ben 6:dan 4:dan 3:chika 2:ben 1:aiko
[ben] POST /likes {"post_id":3}
  -> 400 {"error": "You cannot like this post.", "code": "like_blocked", "values": {}}
# ben unblocked chika, but chika still blocks ben: ben sees chika's posts again yet cannot like them
[chika] DELETE /blocks {"account_name":"ben"}
  -> 200 {"account_name": "ben", "display_name": "Ben Ito"}
[ben] POST /likes {"post_id":3}
  -> 201 {"post_id": 3, "like_count": 1}
[screenshot G9-requests.png]
```

### H1 Only the author may edit or delete a post; an edit keeps the old words

```
[ben] PATCH /posts {"post_id":1,"text":"hacked by ben"}
  -> 403 {"error": "You can only change your own posts.", "code": "post_not_yours", "values": {}}
[ben] DELETE /posts {"post_id":1}
  -> 403 {"error": "You can only change your own posts.", "code": "post_not_yours", "values": {}}
[anon] PATCH /posts {"post_id":1,"text":"hacked"}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[anon] DELETE /posts {"post_id":1}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[aiko] PATCH /posts {"post_id":1,"text":""}
  -> 400 {"error": "The post must not be empty.", "code": "text_empty", "values": {}}
[aiko] PATCH /posts {"post_id":999,"text":"x"}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
[aiko] PATCH /posts {"post_id":8,"text":"Thanks! See you at 3 (edited)"}
  -> 200 {"id": 8, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Thanks! See you at 3 (edited)", "posted_at": "2026-10-09T07:50:12Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 1, "parent_author": "aiko", "reply_count": 0, "newest_reply_id": null, "edited": true, "deleted": false, "hidden_by_reports": false}
[anon] GET /versions?post_id=8
  -> 200 [{"text": "Thanks! See you at 3", "replaced_at": "2026-10-09T07:52:31Z"}]
# post 1 text: Good morning from the library #study
[screenshot H1-requests.png]
```

### H2 Delete a post with no replies: its likes and other people's bookmarks go too

```
[aiko] POST /posts {"text":"This one will be deleted"}
  -> 201 {"id": 12, "author": "aiko", "display_name": "Aiko Tanaka", "text": "This one will be deleted", "posted_at": "2026-10-09T07:52:33Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[chika] POST /likes {"post_id":12}
  -> 201 {"post_id": 12, "like_count": 1}
[chika] POST /bookmarks {"post_id":12}
  -> 201 {"post_id": 12, "bookmarked": true}
[aiko] PATCH /posts {"post_id":12,"text":"This one will be deleted (edited)"}
  -> 200 {"id": 12, "author": "aiko", "display_name": "Aiko Tanaka", "text": "This one will be deleted (edited)", "posted_at": "2026-10-09T07:52:33Z", "old_clock_time": null, "like_count": 1, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": true, "deleted": false, "hidden_by_reports": false}
[aiko] DELETE /posts {"post_id":12}
  -> 200 {"post_id": 12, "post": null}
# rows for post 12 -> posts 0, likes 0, bookmarks 0, versions 0
# chika sees /bookmarks -> (none)
[screenshot H2-requests.png]
```

### H3 Delete a post that has replies: it stays as 'deleted' so the replies keep their place

```
[aiko] DELETE /posts {"post_id":1}
  -> 200 {"post_id": 1, "post": {"id": 1, "author": "aiko", "display_name": "Aiko Tanaka", "text": "", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 2, "newest_reply_id": 8, "edited": false, "deleted": true, "hidden_by_reports": false}}
# row 1 -> text='' place=NULL deleted_at=2026-10-09T07:52:44Z likes=0
# ben sees /posts?before=0 -> 11:aiko 10:dan 9:dan 8:aiko 7:ben 6:dan 4:dan 3:chika 2:ben 1:aiko(deleted)
[aiko] PATCH /posts {"post_id":1,"text":"bring it back"}
  -> 400 {"error": "That post was deleted.", "code": "post_deleted", "values": {}}
[ben] POST /likes {"post_id":1}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
[ben] POST /bookmarks {"post_id":1}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
[chika] POST /posts {"text":"reply to a deleted post","parent_id":1}
  -> 400 {"error": "That post was deleted, so it cannot be answered.", "code": "reply_to_deleted", "values": {}}
[chika] POST /reports {"post_id":1}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
[anon] GET /search?q=library
  -> 200 {"posts": [], "more": false}
[ben] GET /changes?after=6
  -> 200 {"latest": 7, "changes": [{"id": 7, "post_id": 1, "kind": "deleted", "post": {"id": 1, "author": "aiko", "display_name": "Aiko Tanaka", "text": "", "posted_at": "2026-10-09T07:49:49Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 2, "newest_reply_id": 8, "edited": false, "deleted": true, "hidden_by_reports": false}}]}
[screenshot H3-requests.png]
[screenshot H3-deleted-post-as-ben.jpg: the page as ben]
```

### H4 Ben deletes his reply, Aiko deletes hers: the empty post goes away too

```
[aiko] DELETE /posts {"post_id":7}
  -> 403 {"error": "You can only change your own posts.", "code": "post_not_yours", "values": {}}
[ben] DELETE /posts {"post_id":7}
  -> 200 {"post_id": 7, "post": null}
[aiko] DELETE /posts {"post_id":8}
  -> 200 {"post_id": 8, "post": null}
# rows for posts 1,7,8: 0
[anon] GET /changes?after=6
  -> 200 {"latest": 11, "changes": [{"id": 7, "post_id": 1, "kind": "deleted", "post": null}, {"id": 8, "post_id": 7, "kind": "deleted", "post": null}, {"id": 9, "post_id": 1, "kind": "replies_changed", "post": null}, {"id": 10, "post_id": 8, "kind": "deleted", "post": null}, {"id": 11, "post_id": 1, "kind": "deleted", "post": null}]}
# anon sees /posts?before=0 -> 11:aiko 10:dan 9:dan 6:dan 4:dan 3:chika 2:ben
[screenshot H4-requests.png]
```

### I1 Report rules: login, own post, too early, once each, reason length

```
[dan] POST /posts {"text":"Buy cheap watches here #spam"}
  -> 201 {"id": 13, "author": "dan", "display_name": "Dan Sato", "text": "Buy cheap watches here #spam", "posted_at": "2026-10-09T07:53:06Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# target post: 13 (by dan)
[eve] POST /accounts {"account_name":"eve","display_name":"Eve New","password":"correct-horse-eve"}
  -> 201 {"account_name": "eve", "display_name": "Eve New"}
[anon] POST /reports {"post_id":13}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[dan] POST /reports {"post_id":13}
  -> 400 {"error": "You cannot report your own post.", "code": "report_own_post", "values": {}}
[eve] POST /reports {"post_id":13}
  -> 400 {"error": "You can report a post only after you have posted something before it.", "code": "report_too_early", "values": {}}
[ben] POST /reports {"post_id":13,"reason":"rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr
  -> 400 {"error": "The reason must be 200 characters or fewer.", "code": "report_reason_too_long", "values": {"limit": 200}}
[ben] POST /reports {"post_id":13,"reason":"spam"}
  -> 201 {"post_id": 13, "reported": true}
[ben] POST /reports {"post_id":13}
  -> 400 {"error": "You have already reported that post.", "code": "report_already", "values": {}}
[chika] DELETE /reports {"post_id":13}
  -> 400 {"error": "You have not reported that post.", "code": "report_not_there", "values": {}}
[screenshot I1-requests.png]
```

### I2 Three reports hide the post from everyone but its author

```
[chika] POST /reports {"post_id":13}
  -> 201 {"post_id": 13, "reported": true}
# anon sees /posts?before=0 -> 13:dan 11:aiko 10:dan 9:dan 6:dan 4:dan 3:chika 2:ben
[aiko] POST /reports {"post_id":13,"reason":"selling things"}
  -> 201 {"post_id": 13, "reported": true}
# anon sees /posts?before=0 -> 11:aiko 10:dan 9:dan 6:dan 4:dan 3:chika 2:ben
# ben sees /posts?before=0 -> 11:aiko 10:dan 9:dan 6:dan 4:dan 3:chika 2:ben
# eve sees /posts?before=0 -> 11:aiko 10:dan 9:dan 6:dan 4:dan 3:chika 2:ben
# anon sees /search?q=%23spam -> (none)
# dan (author) sees: 13 hidden_by_reports True
[anon] GET /changes?after=11
  -> 200 {"latest": 12, "changes": [{"id": 12, "post_id": 13, "kind": "hidden", "post": null}]}
[dan] GET /reports
  -> 200 {"hidden": [], "mine_hidden": [13], "reported": []}
[ben] GET /reports
  -> 200 {"hidden": [13], "mine_hidden": [], "reported": [13]}
[anon] GET /reports
  -> 200 {"hidden": [13], "mine_hidden": [], "reported": []}
# reports rows: 3; no count or reporter names in any answer
[screenshot I2-requests.png]
[screenshot I2-hidden-post-as-author-dan.jpg: the page as dan]
[screenshot I2-timeline-as-eve.jpg: the page as eve]
```

### I3 One report taken back: the post is shown again

```
[aiko] DELETE /reports {"post_id":13}
  -> 200 {"post_id": 13, "reported": false}
[aiko] DELETE /reports {"post_id":13}
  -> 400 {"error": "You have not reported that post.", "code": "report_not_there", "values": {}}
[anon] GET /changes?after=12
  -> 200 {"latest": 13, "changes": [{"id": 13, "post_id": 13, "kind": "shown", "post": {"id": 13, "author": "dan", "display_name": "Dan Sato", "text": "Buy cheap watches here #spam", "posted_at": "2026-10-09T07:53:06Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}}]}
# anon sees /posts?before=0 -> 13:dan 11:aiko 10:dan 9:dan 6:dan 4:dan 3:chika 2:ben
[screenshot I3-requests.png]
```

### J1 Bookmarks are private: nobody else can see or count them

```
[ben] POST /bookmarks {"post_id":3}
  -> 201 {"post_id": 3, "bookmarked": true}
[ben] POST /bookmarks {"post_id":3}
  -> 400 {"error": "You have already bookmarked that post.", "code": "bookmark_already", "values": {}}
[ben] POST /bookmarks {"post_id":999}
  -> 400 {"error": "That post does not exist.", "code": "post_missing", "values": {}}
# ben sees /bookmarks -> 3:chika
# chika sees /bookmarks -> (none)
[anon] GET /bookmarks
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[chika] GET /bookmarks?user_id=2
  -> 200 []
# a post shown to others has no bookmark field or count: 0 matches for 'bookmark' in GET /posts
[ben] DELETE /bookmarks {"post_id":3}
  -> 200 {"post_id": 3, "bookmarked": false}
[ben] DELETE /bookmarks {"post_id":3}
  -> 400 {"error": "You have not bookmarked that post.", "code": "bookmark_not_there", "values": {}}
[screenshot J1-requests.png]
```

### K1 Email: save an address (unconfirmed); a confirm email is printed, not sent

```
[anon] GET /email
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[aiko] POST /email {"email":"not-an-address"}
  -> 400 {"error": "That does not look like an email address.", "code": "email_not_valid", "values": {}}
[aiko] POST /email {"email":"a@b.com, c@d.com"}
  -> 400 {"error": "That does not look like an email address.", "code": "email_not_valid", "values": {}}
[aiko] POST /email {"email":"aiko@example.com"}
  -> 201 {"email": "aiko@example.com", "confirmed": false, "reply_emails": true}
[aiko] POST /email {"email":"aiko2@example.com"}
  -> 429 {"error": "Too many confirm emails. Please try again in 300 seconds.", "code": "confirm_email_too_fast", "values": {"count": 300}, "retry_after": 300}
[aiko] GET /email
  -> 200 {"email": "aiko@example.com", "confirmed": false, "reply_emails": true}
[ben] GET /email
  -> 200 {"email": null, "confirmed": false, "reply_emails": false}
# terminal shows the confirm email; token kept only as a hash: 1
[screenshot K1-requests.png]
[screenshot K1-confirm-email.png: the server terminal]
```

### K2 Confirm with the token from the link; a wrong or reused token is refused

```
[anon] POST /email-confirmations {"token":"wrong-token"}
  -> 400 {"error": "This confirm link is wrong or too old. Add your address again.", "code": "email_link_wrong", "values": {}}
[anon] POST /email-confirmations {"token":"ipgRh5UQlXxpMbg7BJX3bkRh9qwpci-AL0OhEnOqq-4"}
  -> 200 {"email": "aiko@example.com", "confirmed": true, "reply_emails": true}
[anon] POST /email-confirmations {"token":"ipgRh5UQlXxpMbg7BJX3bkRh9qwpci-AL0OhEnOqq-4"}
  -> 400 {"error": "This confirm link is wrong or too old. Add your address again.", "code": "email_link_wrong", "values": {}}
[aiko] GET /email
  -> 200 {"email": "aiko@example.com", "confirmed": true, "reply_emails": true}
[screenshot K2-requests.png]
```

### K3 Reply emails: Ben's reply to Aiko makes an email for Aiko; her own reply does not

```
[aiko] POST /posts {"text":"Who is coming to the study group on Friday? #study"}
  -> 201 {"id": 14, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Who is coming to the study group on Friday? #study", "posted_at": "2026-10-09T07:53:53Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# aiko's post: 14;  emails printed so far: 1
[ben] POST /posts {"text":"Me! I will bring snacks","parent_id":14}
  -> 201 {"id": 15, "author": "ben", "display_name": "Ben Ito", "text": "Me! I will bring snacks", "posted_at": "2026-10-09T07:53:54Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 14, "parent_author": "aiko", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# emails printed: 2 (one more: to aiko)
[aiko] POST /posts {"text":"Great, thanks Ben","parent_id":14}
  -> 201 {"id": 16, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Great, thanks Ben", "posted_at": "2026-10-09T07:53:55Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 14, "parent_author": "aiko", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# emails printed: 2 (no email for replying to your own post)
[chika] POST /posts {"text":"Reply to Ben (Ben has no address)","parent_id":2}
  -> 201 {"id": 17, "author": "chika", "display_name": "Chika Mori", "text": "Reply to Ben (Ben has no address)", "posted_at": "2026-10-09T07:53:56Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 2, "parent_author": "ben", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# emails printed: 2 (ben has no address: no email)
[screenshot K3-requests.png]
[screenshot K3-reply-email.png: the server terminal]
```

### K4 Switch off: no more reply emails; switch on again; remove the address

```
[aiko] DELETE /reply-emails
  -> 200 {"email": "aiko@example.com", "confirmed": true, "reply_emails": false}
[chika] POST /posts {"text":"I can come too","parent_id":14}
  -> 201 {"id": 18, "author": "chika", "display_name": "Chika Mori", "text": "I can come too", "posted_at": "2026-10-09T07:54:00Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 14, "parent_author": "aiko", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# emails printed: 2 (switch off: no email)
[aiko] POST /reply-emails
  -> 400 {"error": "The request must be JSON.", "code": "not_json", "values": {}}
[anon] POST /reply-emails
  -> 400 {"error": "The request must be JSON.", "code": "not_json", "values": {}}
[aiko] DELETE /email
  -> 200 {"email": null, "confirmed": false, "reply_emails": false}
[aiko] GET /email
  -> 200 {"email": null, "confirmed": false, "reply_emails": false}
# emails rows for aiko: 0
[screenshot K4-requests.png]
```

### K5 Switch on again (with a JSON body, as the page sends it)

```
# K4's POST /reply-emails had no body; every POST must be JSON, and the page sends {}. Not a bug.
[anon] POST /reply-emails {}
  -> 401 {"error": "Please log in first.", "code": "login_needed", "values": {}}
[ben] POST /reply-emails {}
  -> 400 {"error": "You have no email address saved.", "code": "email_missing", "values": {}}
[dan] POST /email {"email":"dan@example.com"}
  -> 201 {"email": "dan@example.com", "confirmed": false, "reply_emails": true}
[dan] POST /reply-emails {}
  -> 200 {"email": "dan@example.com", "confirmed": false, "reply_emails": true}
[dan] GET /email
  -> 200 {"email": "dan@example.com", "confirmed": false, "reply_emails": true}
[chika] POST /posts {"text":"Reply to unconfirmed Dan","parent_id":4}
  -> 201 {"id": 19, "author": "chika", "display_name": "Chika Mori", "text": "Reply to unconfirmed Dan", "posted_at": "2026-10-09T07:54:14Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": 4, "parent_author": "dan", "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
# emails printed: 3 (3 = the confirm email to dan; no reply email while unconfirmed)
[aiko] GET /email
  -> 200 {"email": null, "confirmed": false, "reply_emails": false}
# dan's address is only in dan's own answer
[screenshot K5-requests.png]
```

### L1 Search and trends

```
[anon] GET /search?q=%23study
  -> 200 {"posts": [{"id": 14, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Who is coming to the study group on Friday? #study", "posted_at": "2026-10-09T07:53:53Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 3, "newest_reply_id": 18, "edited": false, "deleted": false, "hidden_by_reports": false}, {"id": 6, "author": "dan", "display_name": "Dan Sato", "text": "My desk today #study", "posted_at": "2026-10-0
[anon] GET /search?q=study%20group
  -> 200 {"posts": [{"id": 14, "author": "aiko", "display_name": "Aiko Tanaka", "text": "Who is coming to the study group on Friday? #study", "posted_at": "2026-10-09T07:53:53Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 3, "newest_reply_id": 18, "edited": false, "deleted": false, "hidden_by_reports": false}], "more": false}
[anon] GET /search?q=%25
  -> 200 {"posts": [], "more": false}
[anon] GET /search?q=a%20b%20c%20d%20e%20f
  -> 400 {"error": "A search may have at most 5 words.", "code": "search_too_many_words", "values": {"limit": 5}}
[anon] GET /search?q=
  -> 400 {"error": "Type a word to search for.", "code": "search_empty", "values": {}}
[anon] GET /trends
  -> 200 {"trends": [{"tag": "study", "count": 3}, {"tag": "food", "count": 1}, {"tag": "spam", "count": 1}]}
[screenshot L1-requests.png]
[screenshot L1-search-signed-out.jpg: the page as anon]
```

### M1 Rate limit: 5 posts a minute per person; a refused post does not use one up; others are not affected

```
[eve] POST /posts {"text":""}
  -> 400 {"error": "The post must not be empty.", "code": "text_empty", "values": {}}
[eve] POST /posts {"text":"Eve post 1"}
  -> 201 {"id": 20, "author": "eve", "display_name": "Eve New", "text": "Eve post 1", "posted_at": "2026-10-09T07:54:34Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[eve] POST /posts {"text":"Eve post 2"}
  -> 201 {"id": 21, "author": "eve", "display_name": "Eve New", "text": "Eve post 2", "posted_at": "2026-10-09T07:54:34Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[eve] POST /posts {"text":"Eve post 3"}
  -> 201 {"id": 22, "author": "eve", "display_name": "Eve New", "text": "Eve post 3", "posted_at": "2026-10-09T07:54:34Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[eve] POST /posts {"text":"Eve post 4"}
  -> 201 {"id": 23, "author": "eve", "display_name": "Eve New", "text": "Eve post 4", "posted_at": "2026-10-09T07:54:34Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[eve] POST /posts {"text":"Eve post 5"}
  -> 201 {"id": 24, "author": "eve", "display_name": "Eve New", "text": "Eve post 5", "posted_at": "2026-10-09T07:54:34Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[eve] POST /posts {"text":"Eve post 6"}
  -> 429 {"error": "Too many posts. Please try again in 60 seconds.", "code": "post_too_fast", "values": {"count": 60}, "retry_after": 60}
# Retry-After header: Retry-After: 60
[ben] POST /posts {"text":"Ben is not slowed down by Eve"}
  -> 201 {"id": 25, "author": "ben", "display_name": "Ben Ito", "text": "Ben is not slowed down by Eve", "posted_at": "2026-10-09T07:54:34Z", "old_clock_time": null, "like_count": 0, "place": null, "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[screenshot M1-requests.png]
```

### M2 Rate limit: 5 login tries in 10 minutes per account name

```
[x] POST /sessions {"account_name":"eve","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[x] POST /sessions {"account_name":"eve","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[x] POST /sessions {"account_name":"eve","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[x] POST /sessions {"account_name":"eve","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[x] POST /sessions {"account_name":"eve","password":"wrong-password"}
  -> 401 {"error": "The account name or password is wrong.", "code": "login_wrong", "values": {}}
[x] POST /sessions {"account_name":"eve","password":"correct-horse-eve"}
  -> 429 {"error": "Too many wrong passwords for this account. Please try again in 600 seconds.", "code": "login_too_fast", "values": {"count": 600}, "retry_after": 600}
[x2] POST /sessions {"account_name":"ben","password":"correct-horse-ben"}
  -> 201 {"account_name": "ben", "display_name": "Ben Ito"}
[eve] GET /sessions
  -> 200 {"account_name": "eve", "display_name": "Eve New", "post_count": 5, "like_count": 0}
# eve's existing session still works; only new logins for @eve wait
[screenshot M2-requests.png]
```

### M3 A made-up or logged-out session cookie is nobody

```
# made-up cookie: {"error": "Your login has ended. Please log in again.", "code": "login_ended", "values": {}} 401
# made-up cookie posting: {"error": "Your login has ended. Please log in again.", "code": "login_ended", "values": {}} 401
[aiko] DELETE /sessions
  -> 200 {}
# aiko's old token after log out: {"error": "Your login has ended. Please log in again.", "code": "login_ended", "values": {}} 401
[aiko] POST /sessions {"account_name":"aiko","password":"correct-horse-aiko"}
  -> 201 {"account_name": "aiko", "display_name": "Aiko Tanaka"}
[screenshot M3-requests.png]
[screenshot M3-final-timeline-as-ben.jpg: the page as ben]
[screenshot M3-final-timeline-phone-as-ben.jpg: the page as ben]
```
```

### N1 Page files and the style guide load

```
# GET / -> 200 text/html; charset=utf-8
# GET /index.html -> 200 text/html; charset=utf-8
# GET /design.html -> 200 text/html; charset=utf-8
# GET /app.js -> 200 text/javascript; charset=utf-8
# GET /words.js -> 200 text/javascript; charset=utf-8
# GET /glass.js -> 200 text/javascript; charset=utf-8
# GET /tokens.css -> 200 text/css; charset=utf-8
# GET /base.css -> 200 text/css; charset=utf-8
# GET /components.css -> 200 text/css; charset=utf-8
# GET /features.css -> 200 text/css; charset=utf-8
[screenshot N1-requests.png]
[screenshot N1-style-guide.jpg: the page as anon]
```

### N2 Observation: a zero-width space is not a 'hidden character'

```
[chika] POST /posts {"text":"zero width space in place","place":"Osa​ka"}
  -> 201 {"id": 26, "author": "chika", "display_name": "Chika Mori", "text": "zero width space in place", "posted_at": "2026-10-09T07:55:50Z", "old_clock_time": null, "like_count": 0, "place": "Osa\u200bka", "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": false, "deleted": false, "hidden_by_reports": false}
[chika] PATCH /posts {"post_id":26,"text":"zero width space in text​"}
  -> 200 {"id": 26, "author": "chika", "display_name": "Chika Mori", "text": "zero width space in text\u200b", "posted_at": "2026-10-09T07:55:50Z", "old_clock_time": null, "like_count": 0, "place": "Osa\u200bka", "picture": null, "parent_id": null, "parent_author": null, "reply_count": 0, "newest_reply_id": null, "edited": true, "deleted": false, "hidden_by_reports": false}
# HIDDEN_CHARACTERS (server.py:861) covers control characters and direction marks only; U+200B, U+200C, U+200D, U+FEFF pass. Place is shown as 'Osaka' but is not equal to 'Osaka'.
[screenshot N2-requests.png]
```
