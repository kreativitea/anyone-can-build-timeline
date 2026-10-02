"""Timeline: the backend. Start it with `python3 server.py`, then open http://localhost:8009

This file has three parts:
  CONTROLLER  reads each request and decides what to do
  MODEL       the rules, and the database (four tables: users, posts, likes and sessions)
  VIEW        turns database rows into the JSON answer
It uses only the Python standard library, so there is nothing to install.
"""

import argparse
import hashlib
import hmac
import http.cookies
import json
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
            try:
                after = int(parse_qs(url.query).get("after", ["0"])[0])
            except ValueError:
                self.send_json(400, {"error": "'after' must be a whole number."})
                return
            # Who is asking decides which posts they may see (see visible_to).
            # Anyone may read, so nobody logged in is fine: the viewer is None.
            viewer = self.user_or_none()
            rows = posts_after(self.server.db_path, after, viewer["id"] if viewer else None)
            self.send_json(200, posts_to_json(rows))
        elif url.path == "/likes":
            # A like changes no post, so a window asks for the counts separately.
            # Anyone may read the counts; "mine" is empty for a window not logged in.
            user = self.user_or_none()
            counts, mine = likes_for(self.server.db_path, user["id"] if user else None)
            self.send_json(200, likes_to_json(counts, mine))
        elif url.path == "/likers":
            self.show_likers(parse_qs(url.query).get("post_id", [None])[0])
        elif url.path == "/likesummary":
            self.show_like_summaries(parse_qs(url.query).get("post_ids", [""])[0])
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
                self.send_json(404, {"error": "The file " + file_name + " is missing."})
        else:
            self.send_nothing_here("GET", url.path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/posts", "/likes", "/accounts", "/sessions"):
            self.send_nothing_here("POST", path)
            return
        data = self.read_json()
        if data is None:
            return
        if path == "/accounts":
            self.sign_up(data)
        elif path == "/sessions":
            self.log_in(data)
        elif path == "/likes":
            self.take_like(data)
        else:
            self.take_post(data)

    def do_DELETE(self):
        # The method says what happens: POST adds a like or a session, and
        # DELETE takes one away.
        path = urlparse(self.path).path
        if path == "/sessions":
            log_out(self.server.db_path, self.session_token())
            self.send_json(200, {}, cookie=session_cookie(""))
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
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(200, like_to_json(post_id, like_count))   # 200: nothing was created

    def read_json(self):
        """The JSON object sent with this request, or None if it was not JSON."""
        # Only a request that says it is JSON. A form on another website can
        # send plain text to this server, but it cannot send JSON without the
        # server agreeing first, and this server never agrees. So another site
        # cannot use a logged-in person's cookie to post as them.
        if self.headers.get_content_type() != "application/json":
            self.send_json(400, {"error": "The request must be JSON."})
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = None   # not a number: refused as "not JSON" just below
        # Too big: refused before it is read, so a huge request cannot fill the
        # server's memory. The size comes from the Content-Length header.
        if length is not None and length > MAX_REQUEST_BYTES:
            self.send_json(413, {"error": "The request is too big."})
            return None
        try:
            if length is None:
                raise ValueError("Content-Length is not a number")
            data = json.loads(self.rfile.read(length))
        except ValueError:
            self.send_json(400, {"error": "The request must be JSON."})
            return None
        if not isinstance(data, dict):
            self.send_json(400, {"error": "The request must be a JSON object."})
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
            self.send_json(401, {"error": str(problem)})
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
                                         data.get("display_name"), data.get("password"))
        except RuleBroken as problem:
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(201, account_to_json(user), cookie=session_cookie(token))

    def log_in(self, data):
        try:
            token, user = log_in(self.server.db_path, data.get("account_name"),
                                 data.get("password"))
        except NotSignedIn as problem:
            self.send_json(401, {"error": str(problem)})
            return
        self.send_json(201, account_to_json(user), cookie=session_cookie(token))

    def take_post(self, data):
        user = self.signed_in_user()
        if user is None:
            return
        try:
            row = save_post(self.server.db_path, user["id"], data.get("text"))
        except RuleBroken as problem:
            self.send_json(400, {"error": str(problem)})
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
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(201, like_to_json(post_id, like_count))

    # who-liked: anyone may read who liked a post, signed in or not.

    def show_likers(self, post_id):
        """GET /likers?post_id=7: everyone who liked one post, A to Z. No cookie is read."""
        try:
            post_id, rows, like_count = who_liked(self.server.db_path, post_id)
        except RuleBroken as problem:
            self.send_json(400, {"error": str(problem)})
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
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(200, summaries_to_json(summaries))

    def send_nothing_here(self, method, path):
        """404, in one sentence for every method, so it stays true when routes are added."""
        self.send_json(404, {"error": f"There is nothing to {method} at {path}."})

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
        if self.command == "GET" and (self.path.startswith("/posts")
                                      or self.path.startswith("/likes")):
            return
        BaseHTTPRequestHandler.log_message(self, format, *args)


