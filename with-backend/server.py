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
            rows = posts_after(self.server.db_path, after)
            self.send_json(200, posts_to_json(rows))
        elif url.path == "/likes":
            # A like changes no post, so a window asks for the counts separately.
            # Anyone may read the counts; "mine" is empty for a window not logged in.
            user = self.user_or_none()
            counts, mine = likes_for(self.server.db_path, user["id"] if user else None)
            self.send_json(200, likes_to_json(counts, mine))
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
            self.send_json(404, {"error": "There is nothing at " + url.path})

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/posts", "/likes", "/accounts", "/sessions"):
            self.send_json(404, {"error": "There is nothing to send to " + path})
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
            self.send_json(404, {"error": "You can only take back a like at /likes, "
                                          "or log out at /sessions"})
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

MAX_TEXT = 280
MAX_AUTHOR = 40
MAX_DISPLAY_NAME = 50
MIN_PASSWORD = 8
MAX_PASSWORD = 200

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


# Each post, with its author's two names looked up in users, and how many people
# have liked it. The view reads row["author"], row["display_name"] and row["like_count"].
POSTS_WITH_AUTHORS = ("SELECT posts.id, users.name AS author, users.display_name, "
                      "posts.text, posts.posted_at, "
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


def save_post(db_path, user_id, text):
    """Check the rules, save the post by this user, and return the saved row."""
    text = check_text(text)
    connection = connect(db_path)
    cursor = connection.execute(
        "INSERT INTO posts (author_id, text, posted_at) VALUES (?, ?, ?)",
        (user_id, text, time.strftime("%H:%M")))
    connection.commit()
    row = connection.execute(POSTS_WITH_AUTHORS + " WHERE posts.id = ?",
                             (cursor.lastrowid,)).fetchone()
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


def posts_after(db_path, after):
    """Return every post with an id larger than `after`, oldest first."""
    connection = connect(db_path)
    rows = connection.execute(POSTS_WITH_AUTHORS + " WHERE posts.id > ? ORDER BY posts.id",
                              (after,)).fetchall()
    connection.close()
    return rows


# ============================================================================
#  VIEW
#  Turns database rows into the JSON the page reads, and the cookie it keeps.
# ============================================================================

def post_to_json(row):
    return {"id": row["id"], "author": row["author"], "display_name": row["display_name"],
            "text": row["text"], "posted_at": row["posted_at"],
            "like_count": row["like_count"]}


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
