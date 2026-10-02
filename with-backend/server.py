"""Timeline: the backend. Start it with `python3 server.py`, then open http://localhost:8009

This file has three parts:
  CONTROLLER  reads each request and decides what to do
  MODEL       the rules, and the database (eleven tables: users, posts, likes, sessions,
              attempts, bookmarks, pictures, blocks, post_versions, changes and reports)
  VIEW        turns database rows into the JSON answer
The server never translates: a refusal names its rule by a code (see PROBLEMS),
and the page shows the words for that code in the reader's language (words.js).
It uses only the Python standard library, so there is nothing to install.
"""

import argparse
import base64
import hashlib
import hmac
import http.cookies
import json
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "timeline.db")

# The page files this server gives to the browser, and the type of each one.
PAGE_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/words.js": ("words.js", "text/javascript; charset=utf-8"),
}

# The name of the cookie that carries the session token.
SESSION_COOKIE = "session"


# ============================================================================
#  CONTROLLER
#  Reads the request. Picks what to do. Asks the model. Sends the answer.
#  Who is asking comes from the session cookie, never from the JSON: anyone
#  can write any name into a request, but only a person who logged in has
#  the cookie.
# ============================================================================

class TimelineHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/posts":
            # keep_blank_values: "?before=" is a wrong question, not no question.
            query = parse_qs(url.query, keep_blank_values=True)
            # timeline-flow: `before` asks for one page of older posts, `after`
            # for every newer post. Which request this is, is the controller's job.
            if "before" in query and "after" in query:
                self.send_problem(400, Problem("before_and_after"))
                return
            if "before" in query:
                self.show_posts_before(query["before"][0])
                return
            try:
                after = int(query.get("after", ["0"])[0])
            except ValueError:
                self.send_problem(400, Problem("after_not_number"))
                return
            # Who is asking decides which posts they may see (see visible_to).
            # Anyone may read, so nobody logged in is fine: the viewer is None.
            viewer = self.user_or_none()
            rows = posts_after(self.server.db_path, after, viewer["id"] if viewer else None)
            self.send_json(200, posts_to_json(rows))
        elif url.path == "/search":
            self.give_search(parse_qs(url.query).get("q", [""])[0])
        elif url.path == "/likes":
            # A like changes no post, so a window asks for the counts separately.
            # Anyone may read the counts; "mine" is empty for a window not logged in.
            # timeline-flow: `from` leaves out posts older than the oldest one
            # the window shows. Left out, it is 0: every post.
            user = self.user_or_none()
            try:
                counts, mine = likes_for(self.server.db_path, user["id"] if user else None,
                                         parse_qs(url.query, keep_blank_values=True).get("from", ["0"])[0])
            except RuleBroken as problem:
                self.send_problem(400, problem)
                return
            self.send_json(200, likes_to_json(counts, mine))
        elif url.path == "/likers":
            self.show_likers(parse_qs(url.query).get("post_id", [None])[0])
        elif url.path == "/likesummary":
            self.show_like_summaries(parse_qs(url.query).get("post_ids", [""])[0])
        elif url.path == "/changes":
            self.show_changes(parse_qs(url.query, keep_blank_values=True).get("after", [None])[0])
        elif url.path == "/versions":
            self.show_versions(parse_qs(url.query).get("post_id", [None])[0])
        elif url.path == "/bookmarks":
            self.show_bookmarks()
        elif url.path == "/blocks":
            self.show_blocks()
        elif url.path == "/reports":
            self.show_reports()
        elif url.path.startswith("/pictures/"):
            self.send_picture(url.path)
        elif url.path == "/sessions":
            # "Who am I?" The page asks this when it opens.
            user = self.signed_in_user()
            if user is not None:
                self.send_json(200, account_to_json(user))
        elif url.path in PAGE_FILES:
            file_name, content_type = PAGE_FILES[url.path]
            try:
                with open(os.path.join(HERE, file_name), "rb") as page_file:
                    self.send_answer(200, content_type, page_file.read())
            except OSError:
                self.send_problem(404, Problem("file_missing", file=file_name))
        else:
            self.send_nothing_here("GET", url.path)

    def show_posts_before(self, before):
        """timeline-flow: answer one page of posts older than `before`, newest first."""
        viewer = self.user_or_none()
        try:
            rows = posts_before(self.server.db_path, before, viewer["id"] if viewer else None)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, posts_to_json(rows))

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/posts", "/likes", "/accounts", "/sessions", "/bookmarks", "/blocks",
                        "/reports"):
            self.send_nothing_here("POST", path)
            return
        data = self.read_json()
        if data is None:
            return
        # The model raises TooFast before any answer is sent, so it is safe to
        # catch it here, once, for all four.
        try:
            if path == "/accounts":
                self.sign_up(data)
            elif path == "/sessions":
                self.log_in(data)
            elif path == "/likes":
                self.take_like(data)
            elif path == "/bookmarks":
                self.take_bookmark(data)
            elif path == "/blocks":
                self.take_block(data)
            elif path == "/reports":
                self.take_report(data)
            else:
                self.take_post(data)
        except TooFast as problem:
            self.send_too_fast(problem)

    def do_DELETE(self):
        # The method says what happens: POST adds a like or a session, and
        # DELETE takes one away.
        path = urlparse(self.path).path
        if path == "/sessions":
            log_out(self.server.db_path, self.session_token())
            self.send_json(200, {}, cookie=session_cookie(""))
            return
        if path == "/bookmarks":
            self.drop_bookmark()
            return
        if path == "/blocks":
            self.end_block()
            return
        if path == "/reports":
            self.drop_report()
            return
        if path == "/posts":
            self.take_delete()   # edit-delete
            return
        if path != "/likes":
            self.send_nothing_here("DELETE", path)
            return
        data = self.read_json()
        if data is None:
            return
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id, like_count = remove_like(self.server.db_path, user["id"],
                                              data.get("post_id"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        except TooFast as problem:
            self.send_too_fast(problem)
            return
        self.send_json(200, like_to_json(post_id, like_count))   # 200: nothing was created

    def do_PATCH(self):
        # edit-delete: PATCH means "change part of this thing". Only the text of
        # a post changes; its author, its time and its likes stay.
        path = urlparse(self.path).path
        if path != "/posts":
            self.send_nothing_here("PATCH", path)
            return
        self.take_edit()

    def read_json(self):
        """The JSON object sent with this request, or None if it was not JSON."""
        # Only a request that says it is JSON. A form on another website can
        # send plain text to this server, but it cannot send JSON without the
        # server agreeing first, and this server never agrees. So another site
        # cannot use a logged-in person's cookie to post as them.
        if self.headers.get_content_type() != "application/json":
            self.send_problem(400, Problem("not_json"))
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = None   # not a number: refused as "not JSON" just below
        # Too big: refused before it is read, so a huge request cannot fill the
        # server's memory. The size comes from the Content-Length header.
        if length is not None and length > MAX_REQUEST_BYTES:
            self.send_problem(413, Problem("request_too_big"))
            return None
        try:
            if length is None:
                raise ValueError("Content-Length is not a number")
            data = json.loads(self.rfile.read(length))
        except ValueError:
            self.send_problem(400, Problem("not_json"))
            return None
        if not isinstance(data, dict):
            self.send_problem(400, Problem("not_json_object"))
            return None
        return data

    def session_token(self):
        """The session token in this request's cookie, or "" if there is none."""
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            return ""
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel is not None else ""

    def signed_in_user(self):
        """The user who sent this request. If nobody is logged in, answer 401 and return None."""
        try:
            return user_for_session(self.server.db_path, self.session_token())
        except NotSignedIn as problem:
            self.send_problem(401, problem)
            return None

    def user_or_none(self):
        """The user who sent this request, or None. For a request anyone may make."""
        try:
            return user_for_session(self.server.db_path, self.session_token())
        except NotSignedIn:
            return None

    def sign_up(self, data):
        try:
            token, user = create_account(self.server.db_path, data.get("account_name"),
                                         data.get("display_name"), data.get("password"),
                                         # The address from the connection itself, never
                                         # from a header: a header can say anything.
                                         address=self.client_address[0])
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, account_to_json(user), cookie=session_cookie(token))

    def log_in(self, data):
        try:
            token, user = log_in(self.server.db_path, data.get("account_name"),
                                 data.get("password"))
        except NotSignedIn as problem:
            self.send_problem(401, problem)
            return
        self.send_json(201, account_to_json(user), cookie=session_cookie(token))

    def take_post(self, data):
        user = self.signed_in_user()
        if user is None:
            return
        try:
            # A picture and its description are optional (pictures): the model
            # decides what to do when one, both or neither is sent.
            more = {"place": data.get("place"), "picture": data.get("picture"),
                    "picture_alt": data.get("picture_alt")}
            # replies: with a parent_id it is a reply. This only chooses which
            # model function to call; the rules are in the model.
            if data.get("parent_id") is None:
                row = save_post(self.server.db_path, user["id"], data.get("text"), **more)
            else:
                row = save_reply(self.server.db_path, user["id"], data.get("text"),
                                 data.get("parent_id"), **more)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, post_to_json(row))
        print(post_to_log_line(row), flush=True)   # one line in the terminal for each new post
        if row["parent_id"] is not None:
            self.after_reply_saved(row)

    def after_reply_saved(self, row):
        """replies: called after a reply is saved AND its 201 answer has gone.

        The place for reply-email: it adds its lines here, with the saved row
        (it has id, author, parent_id and parent_author). The answer has already
        been sent, so nothing done here can slow a reply or turn it into an error.
        Today it does nothing.
        """

    def take_like(self, data):
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id, like_count = add_like(self.server.db_path, user["id"], data.get("post_id"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, like_to_json(post_id, like_count))

    # who-liked: anyone may read who liked a post, signed in or not.

    def show_likers(self, post_id):
        """GET /likers?post_id=7: everyone who liked one post, A to Z.

        The cookie is read only to leave out the people this viewer blocked
        (block). Nobody logged in is fine: then nobody is left out.
        """
        user = self.user_or_none()
        try:
            post_id, rows, like_count = who_liked(self.server.db_path, post_id,
                                                  user["id"] if user else None)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, likers_to_json(post_id, rows, like_count))

    def show_like_summaries(self, post_ids):
        """GET /likesummary?post_ids=3,7,9: the line under each post.

        The text is passed on as it is: splitting and checking it is the model's rule.
        """
        user = self.user_or_none()
        try:
            summaries = like_summaries(self.server.db_path, user["id"] if user else None,
                                       post_ids)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, summaries_to_json(summaries))

    def give_search(self, query):
        """GET /search?q=library: the posts with every word, newest first.

        Anyone may search. The viewer is read only so that visible_to applies.
        The search is passed on as it is: checking it is the model's rule.
        """
        viewer = self.user_or_none()
        try:
            rows, more = search_posts(self.server.db_path, query,
                                      viewer["id"] if viewer else None)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, search_to_json(rows, more))

    # bookmarks: private. Only the person who made a bookmark can ever see it.
    # Who is asking comes only from the cookie: a name, a user id or a query
    # string in the request is never read. Nothing is printed in the terminal
    # for a bookmark, because what someone saves is their own business.

    def show_bookmarks(self):
        """GET /bookmarks: your bookmarked posts, newest first. 401 when nobody is logged in."""
        user = self.signed_in_user()
        if user is None:
            return
        rows = bookmarks_for(self.server.db_path, user["id"])
        self.send_json(200, posts_to_json(rows))

    def take_bookmark(self, data):
        """POST /bookmarks with {post_id}: save a post for yourself."""
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id = add_bookmark(self.server.db_path, user["id"], data.get("post_id"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, bookmark_to_json(post_id, True))

    def drop_bookmark(self):
        """DELETE /bookmarks with {post_id}: take your bookmark back."""
        data = self.read_json()
        if data is None:
            return
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id = remove_bookmark(self.server.db_path, user["id"], data.get("post_id"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, bookmark_to_json(post_id, False))   # 200: nothing was created

    # block: blocking and unblocking need a login. Who blocks always comes
    # from the cookie; only the person being blocked comes from the JSON.

    def take_block(self, data):
        """POST /blocks {"account_name": "ben"}: block that account."""
        user = self.signed_in_user()
        if user is None:
            return
        try:
            blocked = add_block(self.server.db_path, user["id"], data.get("account_name"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, account_to_json(blocked))

    def end_block(self):
        """DELETE /blocks {"account_name": "ben"}: unblock that account."""
        data = self.read_json()
        if data is None:
            return
        user = self.signed_in_user()
        if user is None:
            return
        try:
            unblocked = remove_block(self.server.db_path, user["id"], data.get("account_name"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, account_to_json(unblocked))   # 200: nothing was created

    # report: POST /reports reports a post, DELETE /reports takes the report back,
    # GET /reports says which posts are hidden. Who reports is the person logged
    # in, from the cookie, never from the JSON.

    def take_report(self, data):
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id = add_report(self.server.db_path, user["id"], data.get("post_id"),
                                 data.get("reason"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, report_to_json(post_id, True))

    def drop_report(self):
        data = self.read_json()
        if data is None:
            return
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id = remove_report(self.server.db_path, user["id"], data.get("post_id"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, report_to_json(post_id, False))   # 200: nothing was created

    def show_reports(self):
        """GET /reports: anyone may ask. Not logged in, "mine_hidden" and "reported" are empty."""
        user = self.user_or_none()
        hidden, mine_hidden, reported = reports_for(self.server.db_path,
                                                    user["id"] if user else None)
        self.send_json(200, reports_to_json(hidden, mine_hidden, reported))

    def show_blocks(self):
        """GET /blocks: everyone this person has blocked. 401 when nobody is logged in."""
        user = self.signed_in_user()
        if user is None:
            return
        self.send_json(200, blocks_to_json(blocks_for(self.server.db_path, user["id"])))

    # pictures: anyone may see a post's picture, as anyone may read the post.

    def send_picture(self, path):
        """GET /pictures/7: the picture of post 7, or 404.

        Only digits are read from the address, and only as a number. No part of
        the request is ever used as a file name: the bytes come from the database.
        """
        found = PICTURE_ADDRESS.fullmatch(path)
        if found is None:
            self.send_nothing_here("GET", path)
            return
        # Who is asking decides which posts they may see, as for GET /posts, so
        # a hidden post's picture is hidden too.
        viewer = self.user_or_none()
        picture = picture_for(self.server.db_path, int(found.group(1)),
                              viewer["id"] if viewer else None)
        if picture is None:
            self.send_nothing_here("GET", path)
            return
        self.send_picture_answer(PICTURE_TYPES[picture["kind"]], picture["bytes"])

    def send_picture_answer(self, content_type, body):
        """200 with a picture's bytes, and the headers that keep it only a picture."""
        self.send_response(200)
        # The type the server found from the first bytes, never what was sent.
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # nosniff: the browser must believe the type and never guess another
        # one. So a file that starts like a PNG but hides a web page is still
        # only a picture.
        self.send_header("X-Content-Type-Options", "nosniff")
        # If someone opens the picture's address on its own, nothing in it can run.
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        # A post's picture never changes, so a window can keep it for a day.
        # "private": only this browser keeps it, because who may see a post
        # can depend on who is asking.
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    # edit-delete: change or delete your own post, and the changes feed.

    def take_edit(self):
        """PATCH /posts {post_id, text}: new words for one of your own posts."""
        data = self.read_json()
        if data is None:
            return
        user = self.signed_in_user()
        if user is None:
            return
        try:
            row = edit_post(self.server.db_path, user["id"], data.get("post_id"),
                            data.get("text"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        except NotAllowed as problem:
            self.send_problem(403, problem)
            return
        self.send_json(200, post_to_json(row))   # 200: nothing new was created

    def take_delete(self):
        """DELETE /posts {post_id}: delete one of your own posts."""
        data = self.read_json()
        if data is None:
            return
        user = self.signed_in_user()
        if user is None:
            return
        try:
            post_id, row = delete_post(self.server.db_path, user["id"], data.get("post_id"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        except NotAllowed as problem:
            self.send_problem(403, problem)
            return
        self.send_json(200, deleted_to_json(post_id, row))

    def show_changes(self, after):
        """GET /changes?after=7: every change since change 7. With no after: where the feed is.

        The cookie is read only so that each change brings the post as this
        viewer may see it (visible_to). Nobody logged in is fine.
        """
        viewer = self.user_or_none()
        try:
            latest, rows = changes_after(self.server.db_path, after,
                                         viewer["id"] if viewer else None)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, changes_to_json(latest, rows))

    def show_versions(self, post_id):
        """GET /versions?post_id=3: the earlier words of a post, oldest first. Anyone may read."""
        viewer = self.user_or_none()
        try:
            rows = versions_of(self.server.db_path, post_id, viewer["id"] if viewer else None)
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(200, versions_to_json(rows))

    def send_nothing_here(self, method, path):
        """404, in one sentence for every method, so it stays true when routes are added."""
        self.send_problem(404, Problem("nothing_here", method=method, path=path))

    def send_problem(self, status, problem):
        """Refuse the request. The answer names the rule by its code (see PROBLEMS)."""
        self.send_json(status, problem_to_json(problem))

    def send_too_fast(self, problem):
        """429 Too Many Requests. Retry-After is the standard header for the wait, in seconds."""
        body = json.dumps(too_fast_to_json(problem)).encode("utf-8")
        self.send_response(429)
        self.send_header("Retry-After", str(problem.retry_after))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, data, cookie=None):
        body = json.dumps(data).encode("utf-8")
        self.send_answer(status, "application/json; charset=utf-8", body, cookie)

    def send_answer(self, status, content_type, body, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Each window asks for new posts and new like counts every second.
        # Printing all of those questions would fill the screen, so they are not printed.
        # A search is not printed either: what a person searched for is their
        # own business, and the terminal may be shown on a screen in class.
        if self.command == "GET" and (self.path.startswith("/posts")
                                      or self.path.startswith("/likes")
                                      or self.path.startswith("/search")
                                      or self.path.startswith("/changes")):
            return
        BaseHTTPRequestHandler.log_message(self, format, *args)


# ============================================================================
#  MODEL
#  The rules, and the database. Eleven tables: users (each person once, with
#  both names and a salted password hash), posts (each post points at its
#  author by the author's id), likes (one row for each person who liked each
#  post), sessions (one row for each window that is logged in), attempts
#  (for the rate limits), bookmarks (one private row for each post a
#  person saved), pictures, blocks (one row for each person who blocked
#  another), post_versions (the earlier words of each edited post) and
#  changes (one row for each "this post changed", for open windows to hear)
#  and reports (one row for each person who reported each post).
#  A new rule goes here, never in the controller or the view.
# ============================================================================

MAX_TEXT = 560
MAX_AUTHOR = 40
MAX_DISPLAY_NAME = 50
MAX_PLACE = 40           # a place is a short label, like "Osaka", not a second post
MIN_PASSWORD = 8
MAX_PASSWORD = 200

# who-liked
MAX_LIKERS = 50          # at most this many names in the full list; the total is sent too
SUMMARY_NAMES = 2        # names in the summary line ("Anika, Chika, and 10 others")
MAX_SUMMARY_POSTS = 100  # at most this many posts in one GET /likesummary
POST_ID_TEXT = re.compile(r"[0-9]{1,18}")   # one post id, as text

# search
MAX_QUERY = 100        # characters in a search
MAX_QUERY_WORDS = 5    # words in a search
SEARCH_LIMIT = 50      # at most this many posts in one answer; "more" says if there were more
# A tag: # and then letters, digits or _. Japanese counts as letters:
# 々 (々), hiragana and katakana with ー (぀-ヿ), kanji
# (㐀-鿿), and half-width katakana (ｦ-ﾟ). A tag ends at the
# first other character: a space, punctuation, or an emoji. It is written with
# \u codes so that app.js holds exactly the same text (a test checks this).
# This is the one tag rule: links-and-tags uses it too, and never makes its own.
TAG = re.compile(r"#([0-9A-Za-z_々぀-ヿ㐀-鿿ｦ-ﾟ]+)")

# The largest request body the server will read: 4 MB, in bytes. Enough for a
# 2 MB picture written as text (base64 makes it about a third bigger), with room
# to spare. A bigger request is refused with 413 before it is read.
MAX_REQUEST_BYTES = 4 * 1024 * 1024

# pictures: one picture on a post, at most 2 MB, with a description (alt text)
# of 1 to 200 characters for people who cannot see it.
MAX_PICTURE_BYTES = 2 * 1024 * 1024
MAX_PICTURE_MB = MAX_PICTURE_BYTES // (1024 * 1024)   # the same limit, as the words say it
MIN_PICTURE_BYTES = 12        # the shortest real picture is longer than this
MAX_ALT_TEXT = 200
# The four kinds of picture, and the type the server sends for each. The kind
# is found from the file's first bytes (picture_kind), never from its name.
# SVG is never accepted: it is text, and it can hold a script.
PICTURE_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif",
                 "webp": "image/webp"}
# The address of one picture: /pictures/ and the post's id, digits only.
PICTURE_ADDRESS = re.compile(r"/pictures/([0-9]{1,18})")

# How many times the password is hashed. More is slower for an attacker who
# has copied the database and is guessing, and still fast enough for one
# login. Each user's own count is saved with their hash, so this can be
# raised later without breaking old accounts.
PASSWORD_ROUNDS = 600000

# A login lasts this many days, then the person logs in again.
SESSION_DAYS = 30

# An account name is the @name: letters, numbers and _ only, so it can never
# contain a space and is always one word after the @.
ACCOUNT_NAME = re.compile(r"[A-Za-z0-9_]+")

# Characters a display name may not hold: control characters, such as a new
# line, the two other line breaks (\u2028 and \u2029), and the invisible marks
# that turn text around. They are written as \u codes, because on screen they
# cannot be seen. Any of them could make one name look like another, or make
# a fake line in the server's terminal.
HIDDEN_CHARACTERS = re.compile(
    r"[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]")

# Every way a request can be refused, by code, with its English sentence.
#
# The server never translates. It sends the code, and the values that fill in
# the sentence ({limit} below is a value), and the page chooses the words in
# the reader's language from words.js. The English here is for the terminal,
# the tests, and anyone reading the answer with curl. words.js has every code
# too, with exactly the same English: a test checks it.
#
# A new rule adds its code at the end, under a comment with its feature's
# name. A code is lower case with _: first the thing (text_, like_), then
# what is wrong (_empty, _too_long). Never write Japanese here.
#
# Words with a number ("1 second", "60 seconds") are two entries, code_one and
# code_other. The code is raised without the ending, with the number as the
# value `count`, and the right one is chosen: Problem("post_too_fast", count=1).
PROBLEMS = {
    # accounts
    "name_empty": "The name must not be empty.",
    "name_too_long": "The name must be {limit} characters or fewer.",
    "name_characters": "The account name may use only letters, numbers and _.",
    "name_taken": "That account name is taken.",
    "display_name_too_long": "The display name must be {limit} characters or fewer.",
    "display_name_hidden": "The display name must not have hidden characters or line breaks.",
    "password_too_short": "The password must be at least {limit} characters.",
    "password_too_long": "The password must be {limit} characters or fewer.",
    "text_empty": "The post must not be empty.",
    "text_too_long": "The post must be {limit} characters or fewer.",
    "like_post_id_missing": "The like must say which post it is for.",
    "post_missing": "That post does not exist.",
    "like_already": "You have already liked that post.",
    "like_not_there": "You have not liked that post.",
    "login_wrong": "The account name or password is wrong.",
    "login_needed": "Please log in first.",
    "login_ended": "Your login has ended. Please log in again.",
    # the controller's own refusals
    "after_not_number": "'after' must be a whole number.",
    "not_json": "The request must be JSON.",
    "not_json_object": "The request must be a JSON object.",
    "file_missing": "The file {file} is missing.",
    # groundwork
    "nothing_here": "There is nothing to {method} at {path}.",
    "request_too_big": "The request is too big.",
    # who-liked
    "post_ids_missing": "The request must say which posts it is about.",
    "post_ids_too_many": "One request may ask about at most {limit} posts.",
    # rate-limit: words with a number are two entries, _one and _other (see Problem)
    "post_too_fast_one": "Too many posts. Please try again in {count} second.",
    "post_too_fast_other": "Too many posts. Please try again in {count} seconds.",
    "like_too_fast_one": "Too many likes. Please try again in {count} second.",
    "like_too_fast_other": "Too many likes. Please try again in {count} seconds.",
    "login_too_fast_one": "Too many wrong passwords for this account. "
                          "Please try again in {count} second.",
    "login_too_fast_other": "Too many wrong passwords for this account. "
                            "Please try again in {count} seconds.",
    "signup_too_fast_one": "Too many new accounts. Please try again in {count} second.",
    "signup_too_fast_other": "Too many new accounts. Please try again in {count} seconds.",
    # search
    "search_empty": "Type a word to search for.",
    "search_too_long": "A search must be {limit} characters or fewer.",
    "search_too_many_words": "A search may have at most {limit} words.",
    # timeline-flow
    "before_and_after": "Ask for 'before' or 'after', not both.",
    "id_bound_not_number": "'{name}' must be a whole number, 0 or more.",
    # bookmarks
    "bookmark_post_id_missing": "The bookmark must say which post it is for.",
    "bookmark_already": "You have already bookmarked that post.",
    "bookmark_not_there": "You have not bookmarked that post.",
    # place
    "place_too_long": "The place must be {limit} characters or fewer.",
    "place_hidden": "The place must not have hidden characters or line breaks.",
    # pictures
    "picture_wrong_kind": "The picture must be a PNG, JPEG, GIF or WebP file.",
    "picture_too_big": "The picture must be {limit} MB or smaller.",
    "picture_unreadable": "The picture could not be read.",
    "picture_missing": "Please choose a picture for this description.",
    "picture_alt_empty": "Please describe the picture in a few words.",
    "picture_alt_too_long": "The description must be {limit} characters or fewer.",
    "picture_alt_hidden": "The description must not have hidden characters or line breaks.",
    # block
    "account_missing": "There is no account @{name}.",
    "block_self": "You cannot block yourself.",
    "block_already": "You have already blocked @{name}.",
    "block_not_there": "You have not blocked @{name}.",
    "like_blocked": "You cannot like this post.",
    # replies
    "reply_parent_id_missing": "The reply must say which post it answers.",
    "reply_to_reply": "You can only reply to a post, not to a reply.",
    "reply_blocked": "You cannot reply to this post.",
    # edit-delete
    "post_id_missing": "The request must say which post it is for.",
    "post_not_yours": "You can only change your own posts.",
    "post_deleted": "That post was deleted.",
    "edit_unchanged": "The post is the same as before.",
    "post_delete_refused": "That post cannot be deleted yet.",
    "reply_to_deleted": "That post was deleted, so it cannot be answered.",
    # report
    "report_own_post": "You cannot report your own post.",
    "report_too_early": "You can report a post only after you have posted something before it.",
    "report_already": "You have already reported that post.",
    "report_not_there": "You have not reported that post.",
    "report_reason_not_text": "The reason must be text.",
    "report_reason_too_long": "The reason must be {limit} characters or fewer.",
}

# One code for a wrong name and for a wrong password, so a stranger cannot use
# the login form to find out which account names exist.
WRONG_LOGIN = "login_wrong"


class Problem(Exception):
    """Something the request cannot do. `code` names the rule; `values` fill in its sentence.

    str(problem) is the English sentence from PROBLEMS, so the terminal and the
    tests read it as before. A code that is not in PROBLEMS raises KeyError at
    once, so a forgotten entry fails the first test that reaches it.
    """

    def __init__(self, code, **values):
        Exception.__init__(self, problem_sentence(code, values).format(**values))
        self.code = code
        self.values = values


def problem_sentence(code, values):
    """The English for this code: PROBLEMS[code], or for words with a number,
    code_one when the value `count` is 1 and code_other for any other number."""
    if code in PROBLEMS:
        return PROBLEMS[code]
    return PROBLEMS[code + ("_one" if values.get("count") == 1 else "_other")]


class RuleBroken(Problem):
    """A request broke one of the rules (400). The code says which rule."""


class NotSignedIn(Problem):
    """Nobody is logged in, or the login was wrong (401). The code says which."""


class NotAllowed(Problem):
    """The person is logged in, but this is not theirs to change (403)."""


# edit-delete: the kinds of row the changes table may hold. The database has no
# CHECK for this (SQLite cannot change a CHECK without rebuilding the table), so
# record_change checks it. A feature that hides or shows a post (report) adds
# its own kinds here, in one line, for example "hidden" and "shown".
CHANGE_KINDS = (
    "edited",            # new words
    "deleted",           # removed, or kept as "This post was deleted" for its replies
    "replies_changed",   # a reply to this post was deleted, so its reply count changed
    "hidden", "shown",   # report: the post just reached, or just fell below, HIDE_AFTER_REPORTS
)


# Rate limits: at most this many times, in this many seconds. One place for
# every limit. A post or a like is counted for each signed-in user, a login
# for each account name typed, and a sign-up for each address. Sign-ups are
# 30 an hour because today every request comes from 127.0.0.1, so everyone
# using the server shares that one count.
LIMITS = {"post": (5, 60), "like": (30, 60), "login": (5, 600), "signup": (30, 3600)}
# The code (in PROBLEMS) for "too many, too quickly", for each limit.
TOO_FAST = {"post": "post_too_fast", "like": "like_too_fast", "login": "login_too_fast",
            "signup": "signup_too_fast"}


class TooFast(Problem):
    """Too many attempts too quickly (429). retry_after says how many seconds to wait.

    A Problem with a code, like every refusal, but not a kind of RuleBroken,
    so it can never be sent as a 400 by mistake. The wait is also its value
    {count}, so the page can say it in the reader's language ("1 second",
    "60 seconds": the code has a _one and an _other entry).
    """

    def __init__(self, code, count):
        Problem.__init__(self, code, count=count)
        self.retry_after = count


def connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row  # so a row can be read as row["author"]
    connection.execute("PRAGMA foreign_keys = ON")  # a post must point at a real user
    return connection


# The newest version of the database: the number the last upgrade below sets.
# Each new upgrade raises it by one, and the tests read it from here.
LATEST_VERSION = 11


def create_tables(db_path):
    """Make the tables, or bring an older timeline.db up to date without losing anything.

    Every database, new or old, takes the same steps: first the tables as they
    were at version 0, then each upgrade it has not had yet. SQLite keeps the
    version number in the file itself (PRAGMA user_version).
    """
    connection = connect(db_path)
    old = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
    if old and "author_id" not in old:
        connection.close()
        raise SystemExit("timeline.db was made by a much older version of Timeline. "
                         "Run `make reset`, then start the server again.")
    connection.execute("CREATE TABLE IF NOT EXISTS users ("
                       "id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    connection.execute("CREATE TABLE IF NOT EXISTS posts ("
                       "id INTEGER PRIMARY KEY, "
                       "author_id INTEGER NOT NULL REFERENCES users(id), "
                       "text TEXT NOT NULL, posted_at TEXT NOT NULL)")
    # One row for each person who liked each post. The count is never kept
    # here: it is counted from these rows, so the two can never disagree.
    # PRIMARY KEY (post_id, user_id) is what stops a second like from the
    # same person. The database refuses it, even if the page and the rules
    # below are both got around.
    connection.execute("CREATE TABLE IF NOT EXISTS likes ("
                       "post_id INTEGER NOT NULL REFERENCES posts(id), "
                       "user_id INTEGER NOT NULL REFERENCES users(id), "
                       "PRIMARY KEY (post_id, user_id))")
    connection.commit()
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        upgrade_to_accounts(connection)
    if version < 2:
        upgrade_to_groundwork(connection)
    if version < 3:
        upgrade_to_timestamps(connection)
    if version < 4:
        upgrade_to_rate_limit(connection)
    if version < 5:
        upgrade_to_bookmarks(connection)
    if version < 6:
        upgrade_to_place(connection)
    if version < 7:
        upgrade_to_pictures(connection)
    if version < 8:
        upgrade_to_block(connection)
    if version < 9:
        upgrade_to_replies(connection)
    if version < 10:
        upgrade_to_edit_delete(connection)
    if version < 11:
        upgrade_to_report(connection)
    connection.close()


def upgrade_to_accounts(connection):
    """Version 1: accounts. Every old user and post is kept.

    An old user has no password yet (password_hash is NULL), so nobody can log
    in as them. The first person to sign up with that name claims it, and its
    old posts. Every step is in one transaction: all of them happen, or none.
    """
    connection.execute("BEGIN")
    try:
        # name is the account name (@aiko): it never changes, and it is how a
        # person is found. display_name is the name shown with each post (Aiko Tanaka).
        connection.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        connection.execute("UPDATE users SET display_name = name")
        # The password is never kept. Only a hash of it, made with this user's
        # own salt, hashed this many rounds. All three are NULL until claimed.
        connection.execute("ALTER TABLE users ADD COLUMN password_salt TEXT")
        connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        connection.execute("ALTER TABLE users ADD COLUMN password_rounds INTEGER")
        # @Aiko and @aiko would look like one person, so the database refuses
        # a second name that differs only in capital letters.
        connection.execute("CREATE UNIQUE INDEX users_name_any_case "
                           "ON users (name COLLATE NOCASE)")
        # One row for each login. The token itself is never kept, only its
        # hash, so a copy of this file is not enough to log in as anyone.
        connection.execute("CREATE TABLE sessions ("
                           "token_hash TEXT PRIMARY KEY, "
                           "user_id INTEGER NOT NULL REFERENCES users(id), "
                           "expires_at INTEGER NOT NULL)")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        connection.close()
        raise SystemExit("timeline.db has two users whose names differ only in capital "
                         "letters. Rename one, or run `make reset`, then start again.")


def rebuild_table(connection, table, change_sql, user_version=None, prepare=None):
    """Make `table` again from its own CREATE TABLE text, changed by `change_sql`.

    SQLite cannot change some things in a table that already exists (for example,
    add AUTOINCREMENT). The safe way is to make a new table and move the rows:
      1. read the table's CREATE TABLE text, and its indexes and triggers;
      2. change_sql(text) returns the new text (change_sql is a function);
      3. make the new table, copy every row, drop the old table, and give the
         new one the old name;
      4. make the indexes and triggers again.
    It starts from the table's own text, so a column, an index or a trigger
    that another upgrade added is kept.

    All of it is one transaction (a group of changes that all happen, or none
    do). If user_version is given, the new version number is saved in the same
    transaction. Foreign keys are turned off while the table is briefly gone,
    then checked by hand before anything is saved.

    If prepare is given, it is a function that gets the connection and makes a
    small change to the old table first (for example, renames a column), inside
    the same transaction. The rows are then copied by the new names.
    """
    if connection.in_transaction:
        # A mistake in the code, not a user's broken rule: foreign keys can
        # only be turned off outside a transaction.
        raise ValueError("rebuild_table must be called outside a transaction.")
    # Before BEGIN: inside a transaction SQLite ignores this.
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        try:
            if prepare is not None:
                prepare(connection)
            row = connection.execute("SELECT sql FROM sqlite_master "
                                     "WHERE type = 'table' AND name = ?", (table,)).fetchone()
            if row is None:
                raise SystemExit(f"timeline.db has no {table} table to rebuild. "
                                 "Run `make reset`, then start again.")
            old_sql = row[0]
            others = [r[0] for r in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('index', 'trigger') "
                "AND tbl_name = ? AND sql IS NOT NULL ORDER BY type, name", (table,))]
            new_sql = change_sql(old_sql)
            if new_sql != old_sql:
                # The new table is made under another name first: <table>_new.
                name = re.escape(table)
                start = re.compile(r'^CREATE TABLE\s+(?:"' + name + '"|' + name + r')\s*\(',
                                   re.IGNORECASE)
                if not start.match(new_sql):
                    raise SystemExit(f"timeline.db has a {table} table this upgrade does "
                                     "not know. Run `make reset`, then start again.")
                new_name = table + "_new"
                connection.execute(start.sub(f"CREATE TABLE {new_name} (", new_sql, count=1))
                # Copy by the old table's column names, so every value goes to
                # the column of the same name, and every id is kept. (Rows are
                # read by number here, [0] and [1], so this works on any
                # connection. In PRAGMA table_info, [1] is the column's name.)
                columns = ", ".join('"' + c[1] + '"' for c in
                                    connection.execute(f'PRAGMA table_info("{table}")'))
                connection.execute(f'INSERT INTO {new_name} ({columns}) '
                                   f'SELECT {columns} FROM "{table}"')
                connection.execute(f'DROP TABLE "{table}"')
                connection.execute(f'ALTER TABLE {new_name} RENAME TO "{table}"')
                for sql in others:
                    connection.execute(sql)
            # Foreign keys were off, so check by hand that every row that
            # points at another row still points at a real one.
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise SystemExit(f"timeline.db has rows that point at nothing after "
                                 f"rebuilding {table}. Nothing was changed.")
            if user_version is not None:
                connection.execute(f"PRAGMA user_version = {int(user_version)}")
            connection.commit()
        except sqlite3.Error as problem:
            connection.rollback()
            raise SystemExit(f"timeline.db could not be brought up to date ({table}: "
                             f"{problem}). Nothing was changed.")
        except BaseException:
            connection.rollback()   # nothing is half done
            raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def upgrade_to_groundwork(connection):
    """Version 2: a post id is never given out twice. Every row is kept.

    Without AUTOINCREMENT, SQLite gives a new post the largest id plus one. If
    the newest post were deleted, the next post would get its id again, and a
    window that has already seen that id would never ask for the new post.
    With AUTOINCREMENT, SQLite remembers the largest id it ever gave (in its own
    table, sqlite_sequence) and never gives it again. A table that exists
    cannot be given AUTOINCREMENT, so posts is rebuilt.
    """
    def add_autoincrement(sql):
        if "AUTOINCREMENT" in sql.upper():
            return sql
        start = re.compile(r"\(\s*id\s+INTEGER\s+PRIMARY\s+KEY\s*,", re.IGNORECASE)
        if not start.search(sql):
            raise SystemExit("timeline.db has a posts table this upgrade does not know. "
                             "Run `make reset`, then start again.")
        return start.sub("(id INTEGER PRIMARY KEY AUTOINCREMENT,", sql, count=1)

    rebuild_table(connection, "posts", add_autoincrement, user_version=2)


# timestamps: what posted_at and old_clock_time may hold. GLOB is a simple text
# pattern: [0-9] is one digit. A CHECK on an empty (NULL) value passes, so each
# column's own check applies only when it has a value. The second CHECK on
# old_clock_time says that exactly one of the two has a value: never both, never
# neither. It is written on the column, not at the end of the table, so the
# table's text still ends with a column, and a later upgrade can add one there.
POSTED_AT_COLUMN = ("posted_at TEXT CHECK (posted_at GLOB "
                    "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')")
OLD_CLOCK_TIME_COLUMN = ("old_clock_time TEXT CHECK (old_clock_time GLOB '[0-9][0-9]:[0-9][0-9]') "
                         "CHECK ((posted_at IS NULL) <> (old_clock_time IS NULL))")


def upgrade_to_timestamps(connection):
    """Version 3: a post keeps its full date and time, in UTC. Every row is kept.

    Before this, posted_at held only the clock time, like 15:42, with no date.
    That old text cannot become a real date honestly, so it moves to a new
    column, old_clock_time, and posted_at is left empty (NULL) for those posts.
    A new post gets a full time, like 2026-10-02T07:42:10Z, and no old_clock_time.

    posted_at was NOT NULL, and SQLite cannot change that in place, so posts is
    rebuilt with rebuild_table: posted_at is renamed old_clock_time first, then
    the new table has both columns and their checks. The ids do not change, so
    every like still points at the right post.
    """
    not_a_clock_time = connection.execute(
        "SELECT COUNT(*) FROM posts WHERE posted_at NOT GLOB '[0-9][0-9]:[0-9][0-9]'"
    ).fetchone()[0]
    if not_a_clock_time:
        connection.close()
        raise SystemExit("timeline.db has a post whose time is not like 15:42, so it cannot "
                         "be brought up to date. Run `make reset`, then start again.")

    def rename_old_time(connection):
        connection.execute("ALTER TABLE posts RENAME COLUMN posted_at TO old_clock_time")

    def add_full_time(sql):
        old = re.compile(r'"?old_clock_time"?\s+TEXT\s+NOT\s+NULL', re.IGNORECASE)
        if not old.search(sql):
            raise SystemExit("timeline.db has a posts table this upgrade does not know. "
                             "Run `make reset`, then start again.")
        return old.sub(POSTED_AT_COLUMN + ", " + OLD_CLOCK_TIME_COLUMN, sql, count=1)

    rebuild_table(connection, "posts", add_full_time, user_version=3, prepare=rename_old_time)

def upgrade_to_rate_limit(connection):
    """Version 4: the attempts table, for the rate limits. Every row is kept.

    (Version 3 is timestamps, built on another branch at the same time. The
    number 4 is for now: the orchestrator gives the final numbers at merge.)

    One row is one allowed attempt: what was done, by whom, and when. A count
    is never kept: it is counted from the rows. Nothing points at this table,
    and it holds no password and no post text.
    """
    connection.execute("BEGIN")
    connection.execute("CREATE TABLE IF NOT EXISTS attempts ("
                       "action TEXT NOT NULL, "   # 'post', 'like', 'login' or 'signup'
                       "key TEXT NOT NULL, "      # a user id, an account name, or an address
                       "at REAL NOT NULL)")       # when, in seconds (see clock)
    connection.execute("CREATE INDEX IF NOT EXISTS attempts_by_key "
                       "ON attempts (action, key, at)")
    connection.execute("PRAGMA user_version = 4")
    connection.commit()


def upgrade_to_bookmarks(connection):
    """Version 5: the bookmarks table. Every row is kept; this only adds a table.

    (5 is for now: the orchestrator gives the final numbers at merge.)

    One row is one post one person saved for themselves. It is private: no
    count is kept or shown, and only that person can ever read their rows.
    PRIMARY KEY (user_id, post_id) means the database itself refuses a second
    bookmark of the same post by the same person. user_id comes first because
    bookmarks are always read for one person, so that lookup needs no other
    index. ON DELETE CASCADE: if a post or a user is ever deleted, the database
    deletes their bookmarks too ("cascade": the delete flows on to the rows
    that point at it). It works because connect turns foreign keys on.
    """
    connection.execute("BEGIN")
    connection.execute("CREATE TABLE IF NOT EXISTS bookmarks ("
                       "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                       "post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, "
                       "PRIMARY KEY (user_id, post_id))")
    connection.execute("PRAGMA user_version = 5")
    connection.commit()


def upgrade_to_place(connection):
    """Version 6: each post can say where it was written. Every old post is kept.

    An old post has no place: its place is NULL. A new post with no place is
    NULL too, so there is only one way to say "no place". The place is on
    posts, never on users: the same person writes in Osaka today and in Kyoto
    tomorrow, and a place on users would change every old post.
    Adding a column keeps every row, so no rebuild is needed.
    """
    connection.execute("BEGIN")
    columns = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
    # Like CREATE TABLE IF NOT EXISTS: if the column is already there, it is not
    # added twice (for example, a file whose version number was set back).
    if "place" not in columns:
        # The database refuses an empty place and a place that is too long, even if
        # the rule in check_place is got around. NULL passes the CHECK, so old posts
        # pass. length() in SQLite counts characters, as len() does in Python.
        connection.execute("ALTER TABLE posts ADD COLUMN place TEXT "
                           "CHECK (place IS NULL OR length(place) BETWEEN 1 AND 40)")
    connection.execute("PRAGMA user_version = 6")
    connection.commit()


def upgrade_to_pictures(connection):
    """Version 7: the pictures table. Every row is kept; old posts have no picture.

    A picture is its own table, not a column of posts, so a query for posts
    never reads picture bytes by accident. The database itself makes sure of
    these rules, even if every check in the code is got around:
      - post_id is the primary key, so a post has at most one picture;
      - it points at a real post, and goes when its post's row is deleted
        (ON DELETE CASCADE);
      - kind is one of four words, so the server can only ever send one of
        the four picture types;
      - the bytes are bytes (a BLOB), 12 bytes to 2 MB (MAX_PICTURE_BYTES; a
        test checks that the two numbers agree);
      - the description is 1 to 200 characters (MAX_ALT_TEXT).
    """
    connection.execute("BEGIN")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS pictures ("
        "post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE, "
        "kind TEXT NOT NULL CHECK (kind IN ('png', 'jpeg', 'gif', 'webp')), "
        "alt_text TEXT NOT NULL CHECK (length(alt_text) BETWEEN 1 AND 200), "
        "bytes BLOB NOT NULL CHECK (typeof(bytes) = 'blob' "
        "AND length(bytes) BETWEEN 12 AND 2097152))")
    connection.execute("PRAGMA user_version = 7")
    connection.commit()


def upgrade_to_block(connection):
    """Version 8: the blocks table. Every row is kept.

    One row means "this person blocked that person". Unblocking deletes the
    row; nothing is marked. A block points at a user by id, never by name.
    """
    connection.execute("BEGIN")
    connection.execute("CREATE TABLE IF NOT EXISTS blocks ("
                       # the person who pressed Block
                       "blocker_id INTEGER NOT NULL REFERENCES users(id), "
                       # the person they blocked
                       "blocked_id INTEGER NOT NULL REFERENCES users(id), "
                       # The same block cannot be saved twice, even if two
                       # presses arrive at the same moment.
                       "PRIMARY KEY (blocker_id, blocked_id), "
                       # A CHECK is a rule the database tests on every row it
                       # saves: nobody can block themselves, even if the model
                       # is got around.
                       "CHECK (blocker_id <> blocked_id))")
    connection.execute("PRAGMA user_version = 8")
    connection.commit()


def upgrade_to_replies(connection):
    """Version 9: a post can answer another post. Every row is kept.

    posts.parent_id is the id of the post a reply answers, just as author_id
    points at a user. A normal post, and every old post, has NULL there, so no
    old row changes. Adding a column with an empty value needs no rebuild.

    - REFERENCES posts(id) is a foreign key: the database refuses a reply to a
      post that does not exist, and refuses deleting a post that has replies.
    - posts_by_parent is an index (a sorted list the database keeps), so finding
      the replies of one post is fast.
    - replies_are_one_level is a trigger: a rule the database runs by itself
      before each new post. It refuses a reply to a reply, even if the check in
      save_reply is got around.
    A reply count is never kept: it is counted from the rows each time.
    """
    connection.execute("BEGIN")
    try:
        # Only if it is not there yet, so running this twice is harmless.
        columns = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
        if "parent_id" not in columns:
            connection.execute("ALTER TABLE posts ADD COLUMN parent_id INTEGER "
                               "REFERENCES posts(id)")
        connection.execute("CREATE INDEX IF NOT EXISTS posts_by_parent ON posts (parent_id)")
        connection.execute("CREATE TRIGGER IF NOT EXISTS replies_are_one_level "
                           "BEFORE INSERT ON posts "
                           "WHEN NEW.parent_id IS NOT NULL "
                           "AND (SELECT parent_id FROM posts WHERE id = NEW.parent_id) IS NOT NULL "
                           "BEGIN SELECT RAISE(ABORT, 'A reply cannot be answered.'); END")
        connection.execute("PRAGMA user_version = 9")
        connection.commit()
    except BaseException:
        connection.rollback()   # nothing is half done
        raise


def upgrade_to_edit_delete(connection):
    """Version 10: edit and delete. Every row is kept.

    No table is rebuilt: groundwork already gave posts.id AUTOINCREMENT, so the
    id of a deleted post is never given to a new one.

    - posts gets deleted_at: empty (NULL) for a normal post. A deleted post that
      has replies keeps its row, so its replies stay under it; deleted_at is
      then the time it was deleted (UTC text). Its text is "" and its place
      NULL: the CHECK makes the database refuse a deleted post that still has
      words.
    - post_versions: the earlier words of each edited post, and when they were
      replaced. ON DELETE CASCADE: when a post goes, its versions go too.
    - changes: one row for each "this post changed". No foreign key: a deleted
      post is gone, and its change must stay so that open windows hear about
      it. AUTOINCREMENT, so a change id is never given twice.
    """
    connection.execute("BEGIN")
    try:
        columns = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
        if "deleted_at" not in columns:
            connection.execute(
                "ALTER TABLE posts ADD COLUMN deleted_at TEXT "
                "CHECK (deleted_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T"
                "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z') "
                "CHECK (deleted_at IS NULL OR (text = '' AND place IS NULL))")
        connection.execute("CREATE TABLE IF NOT EXISTS post_versions ("
                           "id INTEGER PRIMARY KEY, "
                           "post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, "
                           "text TEXT NOT NULL, "
                           "replaced_at TEXT NOT NULL)")   # UTC text, like posted_at
        connection.execute("CREATE INDEX IF NOT EXISTS post_versions_by_post "
                           "ON post_versions (post_id)")
        connection.execute("CREATE TABLE IF NOT EXISTS changes ("
                           "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                           "post_id INTEGER NOT NULL, "
                           "kind TEXT NOT NULL, "            # one of CHANGE_KINDS
                           "changed_at TEXT NOT NULL)")      # UTC text, like posted_at
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
    except BaseException:
        connection.rollback()   # nothing is half done
        raise


def upgrade_to_report(connection):
    """Version 11: the reports table. Every row in every other table is kept.

    One row for each person who reported each post. There is no "hidden"
    column anywhere: a post is hidden when it has HIDE_AFTER_REPORTS rows here,
    and that is counted every time (see not_hidden_sql).
    """
    connection.execute("BEGIN")
    try:
        # PRIMARY KEY (post_id, user_id): one report per person per post. The
        # database refuses a second one, even if every check in the code is got
        # around. post_id comes first, so counting one post's reports is fast.
        # ON DELETE CASCADE: when a post goes, its reports go with it.
        # The CHECK: the database refuses a reason over 200 characters too.
        connection.execute("CREATE TABLE IF NOT EXISTS reports ("
                           "post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, "
                           "user_id INTEGER NOT NULL REFERENCES users(id), "
                           "reason TEXT CHECK (reason IS NULL OR length(reason) <= 200), "
                           "PRIMARY KEY (post_id, user_id))")
        connection.execute("PRAGMA user_version = 11")
        connection.commit()
    except BaseException:
        connection.rollback()   # nothing is half done
        raise


# report: a post is hidden from everyone but its author when this many
# different people have reported it. Counted from the rows in reports every
# time, never kept as a flag (see not_hidden_sql).
HIDE_AFTER_REPORTS = 3


# Each post, with its author's two names looked up in users, and how many people
# have liked it. The view reads row["author"], row["display_name"] and row["like_count"].
# picture_alt is the description of the post's picture, or NULL when it has none
# (a description is never empty). The picture's bytes are never read here.
POSTS_WITH_AUTHORS = ("SELECT posts.id, users.name AS author, users.display_name, "
                      "posts.text, posts.posted_at, posts.old_clock_time, posts.place, "
                      "(SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) "
                      "AS like_count, "
                      "(SELECT alt_text FROM pictures WHERE pictures.post_id = posts.id) "
                      "AS picture_alt, "
                      # replies (see VISIBLE_REPLIES below)
                      "posts.parent_id, "
                      "(SELECT parent_users.name FROM posts AS parents "
                      "JOIN users AS parent_users ON parent_users.id = parents.author_id "
                      "WHERE parents.id = posts.parent_id) AS parent_author, "
                      "(SELECT COUNT(*) FROM posts AS answers WHERE answers.parent_id = posts.id "
                      "AND /* visible replies */ 1 = 1) AS reply_count, "
                      "(SELECT MAX(answers.id) FROM posts AS answers "
                      "WHERE answers.parent_id = posts.id "
                      "AND /* visible replies */ 1 = 1) AS newest_reply_id, "
                      # edit-delete: both worked out, never stored as a yes/no. A
                      # post is edited exactly when it has an earlier version.
                      "EXISTS (SELECT 1 FROM post_versions "
                      "WHERE post_versions.post_id = posts.id) AS edited, "
                      "posts.deleted_at IS NOT NULL AS deleted, "
                      # report: worked out, never stored. Only the author is ever
                      # sent a hidden post, so only the author ever sees this true.
                      "(SELECT COUNT(*) FROM reports WHERE reports.post_id = posts.id) "
                      f">= {HIDE_AFTER_REPORTS} AS hidden_by_reports "
                      "FROM posts JOIN users ON users.id = posts.author_id")

# replies: parent_id is the post a reply answers (NULL for a normal post), and
# parent_author that post's account name, looked up in users, never copied into
# posts. reply_count is how many replies the post has, counted from the rows,
# never kept; newest_reply_id is the largest reply id in that count, so the page
# knows which replies it has already counted.
#
# Only the replies the viewer may see are counted: select_posts puts the
# viewer's visible_to condition in place of VISIBLE_REPLIES (visible_replies).
# As it is written here, VISIBLE_REPLIES is "1 = 1", so the text still works on
# its own (post_by_id uses it so, for the writer of a new post): every reply.
VISIBLE_REPLIES = "/* visible replies */ 1 = 1"


def check_name(name):
    """Return the account name without extra spaces, or raise RuleBroken."""
    name = name.strip() if isinstance(name, str) else ""
    if name == "":
        raise RuleBroken("name_empty")
    if len(name) > MAX_AUTHOR:
        raise RuleBroken("name_too_long", limit=MAX_AUTHOR)
    if not ACCOUNT_NAME.fullmatch(name):
        raise RuleBroken("name_characters")
    return name


def check_display_name(display_name):
    """Return the display name without extra spaces ("" if none), or raise RuleBroken."""
    display_name = display_name.strip() if isinstance(display_name, str) else ""
    if len(display_name) > MAX_DISPLAY_NAME:
        raise RuleBroken("display_name_too_long", limit=MAX_DISPLAY_NAME)
    if HIDDEN_CHARACTERS.search(display_name):
        raise RuleBroken("display_name_hidden")
    return display_name


# ---- pictures: the rules for a picture and its description ----

def picture_kind(data):
    """"png", "jpeg", "gif" or "webp", found from the first bytes, or None.

    Every kind of file starts with its own few bytes (its "magic number").
    Only these are read: the file's name and the type the browser says are
    never trusted.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    # A WAV sound file also starts with RIFF, so WEBP at bytes 8 to 11 is needed too.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def check_picture(encoded):
    """Return (kind, bytes) for a picture sent as base64 text, or raise RuleBroken."""
    if not isinstance(encoded, str):
        raise RuleBroken("picture_unreadable")
    # Base64 writes 3 bytes as 4 letters. Too long is refused before decoding,
    # so a huge text is never turned into bytes.
    if len(encoded) > (MAX_PICTURE_BYTES + 2) // 3 * 4:
        raise RuleBroken("picture_too_big", limit=MAX_PICTURE_MB)
    try:
        # validate=True: only base64 letters. A "data:image/png;base64," start
        # is refused; the page removes it before sending.
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise RuleBroken("picture_unreadable")
    if len(data) > MAX_PICTURE_BYTES:
        raise RuleBroken("picture_too_big", limit=MAX_PICTURE_MB)
    if len(data) < MIN_PICTURE_BYTES:
        raise RuleBroken("picture_unreadable")
    kind = picture_kind(data)
    if kind is None:
        raise RuleBroken("picture_wrong_kind")
    return kind, data


def check_alt_text(alt_text):
    """Return the picture's description without extra spaces, or raise RuleBroken."""
    alt_text = alt_text.strip() if isinstance(alt_text, str) else ""
    if alt_text == "":
        raise RuleBroken("picture_alt_empty")
    if len(alt_text) > MAX_ALT_TEXT:
        raise RuleBroken("picture_alt_too_long", limit=MAX_ALT_TEXT)
    if HIDDEN_CHARACTERS.search(alt_text):
        raise RuleBroken("picture_alt_hidden")
    return alt_text


def check_place(place):
    """Return the place without extra spaces, or None if there is no place. Or raise RuleBroken.

    A place that is not text (a number, a list) counts as no place. It may not
    hold a line break or a hidden character: it is shown on one line next to a
    name, and printed in the terminal.
    """
    place = place.strip() if isinstance(place, str) else ""
    if place == "":
        return None
    if len(place) > MAX_PLACE:
        raise RuleBroken("place_too_long", limit=MAX_PLACE)
    if HIDDEN_CHARACTERS.search(place):
        raise RuleBroken("place_hidden")
    return place


def check_password(password):
    """Return the password, or raise RuleBroken.

    A password is never trimmed: " secret" and "secret" are two passwords.
    """
    password = password if isinstance(password, str) else ""
    if len(password) < MIN_PASSWORD:
        raise RuleBroken("password_too_short", limit=MIN_PASSWORD)
    if len(password) > MAX_PASSWORD:
        raise RuleBroken("password_too_long", limit=MAX_PASSWORD)
    return password


def check_text(text):
    """Return the post's text without extra spaces, or raise RuleBroken."""
    text = text.strip() if isinstance(text, str) else ""
    if text == "":
        raise RuleBroken("text_empty")
    if len(text) > MAX_TEXT:
        raise RuleBroken("text_too_long", limit=MAX_TEXT)
    return text


def check_post_id(post_id):
    """Return the post id as a number, or raise RuleBroken."""
    try:
        return int(post_id)
    except (TypeError, ValueError):
        raise RuleBroken("like_post_id_missing")


def hash_password(password, salt, rounds):
    """The password, mixed with the salt and hashed `rounds` times, as hex text.

    The salt is different for every user, so two people with the same password
    get two different hashes, and a list of hashes made in advance is no use.
    """
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), rounds)
    return digest.hex()


def hash_token(token):
    """The hash of a session token, which is what the sessions table keeps.

    A token is 32 random bytes, far too many to guess, so it needs no salt and
    no rounds: one hash is enough to stop a copy of the file being used to log in.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clock():
    """The time now, in seconds. Only the rate limits use it.

    The tests put a fake clock here and move it forward, so they never wait
    for real. Sessions use time.time() instead, so moving the fake clock never
    ends a login.
    """
    return time.time()


def use_allowance(db_path, action, key):
    """Count one attempt at `action` by `key`, or raise TooFast if there have been too many.

    Call it after the other rules, so a mistake (an empty post, a bad name)
    never uses up the allowance. An attempt refused here is not counted.
    It opens its own connection, so the caller has nothing to close.
    """
    most, seconds = LIMITS[action]
    now = clock()
    connection = connect(db_path)
    try:
        # BEGIN IMMEDIATE takes the database's write lock at once, so two
        # requests at the same moment take turns. Without it, two posts sent
        # together could both count 4, and both be allowed.
        connection.execute("BEGIN IMMEDIATE")
        # Tidy up: a row older than the longest limit can never matter again.
        longest = max(window for _, window in LIMITS.values())
        connection.execute("DELETE FROM attempts WHERE at <= ?", (now - longest,))
        rows = connection.execute("SELECT at FROM attempts WHERE action = ? AND key = ? "
                                  "AND at > ? ORDER BY at", (action, key, now - seconds)).fetchall()
        if len(rows) >= most:
            connection.rollback()
            # The wait ends when the oldest counted attempt is `seconds` old.
            # Rounded up to whole seconds, and never less than 1.
            wait = max(1, math.ceil(rows[0]["at"] + seconds - now))
            raise TooFast(TOO_FAST[action], count=wait)
        connection.execute("INSERT INTO attempts (action, key, at) VALUES (?, ?, ?)",
                           (action, key, now))
        connection.commit()
    finally:
        connection.close()


def forget_attempts(db_path, action, key):
    """Delete every counted attempt at `action` by `key`. Used after a right password."""
    connection = connect(db_path)
    connection.execute("DELETE FROM attempts WHERE action = ? AND key = ?", (action, key))
    connection.commit()
    connection.close()


def account_for(connection, user_id):
    """The user's id and both names. Never anything about the password."""
    return connection.execute("SELECT id, name, display_name FROM users WHERE id = ?",
                              (user_id,)).fetchone()


def start_session(connection, user_id):
    """Save a new login for this user, and return its token for the cookie."""
    now = int(time.time())
    connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))   # tidy up old ones
    token = secrets.token_urlsafe(32)
    connection.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                       (hash_token(token), user_id, now + SESSION_DAYS * 24 * 60 * 60))
    return token


def create_account(db_path, name, display_name, password, address="local"):
    """Check the rules, make the account, log it in, and return (token, user).

    If an old user from before accounts has this name and no password, this
    claims it: the old row gets the password, and its old posts become this
    person's. A name that already has a password is taken.
    `address` is where the request came from: sign-ups are limited for each one.
    """
    name = check_name(name)
    display_name = check_display_name(display_name) or name
    password = check_password(password)
    use_allowance(db_path, "signup", address)   # before hashing, so a refusal costs nothing
    salt = secrets.token_bytes(16).hex()
    password_hash = hash_password(password, salt, PASSWORD_ROUNDS)
    connection = connect(db_path)
    # Claim an old name. One statement both looks and claims, so two people
    # signing up with the same old name at the same moment cannot both win.
    # rowcount is how many rows this UPDATE changed.
    cursor = connection.execute(
        "UPDATE users SET name = ?, display_name = ?, "
        "password_salt = ?, password_hash = ?, password_rounds = ? "
        "WHERE name = ? COLLATE NOCASE AND password_hash IS NULL",
        (name, display_name, salt, password_hash, PASSWORD_ROUNDS, name))
    if cursor.rowcount == 1:
        user_id = connection.execute("SELECT id FROM users WHERE name = ?",
                                     (name,)).fetchone()["id"]
    else:
        try:
            user_id = connection.execute(
                "INSERT INTO users (name, display_name, password_salt, password_hash, "
                "password_rounds) VALUES (?, ?, ?, ?, ?)",
                (name, display_name, salt, password_hash, PASSWORD_ROUNDS)).lastrowid
        except sqlite3.IntegrityError:
            # The name is taken, perhaps with other capital letters. The
            # database refused it, because of its UNIQUE index.
            connection.close()
            raise RuleBroken("name_taken")
    token = start_session(connection, user_id)
    connection.commit()
    user = account_for(connection, user_id)
    connection.close()
    return token, user


def log_in(db_path, name, password):
    """Check the name and password, log in, and return (token, user), or raise NotSignedIn."""
    name = name.strip() if isinstance(name, str) else ""
    password = password if isinstance(password, str) else ""
    if name == "" or len(name) > MAX_AUTHOR or len(password) > MAX_PASSWORD:
        raise NotSignedIn(WRONG_LOGIN)
    # Every try is counted as wrong until it is proved right, and it is counted
    # before any hashing. So a refused try costs the server nothing, and many
    # tries sent at once cannot slip past while the first is still hashing.
    # A name with no account is counted the same way: no hint that it exists.
    use_allowance(db_path, "login", name.lower())
    connection = connect(db_path)
    user = connection.execute("SELECT id, password_salt, password_hash, password_rounds "
                              "FROM users WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    # No such user, or an old user nobody has claimed: the same answer as a wrong password.
    if user is None or user["password_hash"] is None:
        connection.close()
        raise NotSignedIn(WRONG_LOGIN)
    attempt = hash_password(password, user["password_salt"], user["password_rounds"])
    # compare_digest takes as long for a near miss as for a far one, so the
    # time of the answer gives away nothing about the real hash.
    if not hmac.compare_digest(attempt, user["password_hash"]):
        connection.close()
        raise NotSignedIn(WRONG_LOGIN)
    forget_attempts(db_path, "login", name.lower())   # right at last: the count starts again
    token = start_session(connection, user["id"])
    connection.commit()
    account = account_for(connection, user["id"])
    connection.close()
    return token, account


def user_for_session(db_path, token):
    """The logged-in user (id and both names) this token belongs to, or raise NotSignedIn."""
    if not isinstance(token, str) or token == "":
        raise NotSignedIn("login_needed")
    connection = connect(db_path)
    user = connection.execute("SELECT users.id, users.name, users.display_name "
                              "FROM sessions JOIN users ON users.id = sessions.user_id "
                              "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                              (hash_token(token), int(time.time()))).fetchone()
    connection.close()
    if user is None:
        raise NotSignedIn("login_ended")
    return user


def log_out(db_path, token):
    """End this login. Like a like taken back, the row is deleted, not marked."""
    if not isinstance(token, str) or token == "":
        return
    connection = connect(db_path)
    connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),))
    connection.commit()
    connection.close()


# The extra columns insert_post may be given, besides the author and the text.
# A feature that adds a column to posts adds its name here, in one line (for
# example "place" or "parent_id"). A column name never comes from a request:
# only a name on this list can reach the SQL. old_clock_time is not on it:
# only the timestamps upgrade ever writes it.
POST_EXTRA_COLUMNS = ("posted_at", "place", "parent_id")


# A time is saved as text in UTC (the one clock the whole world agrees on), to
# the second: 2026-10-02T07:42:10Z. The Z means "this is UTC". As text it sorts
# in time order, and the page's new Date(...) reads it directly.
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now():
    """The time now, in UTC. The only place that reads the real clock for posts.

    A test can replace it (unittest.mock.patch("server.utc_now", ...)), so no
    test depends on the real clock.
    """
    return datetime.now(timezone.utc)


def utc_text(moment):
    """A time as it is saved: 2026-10-02T07:42:10Z. Any time zone is turned into UTC first.

    A time with no time zone cannot be placed honestly, so it is refused. That
    is a mistake in the code, not a user's broken rule.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("utc_text needs a time with a time zone, for example "
                         "datetime.now(timezone.utc).")
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def insert_post(connection, user_id, text, **more):
    """Add one post, and return its new id. The only place that adds a post.

    `more` is extra columns, by name, each one on POST_EXTRA_COLUMNS. It does
    not commit: the caller does, so a feature can add rows of its own in the
    same transaction.
    """
    for name in more:
        if name not in POST_EXTRA_COLUMNS:
            # A mistake in the code, not a user's broken rule.
            raise ValueError(f"insert_post does not know the column {name!r}. "
                             "Add it to POST_EXTRA_COLUMNS.")
    values = {"author_id": user_id, "text": text, "posted_at": utc_text(utc_now())}
    values.update(more)
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cursor = connection.execute(f"INSERT INTO posts ({columns}) VALUES ({marks})",
                                list(values.values()))
    return cursor.lastrowid


def post_by_id(connection, post_id):
    """One post, as GET /posts shows it, or None. With no visibility filter.

    Only for the person who just wrote it (see save_post). Every list of posts
    goes through select_posts instead.
    """
    return connection.execute(POSTS_WITH_AUTHORS + " WHERE posts.id = ?",
                              (post_id,)).fetchone()


def save_post(db_path, user_id, text, now=None, place=None, picture=None, picture_alt=None,
              parent_id=None):
    """Check the rules, save the post by this user, and return the saved row.

    The time comes from the server's clock (utc_now), never from the request.
    A test passes `now` to choose the time. `place` is optional (None: no place).

    picture is the picture as base64 text, and picture_alt its description.
    Both are left out (None) for a post with no picture. Every rule is checked
    first; then the post and its picture are saved in one transaction, so a
    broken rule saves nothing, and a post with a picture still counts as one post.

    parent_id is given only by save_reply, after its own rules (replies). A
    reply is a post, so it is counted by the same rate limit.
    """
    text = check_text(text)
    place = check_place(place)
    now = now or utc_now()
    if picture is None and picture_alt is None:
        kind = None
    elif picture is None:
        raise RuleBroken("picture_missing")
    else:
        kind, data = check_picture(picture)
        picture_alt = check_alt_text(picture_alt)

    use_allowance(db_path, "post", str(user_id))   # after the rules: an empty post is not counted
    connection = connect(db_path)
    reply = {} if parent_id is None else {"parent_id": parent_id}   # replies
    try:
        post_id = insert_post(connection, user_id, text, posted_at=utc_text(now), place=place,
                              **reply)
    except sqlite3.IntegrityError:
        connection.close()   # replies: the database refused it; save_reply says why
        raise
    if kind is not None:
        connection.execute("INSERT INTO pictures (post_id, kind, alt_text, bytes) "
                           "VALUES (?, ?, ?, ?)", (post_id, kind, picture_alt, data))
    connection.commit()
    row = post_by_id(connection, post_id)
    connection.close()
    return row


# ---- replies: a post that answers another post ----
#
# A reply is a post with a parent_id: the id of the post it answers. Only one
# level: a reply cannot be answered (the Reply button is only on posts that are
# not replies, and the database's trigger refuses it too). Replying to your own
# post is allowed. A reply follows the same rules as a post (text, place,
# picture), and is counted by the same rate limit, because save_post saves it.

def check_parent_id(parent_id):
    """Return the id of the post a reply answers, as a number, or raise RuleBroken.

    A whole number, or the same written as digits. Not true or false, not 2.5,
    not a list: only what the page itself sends.
    """
    if isinstance(parent_id, bool) or not isinstance(parent_id, (int, str)) \
            or not POST_ID_TEXT.fullmatch(str(parent_id).strip()):
        raise RuleBroken("reply_parent_id_missing")
    return int(parent_id)


def check_reply_parent(connection, parent_id, user_id):
    """Raise RuleBroken if this user may not answer the post parent_id.

    The post must exist, must not be a reply itself, and its author must not
    have blocked this user (block). Only reads. It does not close the
    connection: the caller does.
    """
    parent = connection.execute("SELECT parent_id, deleted_at FROM posts WHERE id = ?",
                                (parent_id,)).fetchone()
    if parent is None:
        raise RuleBroken("post_missing")
    if parent["parent_id"] is not None:
        raise RuleBroken("reply_to_reply")
    if parent["deleted_at"] is not None:   # edit-delete: kept only for its replies
        raise RuleBroken("reply_to_deleted")
    check_not_blocked_by_author(connection, parent_id, user_id, what="reply")   # block


def save_reply(db_path, user_id, text, parent_id, now=None, **more):
    """Check the rules, save a reply by this user to the post parent_id, and return the row.

    The rules first (the text, then which post), then save_post checks the
    rest and saves it, so a reply is counted as a post by the rate limit, and
    a refused reply is not. `more` is what save_post takes besides: place,
    picture, picture_alt.
    """
    text = check_text(text)
    parent_id = check_parent_id(parent_id)
    connection = connect(db_path)
    try:
        check_reply_parent(connection, parent_id, user_id)
    finally:
        connection.close()
    try:
        return save_post(db_path, user_id, text, now=now, parent_id=parent_id, **more)
    except sqlite3.IntegrityError:
        # The check above passed, but the database refused: the post was deleted
        # a moment ago (the foreign key), or the trigger refused it. Look again to say why.
        connection = connect(db_path)
        try:
            check_reply_parent(connection, parent_id, user_id)
        finally:
            connection.close()
        raise RuleBroken("post_missing")


def has_replies(connection, post_id):
    """True if any post answers this one. Only reads.

    edit-delete asks this before it deletes a post: a post with replies is kept
    (shown as deleted), because the database refuses to delete it.
    """
    return connection.execute("SELECT 1 FROM posts WHERE parent_id = ? LIMIT 1",
                              (post_id,)).fetchone() is not None


def visible_replies(viewer_id):
    """The condition that puts VISIBLE_REPLIES right for this viewer, as (sql, params).

    A reply ("answers") is counted only if it is a post this viewer may see:
    its id is among the posts visible_to allows. visible_to's text names
    posts and users, and inside this small SELECT those are the reply's own.
    """
    visible_sql, visible_params = visible_to(viewer_id)
    return ("answers.id IN (SELECT posts.id FROM posts JOIN users ON users.id = posts.author_id "
            "WHERE " + visible_sql + ")"), list(visible_params)


def like_count_for(connection, post_id):
    """How many people have liked this post."""
    row = connection.execute("SELECT COUNT(*) AS like_count FROM likes WHERE post_id = ?",
                             (post_id,)).fetchone()
    return row["like_count"]


def count_like(connection, db_path, user_id):
    """Use one of this user's likes for now, after the like's rules have passed.

    Liking and taking back share one count, so the heart cannot be flipped
    without end. If it is too fast, close the like's connection and raise TooFast.
    """
    try:
        use_allowance(db_path, "like", str(user_id))
    except TooFast:
        connection.close()
        raise


def add_like(db_path, user_id, post_id):
    """Save one like by this user, and return the post's id and its new count.

    The same person twice on one post is refused: first by the rule here, and
    in the end by the database itself, which will not keep two rows for the
    same pair.
    """
    post_id = check_post_id(post_id)
    connection = connect(db_path)
    # edit-delete: a post kept only for its replies has no words to like.
    if connection.execute("SELECT id FROM posts WHERE id = ? AND deleted_at IS NULL",
                          (post_id,)).fetchone() is None:
        connection.close()
        raise RuleBroken("post_missing")
    try:
        check_not_blocked_by_author(connection, post_id, user_id)   # block
    except RuleBroken:
        connection.close()
        raise
    already = connection.execute("SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?",
                                 (post_id, user_id)).fetchone()
    if already is not None:
        connection.close()
        raise RuleBroken("like_already")
    count_like(connection, db_path, user_id)
    try:
        connection.execute("INSERT INTO likes (post_id, user_id) VALUES (?, ?)",
                           (post_id, user_id))
    except sqlite3.IntegrityError:
        # Two likes arrived at the same moment, so the check above saw nothing
        # both times. The database kept the first row and refused this one.
        connection.close()
        raise RuleBroken("like_already")
    connection.commit()
    count = like_count_for(connection, post_id)
    connection.close()
    return post_id, count


def remove_like(db_path, user_id, post_id):
    """Take this user's like away, and return the post's id and its new count.

    A like is a row, so taking it back deletes the row. Nothing is marked, and
    no count is changed by hand: the count is read again from the rows that are
    left.
    """
    post_id = check_post_id(post_id)
    connection = connect(db_path)
    if connection.execute("SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?",
                          (post_id, user_id)).fetchone() is None:
        connection.close()
        raise RuleBroken("like_not_there")
    count_like(connection, db_path, user_id)
    # One statement both removes the like and says whether it was there, so
    # there is no gap between looking and deleting for a second request to
    # slip into. rowcount is how many rows this DELETE removed.
    cursor = connection.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?",
                                (post_id, user_id))
    if cursor.rowcount == 0:
        connection.close()
        raise RuleBroken("like_not_there")
    connection.commit()
    count = like_count_for(connection, post_id)
    connection.close()
    return post_id, count


def likes_for(db_path, user_id, from_id=0):
    """Return how many likes each post has, and which posts this user has liked.

    user_id is None for a window that is not logged in: it has liked nothing.
    from_id (timeline-flow) leaves out every post with a smaller id: a window
    asks only about the posts it shows. 0, the default, means every post.
    """
    from_id = check_id_bound(from_id, "from")
    connection = connect(db_path)
    counts = connection.execute("SELECT post_id, COUNT(*) AS like_count "
                                "FROM likes WHERE post_id >= ? GROUP BY post_id",
                                (from_id,)).fetchall()
    mine = []
    if user_id is not None:
        mine = connection.execute("SELECT post_id FROM likes WHERE user_id = ? "
                                  "AND post_id >= ? ORDER BY post_id",
                                  (user_id, from_id)).fetchall()
    connection.close()
    return counts, mine


# ---- who-liked: who liked a post, and the line under it ----
#
# Both functions below only read. They never add, change or delete a row, and
# never commit; they never make a user or a session. They name their columns
# (users.name, users.display_name), never users.*, so a password salt or hash
# can never reach an answer by accident.
#
# "Popular" means: how many likes this person's own posts have received from
# other people. It is counted from the rows in likes every time it is asked
# for, and never kept as a number anywhere, for the same reason as a like
# count: a kept number could drift away from the rows; a count of the rows
# cannot.

def who_liked(db_path, post_id, viewer_id=None):
    """Everyone who liked this post, A to Z, at most MAX_LIKERS of them.

    Returns (post_id, rows, like_count). Each row has name and display_name.
    like_count is how many liked it in all, which can be more than the rows.
    People the viewer blocked are left out of the rows, but still counted in
    like_count (block: a count is the same number for everyone).
    Only reads. MAX_LIKERS is read when it runs, so a test can lower it.
    """
    not_blocked, not_blocked_params = not_blocked_sql(viewer_id, "likes.user_id")
    post_id = check_post_id(post_id)
    connection = connect(db_path)
    try:
        # One read transaction, so the names and the count come from the same moment.
        connection.execute("BEGIN")
        if connection.execute("SELECT id FROM posts WHERE id = ?",
                              (post_id,)).fetchone() is None:
            raise RuleBroken("post_missing")
        rows = connection.execute(
            "SELECT users.name, users.display_name "
            "FROM likes JOIN users ON users.id = likes.user_id "
            "WHERE likes.post_id = ? AND " + not_blocked + " "
            "ORDER BY users.name COLLATE NOCASE "
            "LIMIT ?", (post_id, *not_blocked_params, MAX_LIKERS)).fetchall()
        like_count = like_count_for(connection, post_id)
    finally:
        connection.rollback()   # it only read, so there is nothing to keep
        connection.close()
    return post_id, rows, like_count


def check_post_ids(text):
    """The post ids in "3,7,9", as a list of whole numbers, or raise RuleBroken.

    The same id twice counts once. At most MAX_SUMMARY_POSTS different ids.
    """
    pieces = text.split(",") if isinstance(text, str) else []
    # Only the digits 0 to 9, at most 18 of them, so every id fits in the database.
    if not pieces or not all(POST_ID_TEXT.fullmatch(piece.strip()) for piece in pieces):
        raise RuleBroken("post_ids_missing")
    # dict.fromkeys keeps the first of each id, in order.
    post_ids = list(dict.fromkeys(int(piece) for piece in pieces))
    if len(post_ids) > MAX_SUMMARY_POSTS:
        raise RuleBroken("post_ids_too_many", limit=MAX_SUMMARY_POSTS)
    return post_ids


def like_summaries(db_path, viewer_id, post_ids):
    """The line under each post: {post_id: {"like_count", "you", "leaders"}}.

    viewer_id is None for a window that is not logged in. post_ids is the text
    from the request ("3,7,9"), checked by check_post_ids. Every asked id gets
    an entry; a post that does not exist has count 0 and no names.

    "leaders" are the most popular people who liked the post, most popular
    first, then A to Z. If the viewer liked it, "you" is true, the viewer is
    never a leader, and one name fewer is kept, so the line still has at most
    SUMMARY_NAMES names. So the model decides who is named; the page only
    words it. People the viewer blocked are never leaders, but are still in
    like_count (block). Only reads.
    """
    post_ids = check_post_ids(post_ids)
    not_blocked, not_blocked_params = not_blocked_sql(viewer_id, "likes.user_id")
    # The marks are made from the NUMBER of ids only. The ids themselves are
    # always passed as values, never written into the SQL.
    marks = ", ".join("?" * len(post_ids))
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")
        # ROW_NUMBER() OVER (PARTITION BY ...) numbers the likers of each post
        # 1, 2, 3... in popularity order, so place <= 2 keeps the top two of
        # every post in one query. "IS NOT ?" with None leaves everyone in.
        leaders = connection.execute(
            "SELECT post_id, name, display_name FROM ("
            "  SELECT likes.post_id, users.name, users.display_name,"
            "         ROW_NUMBER() OVER ("
            "           PARTITION BY likes.post_id"
            "           ORDER BY"
            # popularity: likes on this person's own posts, by other people
            "             (SELECT COUNT(*) FROM likes AS got"
            "              JOIN posts AS theirs ON theirs.id = got.post_id"
            "              WHERE theirs.author_id = users.id"
            "                AND got.user_id != users.id) DESC,"
            "             users.name COLLATE NOCASE"
            "         ) AS place"
            "  FROM likes JOIN users ON users.id = likes.user_id"
            f"  WHERE likes.post_id IN ({marks})"
            "    AND likes.user_id IS NOT ?"   # the viewer is "You", not a leader
            "    AND " + not_blocked +         # block: never someone the viewer blocked
            ") WHERE place <= ? "
            "ORDER BY post_id, place",
            (*post_ids, viewer_id, *not_blocked_params, SUMMARY_NAMES)).fetchall()
        counts = connection.execute(
            "SELECT post_id, COUNT(*) AS like_count FROM likes "
            f"WHERE post_id IN ({marks}) GROUP BY post_id", post_ids).fetchall()
        mine = set()
        if viewer_id is not None:
            mine = {row["post_id"] for row in connection.execute(
                f"SELECT post_id FROM likes WHERE user_id = ? AND post_id IN ({marks})",
                (viewer_id, *post_ids))}
    finally:
        connection.rollback()   # it only read, so there is nothing to keep
        connection.close()

    summaries = {post_id: {"like_count": 0, "you": post_id in mine, "leaders": []}
                 for post_id in post_ids}
    for row in counts:
        summaries[row["post_id"]]["like_count"] = row["like_count"]
    for row in leaders:
        summaries[row["post_id"]]["leaders"].append(row)
    for summary in summaries.values():
        names = SUMMARY_NAMES - 1 if summary["you"] else SUMMARY_NAMES
        summary["leaders"] = summary["leaders"][:names]
    return summaries


def visible_to(viewer_id):
    """Which posts this viewer may see, as (sql, params): one part of a WHERE.

    viewer_id is None for a window that is not logged in. A feature that hides
    posts (block, report) adds its own condition to this list, in one line,
    and then every list of posts obeys it. They are joined with AND.
    """
    conditions = [
        not_blocked_sql(viewer_id),   # block: not by someone the viewer blocked
        not_hidden_sql(viewer_id),    # report: not reported by HIDE_AFTER_REPORTS people
    ]
    sql = " AND ".join("(" + piece + ")" for piece, _ in conditions)
    params = [value for _, values in conditions for value in values]
    return sql, params


def select_posts(connection, conditions, params, viewer_id, order, limit=None):
    """Every post that matches all the conditions and that this viewer may see.

    The only place that reads a list of posts, so visible_to always applies.
    `conditions` is a list of SQL pieces with ? marks, and `params` their
    values, in order. `order` is the ORDER BY text, for example "posts.id".
    Both come from the code, never from a request. Everything is decided in
    the SQL, so a LIMIT of 20 really gives 20 posts.
    """
    visible_sql, visible_params = visible_to(viewer_id)
    where = " AND ".join("(" + condition + ")" for condition in list(conditions) + [visible_sql])
    columns = POSTS_WITH_AUTHORS
    # replies: count only the replies this viewer may see. The condition is in
    # the column list, before the WHERE, so its values come first.
    reply_sql, reply_params = visible_replies(viewer_id)
    sql = columns.replace(VISIBLE_REPLIES, reply_sql) + " WHERE " + where + " ORDER BY " + order
    values = (reply_params * columns.count(VISIBLE_REPLIES) + list(params)
              + list(visible_params))
    if limit is not None:
        sql += " LIMIT ?"
        values.append(int(limit))
    return connection.execute(sql, values).fetchall()


def posts_after(db_path, after, viewer_id=None):
    """Return every post with an id larger than `after` that this viewer may see, oldest first."""
    connection = connect(db_path)
    rows = select_posts(connection, ["posts.id > ?"], [after], viewer_id, "posts.id")
    connection.close()
    return rows


def picture_for(db_path, post_id, viewer_id=None):
    """The picture of this post, as a row with kind and bytes, or None.

    post_id is a number, never a path. None when the post does not exist, has
    no picture, or is one this viewer may not see: the post is looked for
    through select_posts, so visible_to applies here too. Only reads.
    """
    connection = connect(db_path)
    try:
        # One read transaction: the post and its picture from the same moment.
        connection.execute("BEGIN")
        if not select_posts(connection, ["posts.id = ?"], [post_id], viewer_id, "posts.id"):
            return None
        return connection.execute("SELECT kind, bytes FROM pictures WHERE post_id = ?",
                                  (post_id,)).fetchone()
    finally:
        connection.rollback()   # it only read, so there is nothing to keep
        connection.close()


# ---- search ----

def check_query(query):
    """Return the words of a search, as a list, or raise RuleBroken.

    Words are split at spaces (a Japanese full-width space too). A word that is
    a whole tag, such as "#cat", stays "#cat": search_posts then wants that tag,
    not only the letters. A lone "#" is an ordinary word.
    """
    query = query.strip() if isinstance(query, str) else ""
    if query == "":
        raise RuleBroken("search_empty")
    if len(query) > MAX_QUERY:
        raise RuleBroken("search_too_long", limit=MAX_QUERY)
    words = query.split()
    if len(words) > MAX_QUERY_WORDS:
        raise RuleBroken("search_too_many_words", limit=MAX_QUERY_WORDS)
    return words


def escape_like(word):
    r"""The word, ready to go inside a LIKE pattern.

    In LIKE, % means "any characters" and _ means "any one character". A \ in
    front makes each of them mean itself, and the SQL says ESCAPE '\'. The \
    itself is escaped first, so a \ typed in a search means a \.
    """
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def tags_in(text):
    """The set of tags in a text, in small letters, without the #: {"cat", "東京"}.

    #Cat and #cat are the same tag. links-and-tags may use this too.
    """
    return {tag.lower() for tag in TAG.findall(text or "")}


def has_tag(text, tag):
    """1 if the text holds this tag (without its #, in small letters), else 0.

    search_posts gives this function to SQLite, so the tag rule is checked
    inside the SQL. Then the LIMIT counts only posts that really have the tag.
    """
    return 1 if tag in tags_in(text) else 0


def search_posts(db_path, query, viewer_id=None):
    """The posts that hold every word of the search, newest first: (rows, more).

    At most SEARCH_LIMIT rows; `more` is True when there were more. A tag word
    (#cat) finds only that whole tag, so #cat does not find #catalog. Capital
    letters A to Z do not matter (LIKE works that way); everything else must
    match exactly. Every post goes through select_posts, so visible_to applies.
    Only reads: it never adds a user or changes a row.
    """
    words = check_query(query)
    # edit-delete: a post kept only for its replies has no words to find.
    conditions = ["posts.deleted_at IS NULL"]
    params = []
    for word in words:
        # The \ in ESCAPE '\' is one \ in the SQL. The word is a value (?),
        # never written into the SQL itself.
        conditions.append("posts.text LIKE ? ESCAPE '\\'")
        params.append("%" + escape_like(word) + "%")
        if TAG.fullmatch(word):
            conditions.append("has_tag(posts.text, ?)")
            params.append(word[1:].lower())
    connection = connect(db_path)
    try:
        # has_tag is a Python function that this connection's SQL may call.
        connection.create_function("has_tag", 2, has_tag, deterministic=True)
        # One more than the limit, only to learn whether there were more.
        rows = select_posts(connection, conditions, params, viewer_id, "posts.id DESC",
                            limit=SEARCH_LIMIT + 1)
    finally:
        connection.close()
    return rows[:SEARCH_LIMIT], len(rows) > SEARCH_LIMIT


# ---- timeline-flow: one page of older posts at a time ----

# How many posts one page has. The page has the same number (PAGE_SIZE in
# app.js) only to know when it has reached the end; a test checks they agree.
# The page cannot ask for more, so nobody can ask for a million posts at once.
PAGE_SIZE = 20


def check_id_bound(value, name):
    """Return `value` as a whole number, 0 or more, or raise RuleBroken.

    `name` is the name of the question in the address ("before", "from"), so
    the sentence says which one is wrong. "1.5", "-1", " 3" and "abc" are refused.
    """
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and POST_ID_TEXT.fullmatch(value):
        return int(value)
    raise RuleBroken("id_bound_not_number", name=name)


def posts_before(db_path, before, viewer_id=None):
    """Return at most PAGE_SIZE posts with an id smaller than `before`, newest first.

    `before` 0 means "from the very newest", the same way `after` 0 means
    "from the very first". A page is asked for by id, not by page number, so
    a new post that arrives between two pages cannot push a post into both.
    """
    before = check_id_bound(before, "before")
    conditions, params = [], []
    if before > 0:
        conditions, params = ["posts.id < ?"], [before]
    connection = connect(db_path)
    rows = select_posts(connection, conditions, params, viewer_id, "posts.id DESC",
                        limit=PAGE_SIZE)
    connection.close()
    return rows


# ---- edit-delete: change or delete your own post, and the changes feed ----
#
# Only the author may edit or delete a post. The page shows Edit and Delete
# only on your own posts, but the rule is here, in own_post: the database
# cannot check it, because it does not know who is asking.
#
# THE CHANGES FEED. Each edit or delete adds one row to `changes`, with
# record_change, in the same transaction as the change itself (so a change is
# recorded if and only if it really happened). Every open window asks
# GET /changes?after=<the newest change id it has seen> each second, before
# it asks for new posts. A change says only WHICH post changed; the answer
# pairs it with post_as_shown, the post as GET /posts would show it to this
# viewer right now, or None. So the page has one rule, whatever the kind: a
# post is there, draw it again; None, take it away.

def post_as_shown(connection, post_id, viewer_id=None):
    """The post as GET /posts would show it to this viewer right now, or None.

    The one place that says whether a single post is shown. It goes through
    select_posts, so visible_to applies (block and report change only that).
    """
    rows = select_posts(connection, ["posts.id = ?"], [post_id], viewer_id, "posts.id")
    return rows[0] if rows else None


def check_change_post_id(post_id):
    """The id of the post to edit, delete or read the versions of, as a number, or raise RuleBroken."""
    if isinstance(post_id, bool) or not isinstance(post_id, (int, str)) \
            or not POST_ID_TEXT.fullmatch(str(post_id).strip()):
        raise RuleBroken("post_id_missing")
    return int(post_id)


def own_post(connection, user_id, post_id):
    """The post's row, if this user wrote it and it is not deleted.

    Otherwise raise RuleBroken (no such post, or already deleted) or NotAllowed
    (someone else's). It only reads.
    """
    row = connection.execute("SELECT id, author_id, text, parent_id, deleted_at "
                             "FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        raise RuleBroken("post_missing")
    if row["deleted_at"] is not None:
        raise RuleBroken("post_deleted")
    if row["author_id"] != user_id:
        raise NotAllowed("post_not_yours")
    return row


def record_change(connection, post_id, kind):
    """Add one row to changes. It does not commit: it is part of the caller's transaction."""
    if kind not in CHANGE_KINDS:
        # A mistake in the code, not a user's broken rule.
        raise ValueError(f"record_change does not know the kind {kind!r}. "
                         "Add it to CHANGE_KINDS.")
    connection.execute("INSERT INTO changes (post_id, kind, changed_at) VALUES (?, ?, ?)",
                       (post_id, kind, utc_text(utc_now())))


def edit_post(db_path, user_id, post_id, text):
    """Give one of this user's posts new words, keep the old ones, and return the post.

    The new words follow the same rules as a new post (check_text). The post
    keeps its place in the timeline, its time, its likes and its replies.
    """
    post_id = check_change_post_id(post_id)
    text = check_text(text)
    connection = connect(db_path)
    try:
        # BEGIN IMMEDIATE takes the write lock at the start, so nobody can edit
        # or delete between "is it yours?" and the change itself.
        connection.execute("BEGIN IMMEDIATE")
        old = own_post(connection, user_id, post_id)
        if old["text"] == text:
            # So the list of earlier versions never has a step that changed nothing.
            raise RuleBroken("edit_unchanged")
        connection.execute("INSERT INTO post_versions (post_id, text, replaced_at) "
                           "VALUES (?, ?, ?)", (post_id, old["text"], utc_text(utc_now())))
        connection.execute("UPDATE posts SET text = ? WHERE id = ?", (text, post_id))
        record_change(connection, post_id, "edited")
        connection.commit()
        return post_as_shown(connection, post_id, user_id)
    except BaseException:
        connection.rollback()   # nothing is half done
        raise
    finally:
        connection.close()


def forget_post_details(connection, post_id):
    """Delete the rows that belong to one post: likes, earlier versions, picture, bookmarks, reports.

    Every table that points at posts is named here. (pictures, bookmarks and
    post_versions would go by themselves when the post's row goes, ON DELETE
    CASCADE, but a post kept for its replies keeps its row, so they are
    deleted here by hand, in one place.) It does not commit.
    """
    for table in ("likes", "post_versions", "pictures", "bookmarks", "reports"):
        connection.execute(f"DELETE FROM {table} WHERE post_id = ?", (post_id,))


def delete_post(db_path, user_id, post_id):
    """Delete one of this user's posts. Return (post_id, the post as now shown, or None).

    Its likes, earlier versions, picture and bookmarks are deleted too: no copy
    of its words stays. A post with replies keeps its row, with no words and no
    place, so its replies stay under it ("This post was deleted"); the
    database refuses to delete it anyway (replies' foreign key). A post with
    no replies is removed completely.

    A reply that is deleted changes its post's reply count, so the post gets a
    "replies_changed" change. If that post was itself deleted and this was its
    last reply, nothing is left to keep it for, and it is removed too.
    All of it is one transaction.
    """
    post_id = check_change_post_id(post_id)
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = own_post(connection, user_id, post_id)
        forget_post_details(connection, post_id)
        if has_replies(connection, post_id):
            connection.execute("UPDATE posts SET text = '', place = NULL, deleted_at = ? "
                               "WHERE id = ?", (utc_text(utc_now()), post_id))
        else:
            connection.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        record_change(connection, post_id, "deleted")
        parent_id = row["parent_id"]
        if parent_id is not None:
            parent = connection.execute("SELECT deleted_at FROM posts WHERE id = ?",
                                        (parent_id,)).fetchone()
            if parent["deleted_at"] is not None and not has_replies(connection, parent_id):
                connection.execute("DELETE FROM posts WHERE id = ?", (parent_id,))
                record_change(connection, parent_id, "deleted")
            else:
                record_change(connection, parent_id, "replies_changed")
        connection.commit()
        return post_id, post_as_shown(connection, post_id, user_id)
    except sqlite3.IntegrityError:
        # Another table still points at the post without ON DELETE: nothing changed.
        connection.rollback()
        raise RuleBroken("post_delete_refused")
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


# ---- report: three reports hide a post from everyone but its author ----
#
# A post is hidden when HIDE_AFTER_REPORTS different people have reported it.
# This is counted from the rows in reports every time, never kept as a flag,
# like a like count. So taking a report back shows the post again by itself,
# and changing the number applies to every post at once.

MAX_REASON = 200


def not_hidden_sql(viewer_id):
    """A piece of a WHERE, as (sql, params): the post has fewer than HIDE_AFTER_REPORTS reports.

    Its author still sees it. viewer_id is None for a window that is not
    logged in, and "author_id IS NULL" is never true, so that window does not.
    It is one line in visible_to, so every list of posts obeys it.
    """
    return ("(SELECT COUNT(*) FROM reports WHERE reports.post_id = posts.id) < ? "
            "OR posts.author_id IS ?", [HIDE_AFTER_REPORTS, viewer_id])


def report_count(connection, post_id):
    """How many people have reported this post. Counted, never stored."""
    return connection.execute("SELECT COUNT(*) FROM reports WHERE post_id = ?",
                              (post_id,)).fetchone()[0]


def check_reason(reason):
    """Return the reason without extra spaces, or None if there is none, or raise RuleBroken."""
    if reason is None:
        return None
    if not isinstance(reason, str):
        raise RuleBroken("report_reason_not_text")
    reason = reason.strip()
    if reason == "":
        return None
    if len(reason) > MAX_REASON:
        raise RuleBroken("report_reason_too_long", limit=MAX_REASON)
    return reason


def check_report_rules(connection, user_id, post_id):
    """Raise RuleBroken if this user may not report this post.

    The rules the database cannot hold: the post exists and is not deleted;
    it is not your own post; and you had posted before it (you have a post
    with a smaller id). The last rule stops the cheapest attack: making three
    new accounts now, to hide a post that is on the timeline now.
    """
    post = connection.execute("SELECT author_id FROM posts WHERE id = ? AND deleted_at IS NULL",
                              (post_id,)).fetchone()
    if post is None:
        raise RuleBroken("post_missing")
    if post["author_id"] == user_id:
        raise RuleBroken("report_own_post")
    earlier = connection.execute("SELECT 1 FROM posts WHERE author_id = ? AND id < ? LIMIT 1",
                                 (user_id, post_id)).fetchone()
    if earlier is None:
        raise RuleBroken("report_too_early")


def record_visibility_change(connection, post_id, before, after):
    """Tell open windows when a post crosses HIDE_AFTER_REPORTS, through the changes feed.

    `before` and `after` are its report counts. From under the limit to the
    limit: "hidden". From the limit to under it: "shown". Any other step (the
    first report, or the fourth) changes nothing anyone sees, so no change is
    written. Each window then gets the post as it would see it now
    (post_as_shown): null for everyone but the author, who keeps it. The
    change row is only news: whether a post is hidden is still counted.
    """
    if before < HIDE_AFTER_REPORTS <= after:
        record_change(connection, post_id, "hidden")
    elif after < HIDE_AFTER_REPORTS <= before:
        record_change(connection, post_id, "shown")


def add_report(db_path, user_id, post_id, reason=None):
    """Save one report by this user, and return the post's id.

    The same person twice on one post is refused: first by the look here, and
    in the end by the database itself (PRIMARY KEY), like a second like.
    """
    post_id = check_change_post_id(post_id)
    reason = check_reason(reason)
    connection = connect(db_path)
    try:
        # BEGIN IMMEDIATE takes the write lock at once, so the count before and
        # after this report cannot be changed by another report in between.
        connection.execute("BEGIN IMMEDIATE")
        check_report_rules(connection, user_id, post_id)
        if connection.execute("SELECT 1 FROM reports WHERE post_id = ? AND user_id = ?",
                              (post_id, user_id)).fetchone() is not None:
            raise RuleBroken("report_already")
        before = report_count(connection, post_id)
        try:
            connection.execute("INSERT INTO reports (post_id, user_id, reason) VALUES (?, ?, ?)",
                               (post_id, user_id, reason))
        except sqlite3.IntegrityError:
            raise RuleBroken("report_already")
        record_visibility_change(connection, post_id, before, before + 1)
        connection.commit()
    except BaseException:
        connection.rollback()   # nothing is half done
        raise
    finally:
        connection.close()
    return post_id


def remove_report(db_path, user_id, post_id):
    """Take this user's report back, and return the post's id.

    A report is a row, so taking it back deletes the row. If that brings the
    post under HIDE_AFTER_REPORTS, everyone sees it again, with no other code.
    """
    post_id = check_change_post_id(post_id)
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        before = report_count(connection, post_id)
        cursor = connection.execute("DELETE FROM reports WHERE post_id = ? AND user_id = ?",
                                    (post_id, user_id))
        if cursor.rowcount == 0:
            raise RuleBroken("report_not_there")
        record_visibility_change(connection, post_id, before, before - 1)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return post_id


def reports_for(db_path, user_id):
    """Three lists of post ids: (hidden, mine_hidden, reported).

    hidden: posts hidden from this viewer (other people's hidden posts).
    mine_hidden: this user's own posts that are hidden from others.
    reported: the posts this user has reported.
    The last two are empty when user_id is None. Never a count and never who
    reported: a count would say "one more and it is gone", and names would
    invite revenge. Only reads.
    """
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")   # one moment, so the three lists agree
        rows = connection.execute(
            "SELECT posts.id, posts.author_id FROM posts "
            "WHERE (SELECT COUNT(*) FROM reports WHERE reports.post_id = posts.id) >= ? "
            "ORDER BY posts.id", (HIDE_AFTER_REPORTS,)).fetchall()
        reported = []
        if user_id is not None:
            reported = [row["post_id"] for row in connection.execute(
                "SELECT post_id FROM reports WHERE user_id = ? ORDER BY post_id", (user_id,))]
    finally:
        connection.rollback()   # it only read, so there is nothing to keep
        connection.close()
    hidden = [row["id"] for row in rows if user_id is None or row["author_id"] != user_id]
    mine_hidden = [row["id"] for row in rows
                   if user_id is not None and row["author_id"] == user_id]
    return hidden, mine_hidden, reported


def changes_after(db_path, after, viewer_id=None):
    """Return (latest, rows): the newest change id, and every change after `after`.

    `after` is the text from the request, or None. None means "just tell me
    where the feed is": rows is empty. Each row is (change, post), oldest
    first, where post is post_as_shown for this viewer now, or None. Read in
    one transaction, so latest and the rows come from the same moment. Only reads.
    """
    if after is not None:
        after = check_id_bound(after, "after")
    connection = connect(db_path)
    try:
        connection.execute("BEGIN")
        latest = connection.execute("SELECT COALESCE(MAX(id), 0) FROM changes").fetchone()[0]
        rows = []
        if after is not None:
            for change in connection.execute("SELECT id, post_id, kind FROM changes "
                                             "WHERE id > ? ORDER BY id", (after,)).fetchall():
                rows.append((change, post_as_shown(connection, change["post_id"], viewer_id)))
    finally:
        connection.rollback()   # it only read, so there is nothing to keep
        connection.close()
    return latest, rows


def versions_of(db_path, post_id, viewer_id=None):
    """The earlier words of a post, oldest first: rows with text and replaced_at.

    Anyone may read them. A post that does not exist, or that this viewer may
    not see, has none. Only reads.
    """
    post_id = check_change_post_id(post_id)
    connection = connect(db_path)
    try:
        if post_as_shown(connection, post_id, viewer_id) is None:
            return []
        return connection.execute("SELECT text, replaced_at FROM post_versions "
                                  "WHERE post_id = ? ORDER BY id", (post_id,)).fetchall()
    finally:
        connection.close()


# ---- bookmarks: a post saved by one person, for that person only ----
#
# Like a like, a bookmark is one row, and taking it back deletes the row. Unlike
# a like, it is private: there is no count anywhere, and nothing here ever reads
# another person's bookmarks. Every function takes the user id the controller
# got from the session cookie. None of them takes a name, and none adds a user.

def check_bookmark_post_id(post_id):
    """Return the post id as a number, or raise RuleBroken."""
    try:
        return int(post_id)
    except (TypeError, ValueError):
        raise RuleBroken("bookmark_post_id_missing")


def add_bookmark(db_path, user_id, post_id):
    """Save one bookmark by this user, and return the post's id.

    The same post twice is refused: first by the rule here, and in the end by
    the database itself (PRIMARY KEY (user_id, post_id)).
    """
    post_id = check_bookmark_post_id(post_id)
    connection = connect(db_path)
    try:
        # edit-delete: a post kept only for its replies cannot be saved.
        if connection.execute("SELECT id FROM posts WHERE id = ? AND deleted_at IS NULL",
                              (post_id,)).fetchone() is None:
            raise RuleBroken("post_missing")
        if connection.execute("SELECT 1 FROM bookmarks WHERE user_id = ? AND post_id = ?",
                              (user_id, post_id)).fetchone() is not None:
            raise RuleBroken("bookmark_already")
        try:
            connection.execute("INSERT INTO bookmarks (user_id, post_id) VALUES (?, ?)",
                               (user_id, post_id))
        except sqlite3.IntegrityError:
            # Two presses at the same moment: the check above saw nothing both
            # times. The database kept the first row and refused this one.
            raise RuleBroken("bookmark_already")
        connection.commit()
    finally:
        connection.close()
    return post_id


def remove_bookmark(db_path, user_id, post_id):
    """Take this user's bookmark away, and return the post's id.

    The row is deleted, not marked. user_id is in the WHERE, so this can only
    ever delete the asking person's own row.
    """
    post_id = check_bookmark_post_id(post_id)
    connection = connect(db_path)
    try:
        cursor = connection.execute("DELETE FROM bookmarks WHERE user_id = ? AND post_id = ?",
                                    (user_id, post_id))
        if cursor.rowcount == 0:
            raise RuleBroken("bookmark_not_there")
        connection.commit()
    finally:
        connection.close()
    return post_id


def bookmarks_for(db_path, user_id):
    """This user's bookmarked posts, newest post first, as GET /posts shows them.

    Read through select_posts, so a post this user may not see (block, report)
    is left out here too.
    """
    connection = connect(db_path)
    rows = select_posts(connection,
                        ["posts.id IN (SELECT post_id FROM bookmarks WHERE user_id = ?)"],
                        [user_id], user_id, "posts.id DESC")
    connection.close()
    return rows


# ---- block: one person blocks another ----
#
# A block hides the blocked person's posts from the person who blocked them
# (through visible_to, so every list of posts obeys it: the timeline, older
# posts, search, bookmarks, pictures), and stops the blocked person liking
# (and later replying to) the blocker's posts. A blocked person can still read
# the blocker's posts: reading is open to everyone, even with no login, so
# hiding them would only be pretend.

def not_blocked_sql(viewer_id, column="posts.author_id"):
    """A piece of a WHERE, as (sql, params): `column` is nobody the viewer blocked.

    `column` names a user id column, and always comes from the code, never from
    a request. With no viewer (nobody logged in), nobody is left out.
    """
    if viewer_id is None:
        return "1 = 1", []
    return (column + " NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)",
            [viewer_id])


def find_account(connection, name):
    """The user with this account name (id, name, display_name), or raise RuleBroken.

    Capitals are ignored. It only reads: it never adds a user.
    """
    name = check_name(name)
    user = connection.execute("SELECT id, name, display_name FROM users "
                              "WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if user is None:
        raise RuleBroken("account_missing", name=name)
    return user


def add_block(db_path, blocker_id, name):
    """Save that this user blocked the account `name`. Return the blocked user.

    Blocking yourself, or the same person twice, is refused: first by the rules
    here, and in the end by the database itself (its CHECK and PRIMARY KEY).
    """
    connection = connect(db_path)
    try:
        blocked = find_account(connection, name)
        if blocked["id"] == blocker_id:
            raise RuleBroken("block_self")
        try:
            connection.execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
                               (blocker_id, blocked["id"]))
        except sqlite3.IntegrityError:
            raise RuleBroken("block_already", name=blocked["name"])
        connection.commit()
        return blocked
    finally:
        connection.close()


def remove_block(db_path, blocker_id, name):
    """Unblock the account `name`. Return that user.

    Like a like taken back: the row is deleted, not marked. One statement both
    deletes and says whether the row was there, so there is no gap between
    looking and deleting.
    """
    connection = connect(db_path)
    try:
        blocked = find_account(connection, name)
        cursor = connection.execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                                    (blocker_id, blocked["id"]))
        if cursor.rowcount == 0:
            raise RuleBroken("block_not_there", name=blocked["name"])
        connection.commit()
        return blocked
    finally:
        connection.close()


def blocks_for(db_path, blocker_id):
    """Everyone this user has blocked (name, display_name), A to Z. Only reads."""
    connection = connect(db_path)
    rows = connection.execute("SELECT users.name, users.display_name "
                              "FROM blocks JOIN users ON users.id = blocks.blocked_id "
                              "WHERE blocks.blocker_id = ? "
                              "ORDER BY users.name COLLATE NOCASE", (blocker_id,)).fetchall()
    connection.close()
    return rows


# What a blocked person was trying to do, and the code that refuses it.
# A blocked person can neither like nor reply to the blocker's posts.
BLOCKED_CODES = {"like": "like_blocked", "reply": "reply_blocked"}


def check_not_blocked_by_author(connection, post_id, user_id, what="like"):
    """Raise RuleBroken if the author of this post has blocked this user.

    `what` names what they were trying to do, a key in BLOCKED_CODES. It does
    not close the connection: the caller does.
    """
    BLOCKED_CODES[what]   # a name not in the table fails at once, blocked or not
    row = connection.execute("SELECT 1 FROM blocks "
                             "JOIN posts ON posts.author_id = blocks.blocker_id "
                             "WHERE posts.id = ? AND blocks.blocked_id = ?",
                             (post_id, user_id)).fetchone()
    if row is not None:
        raise RuleBroken(BLOCKED_CODES[what])


# ============================================================================
#  VIEW
#  Turns database rows into the JSON the page reads, and the cookie it keeps.
# ============================================================================

def post_to_json(row):
    return {"id": row["id"], "author": row["author"], "display_name": row["display_name"],
            "text": row["text"], "posted_at": row["posted_at"],
            "old_clock_time": row["old_clock_time"], "like_count": row["like_count"],
            "place": row["place"], "picture": picture_to_json(row),
            # replies: null, null, 0 and null for a post nobody answered.
            "parent_id": row["parent_id"], "parent_author": row["parent_author"],
            "reply_count": row["reply_count"], "newest_reply_id": row["newest_reply_id"],
            # edit-delete
            "edited": bool(row["edited"]), "deleted": bool(row["deleted"]),
            # report: true only on the author's own hidden post (nobody else gets it)
            "hidden_by_reports": bool(row["hidden_by_reports"])}


# edit-delete

def change_to_json(change, post_row):
    """One change: which post, what kind, and the post as now shown (or None)."""
    return {"id": change["id"], "post_id": change["post_id"], "kind": change["kind"],
            "post": post_to_json(post_row) if post_row is not None else None}


def changes_to_json(latest, rows):
    return {"latest": latest, "changes": [change_to_json(c, p) for c, p in rows]}


def report_to_json(post_id, reported):
    """report: the answer to a report, or to a report taken back."""
    return {"post_id": post_id, "reported": reported}


def reports_to_json(hidden, mine_hidden, reported):
    """report: the answer to GET /reports. Three lists of post ids, and no counts."""
    return {"hidden": hidden, "mine_hidden": mine_hidden, "reported": reported}


def deleted_to_json(post_id, post_row):
    """The answer to a delete: the post's id, and the post as now shown (None if gone)."""
    return {"post_id": post_id,
            "post": post_to_json(post_row) if post_row is not None else None}


def version_to_json(row):
    return {"text": row["text"], "replaced_at": row["replaced_at"]}


def versions_to_json(rows):
    return [version_to_json(row) for row in rows]


def picture_to_json(row):
    """The post's picture: its address and its description, or None if it has none.

    The page uses this address as it is, and never builds one itself.
    """
    if row["picture_alt"] is None:
        return None
    return {"url": "/pictures/" + str(row["id"]), "alt": row["picture_alt"]}


def posts_to_json(rows):
    return [post_to_json(row) for row in rows]


def search_to_json(rows, more):
    """A search answer: the posts, newest first, and whether there were more."""
    return {"posts": posts_to_json(rows), "more": more}


def problem_to_json(problem):
    """A refusal: the English sentence, its code, and the values that fill it in.

    The page shows the words for "code" in the reader's language. "error" is
    the English, for an older page, the terminal, and anyone using curl.
    """
    return {"error": str(problem), "code": problem.code, "values": problem.values}


def account_to_json(user):
    """Who is logged in: both names, and nothing about the password."""
    return {"account_name": user["name"], "display_name": user["display_name"]}


def like_to_json(post_id, like_count):
    return {"post_id": post_id, "like_count": like_count}


def bookmark_to_json(post_id, bookmarked):
    """The answer to a bookmark press. No count: nothing about anyone else."""
    return {"post_id": post_id, "bookmarked": bookmarked}


def blocks_to_json(rows):
    """Everyone this person has blocked: both names each, nothing else."""
    return {"blocked": [account_to_json(row) for row in rows]}


def too_fast_to_json(problem):
    """A 429 answer: the refusal, as every refusal is sent, and how many seconds to wait."""
    answer = problem_to_json(problem)
    answer["retry_after"] = problem.retry_after
    return answer


def likes_to_json(counts, mine):
    """The counts by post id, and the posts this user liked.

    A JSON name is always text, so the post ids in "counts" are text too.
    """
    return {"counts": {str(row["post_id"]): row["like_count"] for row in counts},
            "mine": [row["post_id"] for row in mine]}


def likers_to_json(post_id, rows, like_count):
    """Everyone who liked one post (at most MAX_LIKERS), and how many in all."""
    return {"post_id": post_id, "like_count": like_count,
            "likers": [account_to_json(row) for row in rows]}


def summaries_to_json(summaries):
    """The line under each post. A JSON name is always text, so the post ids are too."""
    return {"summaries": {str(post_id): {"like_count": s["like_count"], "you": s["you"],
                                         "leaders": [account_to_json(r) for r in s["leaders"]]}
                          for post_id, s in summaries.items()}}


def session_cookie(token):
    """The Set-Cookie line that gives the browser its session token.

    HttpOnly: the page's JavaScript cannot read it, so a bad script cannot steal it.
    SameSite=Strict: the browser sends it only to requests made from this site.
    An empty token, with Max-Age=0, tells the browser to forget the cookie.
    """
    max_age = SESSION_DAYS * 24 * 60 * 60 if token else 0
    return (f"{SESSION_COOKIE}={token}; Max-Age={max_age}; Path=/; "
            "HttpOnly; SameSite=Strict")


def post_to_log_line(row):
    """One line for the terminal: when the post was written, who wrote it, and what it says.

    The text is shown in quotes, with a line break written as \\n, so a post
    can never make a second, fake line in the terminal.
    """
    text = json.dumps(row["text"], ensure_ascii=False)
    line = f"{row['posted_at']}  {row['display_name']} @{row['author']}: {text}"
    # A place can hold no line break (check_place), so it cannot fake a line.
    if row["place"]:
        line += f" · {row['place']}"
    return line


# ============================================================================
#  Starting the server
# ============================================================================

def make_server(port, db_path):
    create_tables(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), TimelineHandler)
    server.db_path = db_path
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Timeline server.")
    parser.add_argument("--port", type=int, default=8009)
    port = parser.parse_args().port
    server = make_server(port, DB_PATH)
    print("Timeline is running at http://localhost:" + str(port))
    print("The posts are kept in " + DB_PATH)
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    server.server_close()