# ============================================================================
#  MODEL
#  The rules, and the database. Four tables: users (each person once, with
#  both names and a salted password hash), posts (each post points at its
#  author by the author's id), likes (one row for each person who liked each
#  post) and sessions (one row for each window that is logged in).
#  A new rule goes here, never in the controller or the view.
# ============================================================================

MAX_TEXT = 560
MAX_AUTHOR = 40
MAX_DISPLAY_NAME = 50
MIN_PASSWORD = 8
MAX_PASSWORD = 200

# who-liked
MAX_LIKERS = 50          # at most this many names in the full list; the total is sent too
SUMMARY_NAMES = 2        # names in the summary line ("Anika, Chika, and 10 others")
MAX_SUMMARY_POSTS = 100  # at most this many posts in one GET /likesummary
POST_ID_TEXT = re.compile(r"[0-9]{1,18}")   # one post id, as text

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

# One message for a wrong name and for a wrong password, so a stranger
# cannot use the login form to find out which account names exist.
WRONG_LOGIN = "The account name or password is wrong."


class RuleBroken(Exception):
    """A request broke one of the rules. The message says which rule."""


class NotSignedIn(Exception):
    """Nobody is logged in, or the login was wrong. The message says which."""


def connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row  # so a row can be read as row["author"]
    connection.execute("PRAGMA foreign_keys = ON")  # a post must point at a real user
    return connection


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


# Each post, with its author's two names looked up in users, and how many people
# have liked it. The view reads row["author"], row["display_name"] and row["like_count"].
POSTS_WITH_AUTHORS = ("SELECT posts.id, users.name AS author, users.display_name, "
                      "posts.text, posts.posted_at, posts.old_clock_time, "
                      "(SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) "
                      "AS like_count "
                      "FROM posts JOIN users ON users.id = posts.author_id")


def check_name(name):
    """Return the account name without extra spaces, or raise RuleBroken."""
    name = name.strip() if isinstance(name, str) else ""
    if name == "":
        raise RuleBroken("The name must not be empty.")
    if len(name) > MAX_AUTHOR:
        raise RuleBroken(f"The name must be {MAX_AUTHOR} characters or fewer.")
    if not ACCOUNT_NAME.fullmatch(name):
        raise RuleBroken("The account name may use only letters, numbers and _.")
    return name


def check_display_name(display_name):
    """Return the display name without extra spaces ("" if none), or raise RuleBroken."""
    display_name = display_name.strip() if isinstance(display_name, str) else ""
    if len(display_name) > MAX_DISPLAY_NAME:
        raise RuleBroken(f"The display name must be {MAX_DISPLAY_NAME} characters or fewer.")
    if HIDDEN_CHARACTERS.search(display_name):
        raise RuleBroken("The display name must not have hidden characters or line breaks.")
    return display_name


