"""Timeline: the backend. Start it with `python3 server.py`, then open http://localhost:8009

This file has three parts:
  CONTROLLER  reads each request and decides what to do
  MODEL       the rules, and the database (three tables: users, posts and likes)
  VIEW        turns database rows into the JSON answer
It uses only the Python standard library, so there is nothing to install.
"""

import argparse
import json
import os
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


# ============================================================================
#  CONTROLLER
#  Reads the request. Picks what to do. Asks the model. Sends the answer.
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
            author = parse_qs(url.query).get("author", [""])[0]
            counts, mine = likes_for(self.server.db_path, author)
            self.send_json(200, likes_to_json(counts, mine))
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
        if path not in ("/posts", "/likes"):
            self.send_json(404, {"error": "You can send a post to /posts, or a like to /likes"})
            return
        data = self.read_json()
        if data is None:
            return
        if path == "/likes":
            self.take_like(data)
        else:
            self.take_post(data)

    def do_DELETE(self):
        # The page sends DELETE to take a like back: the method says what
        # happens, so POST adds a like and DELETE removes one.
        if urlparse(self.path).path != "/likes":
            self.send_json(404, {"error": "You can only take back a like at /likes"})
            return
        data = self.read_json()
        if data is None:
            return
        try:
            post_id, like_count = remove_like(self.server.db_path,
                                              data.get("author"), data.get("post_id"))
        except RuleBroken as problem:
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(200, like_to_json(post_id, like_count))   # 200: nothing was created

    def read_json(self):
        """The JSON object sent with this request, or None if it was not JSON."""
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

    def take_post(self, data):
        try:
            row = save_post(self.server.db_path, data.get("author"), data.get("text"))
        except RuleBroken as problem:
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(201, post_to_json(row))
        print(post_to_log_line(row), flush=True)   # one line in the terminal for each new post

    def take_like(self, data):
        try:
            post_id, like_count = add_like(self.server.db_path,
                                           data.get("author"), data.get("post_id"))
        except RuleBroken as problem:
            self.send_json(400, {"error": str(problem)})
            return
        self.send_json(201, like_to_json(post_id, like_count))

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_answer(status, "application/json; charset=utf-8", body)

    def send_answer(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
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
#  The rules a post must follow, and the database that keeps the posts.
#  Three tables: users (each person once), posts (each post points at its
#  author by the author's id) and likes (one row for each person who liked
#  each post). A new rule goes here, never in the controller or the view.
# ============================================================================

MAX_TEXT = 280
MAX_AUTHOR = 40


class RuleBroken(Exception):
    """A post broke one of the rules. The message says which rule."""


def connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row  # so a row can be read as row["author"]
    connection.execute("PRAGMA foreign_keys = ON")  # a post must point at a real user
    return connection


def create_tables(db_path):
    connection = connect(db_path)
    old = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
    if old and "author_id" not in old:
        connection.close()
        raise SystemExit("timeline.db was made by an older version of Timeline. "
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
    connection.close()


# Each post, with its author's name looked up in users, and how many people
# have liked it. The view reads row["author"] and row["like_count"].
POSTS_WITH_AUTHORS = ("SELECT posts.id, users.name AS author, posts.text, posts.posted_at, "
                      "(SELECT COUNT(*) FROM likes WHERE likes.post_id = posts.id) "
                      "AS like_count "
                      "FROM posts JOIN users ON users.id = posts.author_id")


def check_rules(author, text):
    """Return the author and text without extra spaces, or raise RuleBroken."""
    author = author.strip() if isinstance(author, str) else ""
    text = text.strip() if isinstance(text, str) else ""
    if author == "":
        raise RuleBroken("The name must not be empty.")
    if len(author) > MAX_AUTHOR:
        raise RuleBroken(f"The name must be {MAX_AUTHOR} characters or fewer.")
    if text == "":
        raise RuleBroken("The post must not be empty.")
    if len(text) > MAX_TEXT:
        raise RuleBroken(f"The post must be {MAX_TEXT} characters or fewer.")
    return author, text


def user_id_for(connection, name):
    """Return the id of the user with this name, adding the user the first time."""
    row = connection.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    return connection.execute("INSERT INTO users (name) VALUES (?)", (name,)).lastrowid


def save_post(db_path, author, text):
    """Check the rules, save the post, and return the saved row."""
    author, text = check_rules(author, text)
    connection = connect(db_path)
    author_id = user_id_for(connection, author)
    cursor = connection.execute(
        "INSERT INTO posts (author_id, text, posted_at) VALUES (?, ?, ?)",
        (author_id, text, time.strftime("%H:%M")))
    connection.commit()
    row = connection.execute(POSTS_WITH_AUTHORS + " WHERE posts.id = ?",
                             (cursor.lastrowid,)).fetchone()
    connection.close()
    return row


def check_like_rules(author, post_id):
    """Return the name without extra spaces and the post id as a number, or raise RuleBroken."""
    author = author.strip() if isinstance(author, str) else ""
    if author == "":
        raise RuleBroken("The name must not be empty.")
    if len(author) > MAX_AUTHOR:
        raise RuleBroken(f"The name must be {MAX_AUTHOR} characters or fewer.")
    try:
        post_id = int(post_id)
    except (TypeError, ValueError):
        raise RuleBroken("The like must say which post it is for.")
    return author, post_id


def like_count_for(connection, post_id):
    """How many people have liked this post."""
    row = connection.execute("SELECT COUNT(*) AS like_count FROM likes WHERE post_id = ?",
                             (post_id,)).fetchone()
    return row["like_count"]


def add_like(db_path, author, post_id):
    """Save one like, and return the post's id and its new count.

    There are no accounts, so a person is their name, as with a post. The same
    name twice on one post is refused: first by the rule here, and in the end by
    the database itself, which will not keep two rows for the same pair.
    """
    author, post_id = check_like_rules(author, post_id)
    connection = connect(db_path)
    if connection.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone() is None:
        connection.close()
        raise RuleBroken("That post does not exist.")
    user_id = user_id_for(connection, author)
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


def remove_like(db_path, author, post_id):
    """Take one like away, and return the post's id and its new count.

    A like is a row, so taking it back deletes the row. Nothing is marked, and
    no count is changed by hand: the count is read again from the rows that are
    left.
    """
    author, post_id = check_like_rules(author, post_id)
    connection = connect(db_path)
    # A plain SELECT, never user_id_for: taking a like back must not add a user.
    user = connection.execute("SELECT id FROM users WHERE name = ?", (author,)).fetchone()
    if user is None:
        connection.close()
        raise RuleBroken("You have not liked that post.")
    # One statement both removes the like and says whether it was there, so
    # there is no gap between looking and deleting for a second request to
    # slip into. rowcount is how many rows this DELETE removed.
    cursor = connection.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?",
                                (post_id, user["id"]))
    if cursor.rowcount == 0:
        connection.close()
        raise RuleBroken("You have not liked that post.")
    connection.commit()
    count = like_count_for(connection, post_id)
    connection.close()
    return post_id, count


def likes_for(db_path, author):
    """Return how many likes each post has, and which posts this name has liked."""
    connection = connect(db_path)
    counts = connection.execute("SELECT post_id, COUNT(*) AS like_count "
                                "FROM likes GROUP BY post_id").fetchall()
    name = author.strip() if isinstance(author, str) else ""
    mine = []
    if name != "":
        # Only a SELECT: asking about likes must never add a user.
        mine = connection.execute("SELECT likes.post_id FROM likes "
                                  "JOIN users ON users.id = likes.user_id "
                                  "WHERE users.name = ? ORDER BY likes.post_id",
                                  (name,)).fetchall()
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
#  Turns database rows into the JSON the page reads.
# ============================================================================

def post_to_json(row):
    return {"id": row["id"], "author": row["author"], "text": row["text"],
            "posted_at": row["posted_at"], "like_count": row["like_count"]}


def posts_to_json(rows):
    return [post_to_json(row) for row in rows]


def like_to_json(post_id, like_count):
    return {"post_id": post_id, "like_count": like_count}


def likes_to_json(counts, mine):
    """The counts by post id, and the posts this name liked.

    A JSON name is always text, so the post ids in "counts" are text too.
    """
    return {"counts": {str(row["post_id"]): row["like_count"] for row in counts},
            "mine": [row["post_id"] for row in mine]}


def post_to_log_line(row):
    """One line for the terminal: when the post was written, who wrote it, and what it says."""
    return f"{row['posted_at']}  {row['author']}: {row['text']}"


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
