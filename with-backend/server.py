"""Timeline: the backend. Start it with `python3 server.py`, then open http://localhost:8009

This file has three parts:
  CONTROLLER  reads each request and decides what to do
  MODEL       the rules, and the database (six tables: users, posts, likes, sessions,
              attempts and bookmarks)
  VIEW        turns database rows into the JSON answer
The server never translates: a refusal names its rule by a code (see PROBLEMS),
and the page shows the words for that code in the reader's language (words.js).
It uses only the Python standard library, so there is nothing to install.
"""

import argparse
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
        elif url.path == "/bookmarks":
            self.show_bookmarks()
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
        if path not in ("/posts", "/likes", "/accounts", "/sessions", "/bookmarks"):
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
            row = save_post(self.server.db_path, user["id"], data.get("text"),
                            place=data.get("place"))
        except RuleBroken as problem:
            self.send_problem(400, problem)
            return
        self.send_json(201, post_to_json(row))
        print(post_to_log_line(row), flush=True)   # one line in the terminal for each new post

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
        """GET /likers?post_id=7: everyone who liked one post, A to Z. No cookie is read."""
        try:
            post_id, rows, like_count = who_liked(self.server.db_path, post_id)
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
                                      or self.path.startswith("/search")):
            return
        BaseHTTPRequestHandler.log_message(self, format, *args)


# ============================================================================
#  MODEL
#  The rules, and the database. Six tables: users (each person once, with
#  both names and a salted password hash), posts (each post points at its
#  author by the author's id), likes (one row for each person who liked each
#  post), sessions (one row for each window that is logged in), attempts
#  (for the rate limits) and bookmarks (one private row for each post a
#  person saved).
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
LATEST_VERSION = 6


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


# Each post, with its author's two names looked up in users, and how many people
# have liked it. The view reads row["author"], row["display_name"] and row["like_count"].
POSTS_WITH_AUTHORS = ("SELECT posts.id, users.name AS author, users.display_name, "
                      "posts.text, posts.posted_at, posts.old_clock_time, posts.place, "
                      "(SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) "
                      "AS like_count "
                      "FROM posts JOIN users ON users.id = posts.author_id")


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
POST_EXTRA_COLUMNS = ("posted_at", "place")


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


def save_post(db_path, user_id, text, now=None, place=None):
    """Check the rules, save the post by this user, and return the saved row.

    The time comes from the server's clock (utc_now), never from the request.
    A test passes `now` to choose the time. `place` is optional (None: no place).
    """
    text = check_text(text)
    place = check_place(place)
    now = now or utc_now()

    use_allowance(db_path, "post", str(user_id))   # after the rules: an empty post is not counted
    connection = connect(db_path)
    post_id = insert_post(connection, user_id, text, posted_at=utc_text(now), place=place)
    connection.commit()
    row = post_by_id(connection, post_id)
    connection.close()
    return row


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
    if connection.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone() is None:
        connection.close()
        raise RuleBroken("post_missing")
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

def who_liked(db_path, post_id):
    """Everyone who liked this post, A to Z, at most MAX_LIKERS of them.

    Returns (post_id, rows, like_count). Each row has name and display_name.
    like_count is how many liked it in all, which can be more than the rows.
    Only reads. MAX_LIKERS is read when it runs, so a test can lower it.
    """
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
            "WHERE likes.post_id = ? "
            "ORDER BY users.name COLLATE NOCASE "
            "LIMIT ?", (post_id, MAX_LIKERS)).fetchall()
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
    words it. Only reads.
    """
    post_ids = check_post_ids(post_ids)
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
            ") WHERE place <= ? "
            "ORDER BY post_id, place",
            (*post_ids, viewer_id, SUMMARY_NAMES)).fetchall()
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

    viewer_id is None for a window that is not logged in. Today every post is
    visible to everyone. A feature that hides posts (block, report) adds its
    own condition here, joined with AND, and then every list of posts obeys it.
    """
    return "1 = 1", []


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
    sql = POSTS_WITH_AUTHORS + " WHERE " + where + " ORDER BY " + order
    values = list(params) + list(visible_params)
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
    conditions = []
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
        if connection.execute("SELECT id FROM posts WHERE id = ?",
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


# ============================================================================
#  VIEW
#  Turns database rows into the JSON the page reads, and the cookie it keeps.
# ============================================================================

def post_to_json(row):
    return {"id": row["id"], "author": row["author"], "display_name": row["display_name"],
            "text": row["text"], "posted_at": row["posted_at"],
            "old_clock_time": row["old_clock_time"], "like_count": row["like_count"],
            "place": row["place"]}


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