def check_password(password):
    """Return the password, or raise RuleBroken.

    A password is never trimmed: " secret" and "secret" are two passwords.
    """
    password = password if isinstance(password, str) else ""
    if len(password) < MIN_PASSWORD:
        raise RuleBroken(f"The password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise RuleBroken(f"The password must be {MAX_PASSWORD} characters or fewer.")
    return password


def check_text(text):
    """Return the post's text without extra spaces, or raise RuleBroken."""
    text = text.strip() if isinstance(text, str) else ""
    if text == "":
        raise RuleBroken("The post must not be empty.")
    if len(text) > MAX_TEXT:
        raise RuleBroken(f"The post must be {MAX_TEXT} characters or fewer.")
    return text


def check_post_id(post_id):
    """Return the post id as a number, or raise RuleBroken."""
    try:
        return int(post_id)
    except (TypeError, ValueError):
        raise RuleBroken("The like must say which post it is for.")


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


def create_account(db_path, name, display_name, password):
    """Check the rules, make the account, log it in, and return (token, user).

    If an old user from before accounts has this name and no password, this
    claims it: the old row gets the password, and its old posts become this
    person's. A name that already has a password is taken.
    """
    name = check_name(name)
    display_name = check_display_name(display_name) or name
    password = check_password(password)
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
            raise RuleBroken("That account name is taken.")
    token = start_session(connection, user_id)
    connection.commit()
    user = account_for(connection, user_id)
    connection.close()
    return token, user


def log_in(db_path, name, password):
    """Check the name and password, log in, and return (token, user), or raise NotSignedIn."""
    name = name.strip() if isinstance(name, str) else ""
    password = password if isinstance(password, str) else ""
    if name == "" or len(password) > MAX_PASSWORD:
        raise NotSignedIn(WRONG_LOGIN)
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
    token = start_session(connection, user["id"])
    connection.commit()
    account = account_for(connection, user["id"])
    connection.close()
    return token, account


def user_for_session(db_path, token):
    """The logged-in user (id and both names) this token belongs to, or raise NotSignedIn."""
    if not isinstance(token, str) or token == "":
        raise NotSignedIn("Please log in first.")
    connection = connect(db_path)
    user = connection.execute("SELECT users.id, users.name, users.display_name "
                              "FROM sessions JOIN users ON users.id = sessions.user_id "
                              "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                              (hash_token(token), int(time.time()))).fetchone()
    connection.close()
    if user is None:
        raise NotSignedIn("Your login has ended. Please log in again.")
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
POST_EXTRA_COLUMNS = ("posted_at",)


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


def save_post(db_path, user_id, text, now=None):
    """Check the rules, save the post by this user, and return the saved row.

    The time comes from the server's clock (utc_now), never from the request.
    A test passes `now` to choose the time.
    """
    text = check_text(text)
    now = now or utc_now()
    connection = connect(db_path)
    post_id = insert_post(connection, user_id, text, posted_at=utc_text(now))
    connection.commit()
    row = post_by_id(connection, post_id)
    connection.close()
    return row


def like_count_for(connection, post_id):
    """How many people have liked this post."""
    row = connection.execute("SELECT COUNT(*) AS like_count FROM likes WHERE post_id = ?",
                             (post_id,)).fetchone()
    return row["like_count"]


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
        raise RuleBroken("That post does not exist.")
    already = connection.execute("SELECT 1 FROM likes WHERE post_id = ? AND user_id = ?",
                                 (post_id, user_id)).fetchone()
    if already is not None:
        connection.close()
        raise RuleBroken("You have already liked that post.")
    try:
        connection.execute("INSERT INTO likes (post_id, user_id) VALUES (?, ?)",
                           (post_id, user_id))
    except sqlite3.IntegrityError:
        # Two likes arrived at the same moment, so the check above saw nothing
        # both times. The database kept the first row and refused this one.
        connection.close()
        raise RuleBroken("You have already liked that post.")
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
    # One statement both removes the like and says whether it was there, so
    # there is no gap between looking and deleting for a second request to
    # slip into. rowcount is how many rows this DELETE removed.
    cursor = connection.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?",
                                (post_id, user_id))
    if cursor.rowcount == 0:
        connection.close()
        raise RuleBroken("You have not liked that post.")
    connection.commit()
    count = like_count_for(connection, post_id)
    connection.close()
    return post_id, count


def likes_for(db_path, user_id):
    """Return how many likes each post has, and which posts this user has liked.

    user_id is None for a window that is not logged in: it has liked nothing.
    """
    connection = connect(db_path)
    counts = connection.execute("SELECT post_id, COUNT(*) AS like_count "
                                "FROM likes GROUP BY post_id").fetchall()
    mine = []
    if user_id is not None:
        mine = connection.execute("SELECT post_id FROM likes WHERE user_id = ? "
                                  "ORDER BY post_id", (user_id,)).fetchall()
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
            raise RuleBroken("That post does not exist.")
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
        raise RuleBroken("The request must say which posts it is about.")
    # dict.fromkeys keeps the first of each id, in order.
    post_ids = list(dict.fromkeys(int(piece) for piece in pieces))
    if len(post_ids) > MAX_SUMMARY_POSTS:
        raise RuleBroken(f"One request may ask about at most {MAX_SUMMARY_POSTS} posts.")
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


# ============================================================================
#  VIEW
#  Turns database rows into the JSON the page reads, and the cookie it keeps.
# ============================================================================

def post_to_json(row):
    return {"id": row["id"], "author": row["author"], "display_name": row["display_name"],
            "text": row["text"], "posted_at": row["posted_at"],
            "old_clock_time": row["old_clock_time"], "like_count": row["like_count"]}


def posts_to_json(rows):
    return [post_to_json(row) for row in rows]


def account_to_json(user):
    """Who is logged in: both names, and nothing about the password."""
    return {"account_name": user["name"], "display_name": user["display_name"]}


def like_to_json(post_id, like_count):
    return {"post_id": post_id, "like_count": like_count}


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
    return f"{row['posted_at']}  {row['display_name']} @{row['author']}: {text}"


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
