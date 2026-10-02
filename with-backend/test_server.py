"""Tests for server.py. Run them with:  python3 -m unittest

Most tests call the MODEL directly, with a database made only for the test.
RealServerTest starts the real server and talks to it, as the page does.
JourneyTest walks one whole journey through all three levels at once: the
requests the page makes, the server that answers them, and the rows in the
database file.
PageAndServerAgreeTest reads app.js and checks the page and the server agree.
"""

import ast
import base64
import html.parser
import http.client
import http.cookiejar
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from unittest import mock

import server

HERE = os.path.dirname(os.path.abspath(server.__file__))

# A password for the tests. It is long enough, and easy to spot in a table.
PASSWORD = "correct horse battery"


ISO_TIME = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"   # 2026-10-02T07:42:10Z
# A fixed moment for the tests, so no test depends on the real clock.
SOME_MOMENT = datetime(2026, 10, 2, 7, 42, 10, tzinfo=timezone.utc)


def all_values_in(db_path):
    """Every value in every column of every table, as text. To look for a password."""
    connection = sqlite3.connect(db_path)
    tables = [row[0] for row in
              connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    values = []
    for table in tables:
        for row in connection.execute("SELECT * FROM " + table):
            values.extend(str(value) for value in row)
    connection.close()
    return values


class FakeClock:
    """A clock for the rate limits that moves only when a test moves it.

    So no test ever sleeps. The real server in RealServerTest and JourneyTest
    runs in a thread of this same process, so it sees the fake clock too.
    """

    def __init__(self):
        self.now = 1000000.0

    def __call__(self):
        return self.now

    def move(self, seconds):
        self.now += seconds


def use_fake_clock(test):
    """Put a FakeClock in place of server.clock for this one test, and return it."""
    fake = FakeClock()
    patcher = mock.patch.object(server, "clock", fake)
    patcher.start()
    test.addCleanup(patcher.stop)
    return fake


# ---- Reading words.js (japanese) ----
#
# words.js is JavaScript, but every entry has one fixed shape, so Python can
# read it with one regular expression (a pattern for finding text):
#
#   key: {
#     en: "English words.",
#     ja: "日本語",            <- from japanese Part B
#   },
WORD_ENTRY = re.compile(
    r'^  ([a-z][a-z0-9_]*): \{\n'
    r'    en: ("(?:[^"\\\n]|\\.)*"),\n'
    r'(?:    ja: ("(?:[^"\\\n]|\\.)*"),\n)?'
    r'  \},$', re.MULTILINE)

# A {name} inside a sentence: a value filled in later.
VALUE_NAME = re.compile(r"\{(\w+)\}")


# pictures: tiny pictures for the tests, written as bytes, so no test needs a
# real photo. Only the first bytes matter to the server; the PNG and the GIF
# are whole 1 x 1 pictures.
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a5c000"
                    "00000049454e44ae426082")
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
       b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88"
# Files that are not pictures. A WAV sound starts with RIFF, like a WebP.
NOT_PICTURES = {
    "text named cat.png": b"This is only text, in a file named cat.png.",
    "svg": b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    "html": b"<!DOCTYPE html><html><script>alert(1)</script></html>",
    "wav": b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00",
}


def as_base64(data):
    """Bytes written as base64 text, as the page sends a picture."""
    return base64.b64encode(data).decode("ascii")


def read_words():
    """words.js as (its text, the entries found in order, {key: {"en": ..., "ja": ...}})."""
    with open(os.path.join(HERE, "words.js"), encoding="utf-8") as words_file:
        text = words_file.read()
    found = WORD_ENTRY.findall(text)
    words = {}
    for key, en, ja in found:
        words[key] = {"en": json.loads(en)}
        if ja:
            words[key]["ja"] = json.loads(ja)
    return text, found, words


def value_names(sentence):
    """The {names} in a sentence, as a set."""
    return set(VALUE_NAME.findall(sentence))


class ModelTests(unittest.TestCase):

    def setUp(self):
        # A new, empty database for every test, in a temporary folder.
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "test.db")
        server.create_tables(self.db_path)

    def tearDown(self):
        self.folder.cleanup()

    # -- helpers --

    def sign_up(self, name, display_name="", password=PASSWORD):
        """Make an account. Return the new user's id."""
        token, user = server.create_account(self.db_path, name, display_name, password)
        return user["id"]

    def rows(self, sql, values=()):
        connection = server.connect(self.db_path)
        rows = [tuple(row) for row in connection.execute(sql, values).fetchall()]
        connection.close()
        return rows

    def users(self):
        return self.rows("SELECT name, display_name FROM users ORDER BY id")

    # -- the rules for a post --

    def test_empty_text_is_refused(self):
        aiko = self.sign_up("aiko")
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, aiko, "   ")

    def test_too_long_text_is_refused(self):
        aiko = self.sign_up("aiko")
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, aiko, "a" * (server.MAX_TEXT + 1))

    def test_text_of_exactly_the_limit_is_allowed(self):
        aiko = self.sign_up("aiko")
        row = server.save_post(self.db_path, aiko, "a" * server.MAX_TEXT)
        self.assertEqual(len(row["text"]), server.MAX_TEXT)

    def test_saved_post_comes_back_with_id_and_time(self):
        aiko = self.sign_up("aiko", "Aiko Tanaka")
        row = server.save_post(self.db_path, aiko, " the library is open late ")
        self.assertEqual(row["id"], 1)
        self.assertEqual(row["author"], "aiko")
        self.assertEqual(row["display_name"], "Aiko Tanaka")
        self.assertEqual(row["text"], "the library is open late")
        self.assertRegex(row["posted_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_post_points_at_its_author_by_id(self):
        aiko = self.sign_up("aiko", "Aiko Tanaka")
        server.save_post(self.db_path, aiko, "the library is open late tonight")
        post = self.rows("SELECT * FROM posts")[0]
        connection = server.connect(self.db_path)
        columns = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
        connection.close()
        self.assertEqual(post[1], aiko)   # author_id
        # Neither name is copied into posts: they are kept once, in users.
        self.assertNotIn("author", columns)
        self.assertNotIn("display_name", columns)

    def test_after_returns_only_newer_posts_oldest_first(self):
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        server.save_post(self.db_path, aiko, "first")
        server.save_post(self.db_path, ben, "second")
        server.save_post(self.db_path, aiko, "third")
        rows = server.posts_after(self.db_path, 1)
        self.assertEqual([row["text"] for row in rows], ["second", "third"])

    def test_two_people_may_share_a_display_name(self):
        self.sign_up("aiko", "Aiko")
        self.sign_up("aiko_t", "Aiko")
        self.assertEqual(self.users(), [("aiko", "Aiko"), ("aiko_t", "Aiko")])

    # -- likes: one per person, and taken back by deleting the row --

    def test_a_like_is_kept_as_one_row_and_counted(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        post_id, count = server.add_like(self.db_path, ben, post["id"])
        self.assertEqual((post_id, count), (post["id"], 1))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(post["id"], ben)])

    def test_the_same_person_cannot_like_the_same_post_twice(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, ben, post["id"])
        self.assertEqual(len(self.rows("SELECT * FROM likes")), 1)   # the database keeps only one

    def test_two_people_can_like_the_same_post(self):
        aiko, ben, chie = self.sign_up("aiko"), self.sign_up("ben"), self.sign_up("chie")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        post_id, count = server.add_like(self.db_path, chie, post["id"])
        self.assertEqual(count, 2)

    def test_the_same_person_can_like_two_different_posts(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        first = server.save_post(self.db_path, aiko, "first")
        second = server.save_post(self.db_path, aiko, "second")
        server.add_like(self.db_path, ben, first["id"])
        post_id, count = server.add_like(self.db_path, ben, second["id"])
        self.assertEqual(count, 1)

    def test_a_like_for_a_post_that_does_not_exist_is_refused(self):
        ben = self.sign_up("ben")
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, ben, 999)

    def test_a_like_without_a_post_id_is_refused(self):
        ben = self.sign_up("ben")
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, ben, None)

    def test_a_post_comes_back_with_its_like_count(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        self.assertEqual(server.post_to_json(post)["like_count"], 0)
        server.add_like(self.db_path, ben, post["id"])
        rows = server.posts_after(self.db_path, 0)
        self.assertEqual(server.post_to_json(rows[0])["like_count"], 1)

    def test_likes_for_gives_the_counts_and_this_person_s_own_likes(self):
        aiko, ben, chie = self.sign_up("aiko"), self.sign_up("ben"), self.sign_up("chie")
        first = server.save_post(self.db_path, aiko, "first")
        second = server.save_post(self.db_path, aiko, "second")
        server.add_like(self.db_path, ben, first["id"])
        server.add_like(self.db_path, chie, first["id"])
        server.add_like(self.db_path, chie, second["id"])
        answer = server.likes_to_json(*server.likes_for(self.db_path, chie))
        self.assertEqual(answer["counts"], {str(first["id"]): 2, str(second["id"]): 1})
        self.assertEqual(answer["mine"], [first["id"], second["id"]])
        answer = server.likes_to_json(*server.likes_for(self.db_path, ben))
        self.assertEqual(answer["mine"], [first["id"]])

    def test_nobody_logged_in_has_liked_nothing(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        answer = server.likes_to_json(*server.likes_for(self.db_path, None))
        self.assertEqual(answer, {"counts": {str(post["id"]): 1}, "mine": []})

    def test_a_like_taken_back_leaves_no_row(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        post_id, count = server.remove_like(self.db_path, ben, post["id"])
        self.assertEqual((post_id, count), (post["id"], 0))
        self.assertEqual(self.rows("SELECT * FROM likes"), [])   # the row is gone, not marked

    def test_taking_back_a_like_you_do_not_have_is_refused(self):
        aiko, ben, chie = self.sign_up("aiko"), self.sign_up("ben"), self.sign_up("chie")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        with self.assertRaises(server.RuleBroken):
            server.remove_like(self.db_path, chie, post["id"])

    def test_taking_back_a_like_twice_is_refused(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        server.remove_like(self.db_path, ben, post["id"])
        with self.assertRaises(server.RuleBroken):
            server.remove_like(self.db_path, ben, post["id"])

    def test_like_then_take_it_back_then_like_again(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        server.remove_like(self.db_path, ben, post["id"])
        post_id, count = server.add_like(self.db_path, ben, post["id"])
        self.assertEqual(count, 1)   # nothing was left behind to get in the way

    def test_taking_one_like_back_leaves_the_other_person_s(self):
        aiko, ben, chie = self.sign_up("aiko"), self.sign_up("ben"), self.sign_up("chie")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        server.add_like(self.db_path, chie, post["id"])
        post_id, count = server.remove_like(self.db_path, ben, post["id"])
        self.assertEqual(count, 1)
        answer = server.likes_to_json(*server.likes_for(self.db_path, chie))
        self.assertEqual(answer["mine"], [post["id"]])

    def test_liking_and_posting_never_add_a_user(self):
        # Only sign-up makes a user.
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        post = server.save_post(self.db_path, aiko, "hello")
        server.add_like(self.db_path, ben, post["id"])
        server.remove_like(self.db_path, ben, post["id"])
        server.likes_for(self.db_path, None)
        self.assertEqual(self.users(), [("aiko", "aiko"), ("ben", "ben")])

    # -- the log line in the terminal --

    def test_log_line_has_the_time_the_author_and_the_text_in_quotes(self):
        aiko = self.sign_up("aiko", "Aiko Tanaka")
        row = server.save_post(self.db_path, aiko, "the library is open late tonight",
                               now=datetime(2026, 10, 2, 7, 42, 10, tzinfo=timezone.utc))
        self.assertEqual(server.post_to_log_line(row),
                         '2026-10-02T07:42:10Z  Aiko Tanaka @aiko: "the library is open late tonight"')

    def test_a_line_break_in_a_post_cannot_make_a_second_log_line(self):
        aiko = self.sign_up("aiko")
        row = server.save_post(self.db_path, aiko, "hi\n12:00  Ben @ben: fake")
        line = server.post_to_log_line(row)
        self.assertNotIn("\n", line)
        self.assertIn('"hi\\n12:00  Ben @ben: fake"', line)

    # -- the rules for an account --

    def test_with_no_display_name_the_account_name_is_shown(self):
        self.sign_up("aiko", "   ")
        self.assertEqual(self.users(), [("aiko", "aiko")])

    def test_too_long_display_name_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            self.sign_up("aiko", "a" * 51)
        self.assertEqual(self.users(), [])

    def test_display_name_of_exactly_50_is_allowed(self):
        self.sign_up("aiko", "a" * 50)
        self.assertEqual(self.users(), [("aiko", "a" * 50)])

    def test_a_display_name_with_a_hidden_character_is_refused(self):
        # A line break, and the invisible mark that turns the text after it around.
        for display_name in ("Aiko\nBen", "Aiko\u202eokiA"):
            with self.subTest(display_name=display_name):
                with self.assertRaises(server.RuleBroken):
                    self.sign_up("aiko", display_name)
        self.assertEqual(self.users(), [])

    def test_an_account_name_that_is_not_one_word_is_refused(self):
        for name in ("Aiko Tanaka", "@aiko", "aiko!", "", "a" * 41):
            with self.subTest(name=name):
                with self.assertRaises(server.RuleBroken):
                    self.sign_up(name)
        self.assertEqual(self.users(), [])

    def test_a_name_that_differs_only_in_capitals_is_taken(self):
        self.sign_up("aiko")
        with self.assertRaises(server.RuleBroken) as caught:
            self.sign_up("Aiko")
        self.assertIn("taken", str(caught.exception))
        self.assertEqual(self.users(), [("aiko", "aiko")])

    def test_a_short_or_long_password_is_refused(self):
        for password in ("a" * 7, "a" * 201, None):
            with self.subTest(password=password):
                with self.assertRaises(server.RuleBroken):
                    self.sign_up("aiko", password=password)
        self.sign_up("aiko", password="a" * 8)   # exactly 8 is fine

    # -- passwords: only a salted hash is kept --

    def test_the_same_password_gives_two_different_hashes(self):
        self.sign_up("aiko", password=PASSWORD)
        self.sign_up("ben", password=PASSWORD)
        (salt1, hash1, rounds1), (salt2, hash2, rounds2) = self.rows(
            "SELECT password_salt, password_hash, password_rounds FROM users ORDER BY id")
        self.assertNotEqual(salt1, salt2)
        self.assertNotEqual(hash1, hash2)
        self.assertEqual((rounds1, rounds2), (server.PASSWORD_ROUNDS, server.PASSWORD_ROUNDS))

    def test_the_plain_password_is_in_no_table(self):
        token, user = server.create_account(self.db_path, "aiko", "", PASSWORD)
        server.log_in(self.db_path, "aiko", PASSWORD)
        values = all_values_in(self.db_path)
        self.assertTrue(values)
        for value in values:
            self.assertNotIn(PASSWORD, value)
            self.assertNotIn(token, value)   # nor the session token: only its hash

    def test_a_password_is_never_trimmed(self):
        self.sign_up("aiko", password=" " + PASSWORD + " ")
        with self.assertRaises(server.NotSignedIn):
            server.log_in(self.db_path, "aiko", PASSWORD)
        token, user = server.log_in(self.db_path, "aiko", " " + PASSWORD + " ")
        self.assertEqual(user["name"], "aiko")

    # -- logging in and out --

    def test_log_in_with_the_right_password(self):
        self.sign_up("aiko", "Aiko Tanaka")
        token, user = server.log_in(self.db_path, "AIKO", PASSWORD)   # capitals do not matter
        self.assertEqual((user["name"], user["display_name"]), ("aiko", "Aiko Tanaka"))
        self.assertEqual(server.user_for_session(self.db_path, token)["name"], "aiko")

    def test_a_wrong_name_and_a_wrong_password_get_the_same_message(self):
        self.sign_up("aiko")
        with self.assertRaises(server.NotSignedIn) as wrong_name:
            server.log_in(self.db_path, "nobody", PASSWORD)
        with self.assertRaises(server.NotSignedIn) as wrong_password:
            server.log_in(self.db_path, "aiko", "not the password")
        self.assertEqual(str(wrong_name.exception), str(wrong_password.exception))
        self.assertEqual(wrong_name.exception.code, server.WRONG_LOGIN)
        self.assertEqual(wrong_password.exception.code, server.WRONG_LOGIN)

    def test_no_token_is_not_signed_in(self):
        for token in ("", None, "made-up-token"):
            with self.subTest(token=token):
                with self.assertRaises(server.NotSignedIn):
                    server.user_for_session(self.db_path, token)

    def test_an_expired_session_is_refused(self):
        token, user = server.create_account(self.db_path, "aiko", "", PASSWORD)
        connection = server.connect(self.db_path)
        connection.execute("UPDATE sessions SET expires_at = 1")   # long ago, in 1970
        connection.commit()
        connection.close()
        with self.assertRaises(server.NotSignedIn):
            server.user_for_session(self.db_path, token)

    def test_log_out_deletes_the_row(self):
        token, user = server.create_account(self.db_path, "aiko", "", PASSWORD)
        self.assertEqual(len(self.rows("SELECT * FROM sessions")), 1)
        server.log_out(self.db_path, token)
        self.assertEqual(self.rows("SELECT * FROM sessions"), [])   # gone, not marked
        with self.assertRaises(server.NotSignedIn):
            server.user_for_session(self.db_path, token)

    def test_logging_out_one_window_leaves_the_other_logged_in(self):
        first, user = server.create_account(self.db_path, "aiko", "", PASSWORD)
        second, user = server.log_in(self.db_path, "aiko", PASSWORD)
        server.log_out(self.db_path, first)
        self.assertEqual(server.user_for_session(self.db_path, second)["name"], "aiko")

    # -- an older timeline.db, made before accounts: brought up to date, nothing lost --

    def use_an_old_database(self):
        """Build a version-0 database by hand, then let create_tables upgrade it.

        It has the three tables as they were before accounts, some rows, and
        user_version 0. Returns the rows as they were before the upgrade.
        """
        self.db_path = os.path.join(self.folder.name, "old.db")
        connection = sqlite3.connect(self.db_path)
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE posts (id INTEGER PRIMARY KEY,
                                author_id INTEGER NOT NULL REFERENCES users(id),
                                text TEXT NOT NULL, posted_at TEXT NOT NULL);
            CREATE TABLE likes (post_id INTEGER NOT NULL REFERENCES posts(id),
                                user_id INTEGER NOT NULL REFERENCES users(id),
                                PRIMARY KEY (post_id, user_id));
            INSERT INTO users VALUES (1, 'Aiko'), (2, 'Ben'), (3, 'Daniel Radcliffe');
            INSERT INTO posts VALUES (1, 1, 'first', '09:00'), (2, 2, 'second', '09:01'),
                                     (3, 3, 'third', '09:02');
            INSERT INTO likes VALUES (1, 2), (1, 3), (2, 1);
        """)
        connection.close()
        self.assertEqual(self.rows("PRAGMA user_version"), [(0,)])
        before = (self.rows("SELECT id, name FROM users ORDER BY id"),
                  self.rows("SELECT * FROM posts ORDER BY id"),
                  self.rows("SELECT * FROM likes ORDER BY post_id, user_id"))
        server.create_tables(self.db_path)
        return before

    def test_the_upgrade_keeps_every_row(self):
        users, posts, likes = self.use_an_old_database()
        self.assertEqual(self.rows("SELECT id, name FROM users ORDER BY id"), users)
        # timestamps moved the old HH:MM into old_clock_time.
        self.assertEqual(self.rows("SELECT id, author_id, text, old_clock_time FROM posts "
                                   "ORDER BY id"), posts)
        self.assertEqual(self.rows("SELECT * FROM likes ORDER BY post_id, user_id"), likes)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])

    def test_an_old_user_has_their_name_as_display_name_and_no_password(self):
        self.use_an_old_database()
        self.assertEqual(
            self.rows("SELECT name, display_name, password_hash FROM users ORDER BY id"),
            [("Aiko", "Aiko", None), ("Ben", "Ben", None),
             ("Daniel Radcliffe", "Daniel Radcliffe", None)])

    def test_nobody_can_log_in_as_an_old_user(self):
        self.use_an_old_database()
        for password in ("", PASSWORD):
            with self.assertRaises(server.NotSignedIn):
                server.log_in(self.db_path, "Aiko", password)

    def test_create_tables_twice_is_harmless(self):
        self.use_an_old_database()
        before = self.rows("SELECT * FROM users ORDER BY id")
        server.create_tables(self.db_path)
        self.assertEqual(self.rows("SELECT * FROM users ORDER BY id"), before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])

    def test_the_first_sign_up_with_an_old_name_claims_it_and_its_posts(self):
        self.use_an_old_database()
        # Capitals do not matter: "aiko" claims "Aiko", and the name is saved as typed now.
        token, user = server.create_account(self.db_path, "aiko", "Aiko Tanaka", PASSWORD)
        self.assertEqual(user["id"], 1)
        self.assertEqual(self.rows("SELECT id, name, display_name FROM users WHERE id = 1"),
                         [(1, "aiko", "Aiko Tanaka")])
        # Her old post and her old like are hers now.
        posts = server.posts_to_json(server.posts_after(self.db_path, 0))
        self.assertEqual((posts[0]["author"], posts[0]["display_name"]), ("aiko", "Aiko Tanaka"))
        answer = server.likes_to_json(*server.likes_for(self.db_path, user["id"]))
        self.assertEqual(answer["mine"], [2])
        self.assertEqual(len(self.rows("SELECT * FROM users")), 3)   # no new row was made

    def test_an_old_name_can_be_claimed_only_once(self):
        self.use_an_old_database()
        server.create_account(self.db_path, "aiko", "", PASSWORD)
        with self.assertRaises(server.RuleBroken):
            server.create_account(self.db_path, "AIKO", "", "another password")
        token, user = server.log_in(self.db_path, "aiko", PASSWORD)
        self.assertEqual(user["id"], 1)

    def test_an_old_name_with_a_space_can_never_be_claimed(self):
        self.use_an_old_database()
        with self.assertRaises(server.RuleBroken):
            server.create_account(self.db_path, "Daniel Radcliffe", "", PASSWORD)
        # Its post stays, with no owner.
        self.assertEqual(self.rows("SELECT name, password_hash FROM users WHERE id = 3"),
                         [("Daniel Radcliffe", None)])
        self.assertEqual(self.rows("SELECT text FROM posts WHERE author_id = 3"), [("third",)])

    # -- groundwork: one filter for every list, one place that adds a post --

    def test_posts_after_with_no_viewer_gives_what_it_gave_before(self):
        aiko, ben = self.sign_up("aiko"), self.sign_up("ben")
        for text in ("first", "second", "third"):
            server.save_post(self.db_path, aiko, text)
        # The query posts_after ran before groundwork, written out by hand.
        before = self.rows(server.POSTS_WITH_AUTHORS + " WHERE posts.id > ? ORDER BY posts.id",
                           (1,))
        for viewer in (None, aiko, ben):
            with self.subTest(viewer=viewer):
                rows = server.posts_after(self.db_path, 1, viewer)
                self.assertEqual([tuple(row) for row in rows], before)
        self.assertEqual([tuple(row) for row in server.posts_after(self.db_path, 1)], before)

    def test_visible_to_allows_every_post(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "first")
        server.save_post(self.db_path, aiko, "second")
        for viewer in (None, aiko):
            with self.subTest(viewer=viewer):
                sql, params = server.visible_to(viewer)
                self.assertEqual(self.rows("SELECT id FROM posts WHERE " + sql, params),
                                 [(1,), (2,)])

    def test_insert_post_refuses_a_column_that_is_not_on_its_list(self):
        aiko = self.sign_up("aiko")
        connection = server.connect(self.db_path)
        for name in ("author_id", "old_clock_time", "text) VALUES (1, 'x', 'y'); --"):
            with self.subTest(column=name):
                with self.assertRaises(ValueError):
                    server.insert_post(connection, aiko, "hello", **{name: "x"})
        connection.commit()
        connection.close()
        self.assertEqual(self.rows("SELECT * FROM posts"), [])

    def test_a_post_id_is_never_given_out_twice(self):
        aiko = self.sign_up("aiko")
        for text in ("first", "second", "third"):
            server.save_post(self.db_path, aiko, text)
        connection = server.connect(self.db_path)
        connection.execute("DELETE FROM posts WHERE id = 3")
        connection.commit()
        connection.close()
        row = server.save_post(self.db_path, aiko, "fourth")
        # Without AUTOINCREMENT this would be 3 again, and a window that had
        # already seen post 3 would never ask for it.
        self.assertEqual(row["id"], 4)

    def use_an_accounts_database(self):
        """Build a version-1 database (accounts, before groundwork) by hand, with rows."""
        self.db_path = os.path.join(self.folder.name, "accounts.db")
        connection = sqlite3.connect(self.db_path)
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                                display_name TEXT NOT NULL DEFAULT '', password_salt TEXT,
                                password_hash TEXT, password_rounds INTEGER);
            CREATE TABLE posts (id INTEGER PRIMARY KEY,
                                author_id INTEGER NOT NULL REFERENCES users(id),
                                text TEXT NOT NULL, posted_at TEXT NOT NULL);
            CREATE TABLE likes (post_id INTEGER NOT NULL REFERENCES posts(id),
                                user_id INTEGER NOT NULL REFERENCES users(id),
                                PRIMARY KEY (post_id, user_id));
            CREATE UNIQUE INDEX users_name_any_case ON users (name COLLATE NOCASE);
            CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,
                                   user_id INTEGER NOT NULL REFERENCES users(id),
                                   expires_at INTEGER NOT NULL);
            INSERT INTO users VALUES (1, 'aiko', 'Aiko Tanaka', 'aa', 'bb', 600000),
                                     (2, 'ben', 'Ben Ito', 'cc', 'dd', 600000);
            INSERT INTO posts VALUES (1, 1, 'first', '09:00'), (2, 2, 'second', '09:01'),
                                     (5, 1, 'fifth', '09:05');
            INSERT INTO likes VALUES (1, 2), (5, 1), (5, 2);
            INSERT INTO sessions VALUES ('hash-of-a-token', 2, 9999999999);
            PRAGMA user_version = 1;
        """)
        connection.close()
        tables = ("users", "posts", "likes", "sessions")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}
        server.create_tables(self.db_path)
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        return before, after

    def test_the_groundwork_upgrade_keeps_every_row(self):
        before, after = self.use_an_accounts_database()
        # timestamps then moved each old HH:MM from posted_at into old_clock_time.
        before["posts"] = [row[:3] + (None, row[3]) for row in before["posts"]]
        # Later upgrades (place) add columns after these five, empty for an old post.
        self.assertEqual([row[5:] for row in after["posts"]],
                         [(None,) * (len(row) - 5) for row in after["posts"]])
        after["posts"] = [row[:5] for row in after["posts"]]
        self.assertEqual(after, before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        # posts now has AUTOINCREMENT, and SQLite remembers the largest id it gave.
        posts_sql = self.rows("SELECT sql FROM sqlite_master WHERE name = 'posts'")[0][0]
        self.assertIn("AUTOINCREMENT", posts_sql)
        self.assertEqual(self.rows("SELECT seq FROM sqlite_sequence WHERE name = 'posts'"),
                         [(5,)])
        # The index from accounts is still there, and likes still points at posts.
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE type = 'index' "
                                   "AND name = 'users_name_any_case'"),
                         [("users_name_any_case",)])
        with self.assertRaises(sqlite3.IntegrityError):
            connection = server.connect(self.db_path)
            try:
                connection.execute("INSERT INTO likes VALUES (99, 1)")   # no post 99
            finally:
                connection.close()

    def test_a_version_0_database_gets_both_upgrades(self):
        users, posts, likes = self.use_an_old_database()
        self.assertEqual(self.rows("SELECT id, author_id, text, old_clock_time FROM posts "
                                   "ORDER BY id"), posts)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("SELECT seq FROM sqlite_sequence WHERE name = 'posts'"),
                         [(3,)])

    def test_rebuild_table_keeps_an_extra_column_an_index_and_a_trigger(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "first")
        connection = server.connect(self.db_path)
        # What another plan might have added to posts before this rebuild.
        connection.executescript("""
            ALTER TABLE posts ADD COLUMN mood TEXT NOT NULL DEFAULT 'happy';
            CREATE INDEX posts_by_author ON posts (author_id);
            CREATE TABLE post_log (post_id INTEGER);
            CREATE TRIGGER log_each_post AFTER INSERT ON posts
              BEGIN INSERT INTO post_log VALUES (new.id); END;
        """)
        connection.execute("UPDATE posts SET mood = 'sleepy'")
        connection.commit()
        # The change for this test: one more column at the end.
        server.rebuild_table(connection, "posts", lambda sql: sql[:-1] + ", note TEXT)")
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        connection.close()
        self.assertEqual(self.rows("SELECT id, text, mood, note FROM posts"),
                         [(1, "first", "sleepy", None)])
        self.assertEqual(self.rows("SELECT type, name FROM sqlite_master "
                                   "WHERE tbl_name = 'posts' AND type IN ('index', 'trigger') "
                                   "AND name IN ('log_each_post', 'posts_by_author') "
                                   "ORDER BY name"),
                         [("trigger", "log_each_post"), ("index", "posts_by_author")])
        server.save_post(self.db_path, aiko, "second")   # the trigger still works
        self.assertEqual(self.rows("SELECT post_id FROM post_log"), [(2,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_rebuild_table_changes_nothing_if_a_row_would_point_at_nothing(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "first")
        connection = sqlite3.connect(self.db_path)   # foreign keys off, to break a rule
        connection.execute("INSERT INTO likes VALUES (99, 1)")
        connection.commit()
        before = self.rows("SELECT sql FROM sqlite_master WHERE name = 'posts'")
        with self.assertRaises(SystemExit):
            server.rebuild_table(connection, "posts", lambda sql: sql[:-1] + ", note TEXT)")
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        connection.close()
        self.assertEqual(self.rows("SELECT sql FROM sqlite_master WHERE name = 'posts'"), before)
        self.assertEqual(self.rows("SELECT id, text FROM posts"), [(1, "first")])

    def test_create_tables_twice_is_harmless_after_groundwork(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "first")
        before = self.rows("SELECT * FROM posts")
        schema = self.rows("SELECT sql FROM sqlite_master ORDER BY name")
        server.create_tables(self.db_path)
        self.assertEqual(self.rows("SELECT * FROM posts"), before)
        self.assertEqual(self.rows("SELECT sql FROM sqlite_master ORDER BY name"), schema)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(server.save_post(self.db_path, aiko, "second")["id"], 2)

    # -- long-posts --

    def test_the_limit_is_560(self):
        # The one place a test says the number on purpose, so a wrong edit is noticed.
        self.assertEqual(server.MAX_TEXT, 560)

    def test_an_emoji_counts_as_one_character(self):
        aiko = self.sign_up("aiko")
        row = server.save_post(self.db_path, aiko, "\U0001F600" * server.MAX_TEXT)
        self.assertEqual(len(row["text"]), server.MAX_TEXT)
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, aiko, "\U0001F600" * (server.MAX_TEXT + 1))

    # -- who-liked --
    #
    # People are made straight with SQL here, so no test hashes a password
    # 600,000 times for each of them. They have no password, like an old user.

    def person(self, name, display_name=None):
        """Add a user with SQL. Return the id."""
        connection = server.connect(self.db_path)
        user_id = connection.execute("INSERT INTO users (name, display_name) VALUES (?, ?)",
                                     (name, display_name or name)).lastrowid
        connection.commit()
        connection.close()
        return user_id

    def post_by(self, user_id, text="hello"):
        return server.save_post(self.db_path, user_id, text)["id"]

    def like(self, user_id, *post_ids):
        for post_id in post_ids:
            server.add_like(self.db_path, user_id, post_id)

    def names(self, rows):
        return [row["name"] for row in rows]

    def summary(self, viewer_id, post_id):
        return server.like_summaries(self.db_path, viewer_id, str(post_id))[post_id]

    def leaders(self, viewer_id, post_id):
        return self.names(self.summary(viewer_id, post_id)["leaders"])

    def counts_of_every_table(self):
        return [self.rows(f"SELECT COUNT(*) FROM {table}")[0][0]
                for table in ("users", "posts", "likes", "sessions")]

    def test_who_liked_a_post_nobody_liked(self):
        aiko = self.person("aiko")
        post = self.post_by(aiko)
        self.assertEqual(server.who_liked(self.db_path, post), (post, [], 0))

    def test_who_liked_is_a_to_z_ignoring_capitals(self):
        aiko, chika, ben = self.person("aiko"), self.person("Chika"), self.person("ben")
        post = self.post_by(aiko)
        self.like(chika, post)
        self.like(ben, post)
        post_id, rows, count = server.who_liked(self.db_path, str(post))
        self.assertEqual((post_id, self.names(rows), count), (post, ["ben", "Chika"], 2))

    def test_a_like_taken_back_is_gone_from_the_list(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        post = self.post_by(aiko)
        self.like(ben, post)
        server.remove_like(self.db_path, ben, post)
        self.assertEqual(server.who_liked(self.db_path, post), (post, [], 0))

    def test_who_liked_refuses_a_missing_or_wrong_post_id(self):
        for post_id in (None, "", "seven"):
            with self.subTest(post_id=post_id):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.who_liked(self.db_path, post_id)
                self.assertIn("which post", str(caught.exception))
        with self.assertRaises(server.RuleBroken) as caught:
            server.who_liked(self.db_path, 99)
        self.assertIn("does not exist", str(caught.exception))

    def test_who_liked_names_at_most_max_likers_but_counts_them_all(self):
        aiko = self.person("aiko")
        post = self.post_by(aiko)
        for name in ("ben", "chika", "dan"):
            self.like(self.person(name), post)
        old = server.MAX_LIKERS
        server.MAX_LIKERS = 2
        try:
            post_id, rows, count = server.who_liked(self.db_path, post)
        finally:
            server.MAX_LIKERS = old
        self.assertEqual((self.names(rows), count), (["ben", "chika"], 3))

    def test_an_old_unclaimed_user_s_like_is_listed(self):
        self.use_an_old_database()   # Ben and Daniel Radcliffe liked post 1
        post_id, rows, count = server.who_liked(self.db_path, 1)
        self.assertEqual([tuple(row) for row in rows],
                         [("Ben", "Ben"), ("Daniel Radcliffe", "Daniel Radcliffe")])

    def test_the_most_popular_likers_are_the_leaders(self):
        aiko, anika, ben, chika = (self.person(n) for n in ("aiko", "anika", "ben", "chika"))
        chika_posts = [self.post_by(chika) for _ in range(3)]
        self.like(aiko, *chika_posts)        # Chika: 3 likes from others
        self.like(aiko, self.post_by(anika))  # Anika: 1
        post = self.post_by(aiko)
        self.like(anika, post)
        self.like(ben, post)
        self.like(chika, post)
        self.assertEqual(self.leaders(None, post), ["chika", "anika"])

    def test_posting_a_lot_is_not_popularity(self):
        aiko, anika, ben = self.person("aiko"), self.person("anika"), self.person("ben")
        # Ben posts ten times, slowly enough that the rate limit never stops him.
        clock = use_fake_clock(self)
        for _ in range(10):
            self.post_by(ben)
            clock.move(60)
        self.like(aiko, self.post_by(anika))
        post = self.post_by(aiko)
        self.like(ben, post)
        self.like(anika, post)
        self.assertEqual(self.leaders(None, post), ["anika", "ben"])

    def test_liking_yourself_is_not_popularity(self):
        aiko, anika, ben = self.person("aiko"), self.person("anika"), self.person("ben")
        for _ in range(5):
            self.like(ben, self.post_by(ben))
        post = self.post_by(aiko)
        self.like(ben, post)
        self.like(anika, post)
        # Both have 0 from other people, so it is A to Z: Anika before Ben.
        self.assertEqual(self.leaders(None, post), ["anika", "ben"])

    def test_equal_popularity_is_a_to_z_ignoring_capitals(self):
        aiko = self.person("aiko")
        post = self.post_by(aiko)
        for name in ("dan", "Bea", "chika"):
            self.like(self.person(name), post)
        self.assertEqual(self.leaders(None, post), ["Bea", "chika"])

    def test_popularity_is_counted_from_the_rows_every_time(self):
        aiko, anika, chika = self.person("aiko"), self.person("anika"), self.person("chika")
        chika_post = self.post_by(chika)
        self.like(aiko, chika_post)
        post = self.post_by(aiko)
        self.like(anika, post)
        self.like(chika, post)
        tables = [self.rows(f"PRAGMA table_info({t})") for t in ("users", "posts", "likes")]
        self.assertEqual(self.leaders(None, post), ["chika", "anika"])
        server.remove_like(self.db_path, aiko, chika_post)
        self.assertEqual(self.leaders(None, post), ["anika", "chika"])
        self.assertEqual([self.rows(f"PRAGMA table_info({t})") for t in ("users", "posts", "likes")],
                         tables)

    def test_you_come_first_and_are_never_a_leader(self):
        aiko, anika, ben, chika = (self.person(n) for n in ("aiko", "anika", "ben", "chika"))
        post = self.post_by(aiko)
        self.like(anika, post)
        self.like(ben, post)
        self.like(chika, post)
        mine = self.summary(ben, post)
        self.assertEqual((mine["you"], mine["like_count"], self.names(mine["leaders"])),
                         (True, 3, ["anika"]))
        theirs = self.summary(aiko, post)   # Aiko did not like it
        self.assertEqual((theirs["you"], self.names(theirs["leaders"])),
                         (False, ["anika", "ben"]))
        nobody = self.summary(None, post)
        self.assertEqual((nobody["you"], self.names(nobody["leaders"])),
                         (False, ["anika", "ben"]))

    def test_each_summary_count_is_the_count_of_rows(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        one, two = self.post_by(aiko), self.post_by(aiko)
        self.like(ben, one)
        self.like(aiko, one, two)
        summaries = server.like_summaries(self.db_path, None, f"{one},{two},99")
        for post_id in (one, two):
            self.assertEqual(summaries[post_id]["like_count"],
                             self.rows("SELECT COUNT(*) FROM likes WHERE post_id = ?",
                                       (post_id,))[0][0])
        self.assertEqual(summaries[99], {"like_count": 0, "you": False, "leaders": []})

    def test_check_post_ids(self):
        for text in ("", "a,b", "1,,2", "1;2", None, "-1"):
            with self.subTest(text=text):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.check_post_ids(text)
                self.assertIn("which posts", str(caught.exception))
        with self.assertRaises(server.RuleBroken) as caught:
            server.check_post_ids(",".join(str(n) for n in range(1, 102)))
        self.assertIn("at most 100", str(caught.exception))
        self.assertEqual(len(server.check_post_ids(",".join(str(n) for n in range(1, 101)))),
                         100)
        self.assertEqual(server.check_post_ids("7,7"), [7])

    def test_asking_who_liked_adds_nothing(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        post = self.post_by(aiko)
        self.like(ben, post)
        before = self.counts_of_every_table()
        server.who_liked(self.db_path, post)
        with self.assertRaises(server.RuleBroken):
            server.who_liked(self.db_path, 99)
        server.like_summaries(self.db_path, None, f"{post},99")
        server.like_summaries(self.db_path, ben, f"{post},99")
        server.like_summaries(self.db_path, 12345, f"{post}")   # a viewer who does not exist
        self.assertEqual(self.counts_of_every_table(), before)

    def test_a_liker_in_an_answer_has_only_the_two_names(self):
        aiko = self.sign_up("aiko", "Aiko Tanaka")   # a real account, with a password hash
        post = self.post_by(aiko)
        self.like(aiko, post)
        secrets_in_file = [value for row in self.rows(
            "SELECT password_salt, password_hash FROM users") for value in row]
        post_id, rows, count = server.who_liked(self.db_path, post)
        likers = server.likers_to_json(post_id, rows, count)
        summaries = server.summaries_to_json(server.like_summaries(self.db_path, None, str(post)))
        people = likers["likers"] + summaries["summaries"][str(post)]["leaders"]
        self.assertEqual(len(people), 2)
        for person in people:
            self.assertEqual(person, {"account_name": "aiko", "display_name": "Aiko Tanaka"})
        answer = json.dumps([likers, summaries])
        for secret in secrets_in_file:
            self.assertNotIn(secret, answer)

    def test_sqlite_has_window_functions(self):
        self.assertGreaterEqual(sqlite3.sqlite_version_info, (3, 25, 0),
                                "who-liked needs SQLite 3.25 or newer, for ROW_NUMBER() OVER.")


    # -- timestamps: the full date and time, in UTC --

    def test_a_post_is_saved_with_the_time_it_is_given(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "hello", now=SOME_MOMENT)
        self.assertEqual(self.rows("SELECT posted_at, old_clock_time FROM posts"),
                         [("2026-10-02T07:42:10Z", None)])

    def test_a_time_in_japan_is_saved_in_utc(self):
        aiko = self.sign_up("aiko")
        japan = timezone(timedelta(hours=9))   # JST, nine hours ahead of UTC
        server.save_post(self.db_path, aiko, "hello",
                         now=datetime(2026, 10, 2, 16, 42, 10, tzinfo=japan))
        self.assertEqual(self.rows("SELECT posted_at FROM posts"), [("2026-10-02T07:42:10Z",)])

    def test_a_time_without_a_time_zone_is_refused(self):
        with self.assertRaises(ValueError):
            server.utc_text(datetime(2026, 10, 2, 7, 42, 10))

    def test_the_same_clock_time_on_two_days_is_two_different_times(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "one", now=SOME_MOMENT)
        server.save_post(self.db_path, aiko, "two", now=SOME_MOMENT + timedelta(days=1))
        self.assertEqual(self.rows("SELECT posted_at FROM posts ORDER BY id"),
                         [("2026-10-02T07:42:10Z",), ("2026-10-03T07:42:10Z",)])

    def test_with_no_time_given_the_server_clock_is_used(self):
        aiko = self.sign_up("aiko")
        # Only the shape and the order are checked, never the real time itself.
        before = server.utc_text(server.utc_now())
        row = server.save_post(self.db_path, aiko, "hello")
        after = server.utc_text(server.utc_now())
        self.assertRegex(row["posted_at"], ISO_TIME)
        self.assertTrue(before <= row["posted_at"] <= after)

    def test_the_database_refuses_a_wrong_time_or_both_or_neither(self):
        aiko = self.sign_up("aiko")
        connection = server.connect(self.db_path)
        for posted_at, old_clock_time in (("15:42", None), (None, None),
                                          ("2026-10-02T07:42:10Z", "15:42"),
                                          (None, "3pm"), ("2026-10-02 07:42:10", None)):
            with self.subTest(posted_at=posted_at, old_clock_time=old_clock_time):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO posts (author_id, text, posted_at, "
                                       "old_clock_time) VALUES (?, 'x', ?, ?)",
                                       (aiko, posted_at, old_clock_time))
        connection.close()
        self.assertEqual(self.rows("SELECT * FROM posts"), [])

    def test_the_timestamps_upgrade_keeps_old_times_as_date_unknown(self):
        before, after = self.use_an_accounts_database()
        self.assertEqual(self.rows("SELECT id, author_id, text, posted_at, old_clock_time "
                                   "FROM posts ORDER BY id"),
                         [(1, 1, "first", None, "09:00"), (2, 2, "second", None, "09:01"),
                          (5, 1, "fifth", None, "09:05")])
        self.assertEqual(after["likes"], before["likes"])   # each like still points at its post
        self.assertEqual(after["users"], before["users"])
        self.assertEqual(after["sessions"], before["sessions"])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        connection = server.connect(self.db_path)
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        connection.close()
        # The column order keeps its shape: posted_at, then old_clock_time.
        # Later upgrades (place) add their columns after these five.
        self.assertEqual([row[1] for row in self.rows("PRAGMA table_info(posts)")][:5],
                         ["id", "author_id", "text", "posted_at", "old_clock_time"])

    def test_after_the_upgrade_a_new_post_gets_a_full_time_and_order_is_by_id(self):
        self.use_an_accounts_database()
        row = server.save_post(self.db_path, 1, "new", now=SOME_MOMENT)
        self.assertEqual(row["id"], 6)
        posts = server.posts_to_json(server.posts_after(self.db_path, 0))
        self.assertEqual([post["id"] for post in posts], [1, 2, 5, 6])
        self.assertEqual((posts[0]["posted_at"], posts[0]["old_clock_time"]), (None, "09:00"))
        self.assertEqual((posts[3]["posted_at"], posts[3]["old_clock_time"]),
                         ("2026-10-02T07:42:10Z", None))

    def test_the_upgrade_refuses_an_old_time_that_is_not_hh_mm(self):
        self.db_path = os.path.join(self.folder.name, "odd.db")
        connection = sqlite3.connect(self.db_path)
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE posts (id INTEGER PRIMARY KEY,
                                author_id INTEGER NOT NULL REFERENCES users(id),
                                text TEXT NOT NULL, posted_at TEXT NOT NULL);
            INSERT INTO users VALUES (1, 'aiko');
            INSERT INTO posts VALUES (1, 1, 'first', 'teatime');
        """)
        connection.close()
        with self.assertRaises(SystemExit) as caught:
            server.create_tables(self.db_path)
        self.assertIn("make reset", str(caught.exception))
        self.assertEqual(self.rows("SELECT posted_at FROM posts"), [("teatime",)])
        self.assertEqual(self.rows("PRAGMA user_version"), [(2,)])   # timestamps did not happen

    def test_the_json_has_both_times_for_an_old_and_a_new_post(self):
        self.use_an_accounts_database()
        server.save_post(self.db_path, 1, "new", now=SOME_MOMENT)
        posts = server.posts_to_json(server.posts_after(self.db_path, 0))
        for post in posts:
            self.assertIn("posted_at", post)
            self.assertIn("old_clock_time", post)
        self.assertEqual(posts[-1]["posted_at"], "2026-10-02T07:42:10Z")

    # -- rate limits: too many, too quickly --

    def post_too_fast(self, user_id, text="one more"):
        """A post the rate limit refuses. Return the TooFast it raised."""
        with self.assertRaises(server.TooFast) as caught:
            server.save_post(self.db_path, user_id, text)
        return caught.exception

    def test_the_sixth_post_in_a_minute_is_refused(self):
        clock = use_fake_clock(self)
        aiko = self.sign_up("aiko")
        for number in range(5):
            server.save_post(self.db_path, aiko, f"post {number}")
        problem = self.post_too_fast(aiko, "the sixth")
        self.assertEqual(problem.retry_after, 60)
        self.assertEqual(str(problem), "Too many posts. Please try again in 60 seconds.")
        self.assertNotIn(("the sixth",), self.rows("SELECT text FROM posts"))
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 5)
        # A minute and a second later, the first one no longer counts.
        clock.move(61)
        server.save_post(self.db_path, aiko, "allowed again")

    def test_the_wait_counts_down(self):
        clock = use_fake_clock(self)
        aiko = self.sign_up("aiko")
        for number in range(5):
            server.save_post(self.db_path, aiko, f"post {number}")
        clock.move(20)
        self.assertEqual(self.post_too_fast(aiko).retry_after, 40)
        clock.move(39.5)
        self.assertEqual(self.post_too_fast(aiko).retry_after, 1)   # rounded up, at least 1

    def test_one_person_s_limit_does_not_touch_another(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        for number in range(5):
            server.save_post(self.db_path, aiko, f"post {number}")
        self.post_too_fast(aiko)
        server.save_post(self.db_path, ben, "Ben is fine")

    def test_a_post_that_breaks_a_rule_is_not_counted(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        for text in ("", "   ", "x" * (server.MAX_TEXT + 1)):
            with self.assertRaises(server.RuleBroken):
                server.save_post(self.db_path, aiko, text)
        self.assertEqual(self.rows("SELECT * FROM attempts WHERE action = 'post'"), [])
        for number in range(5):
            server.save_post(self.db_path, aiko, f"post {number}")

    def test_a_refused_attempt_is_not_counted(self):
        clock = use_fake_clock(self)
        aiko = self.sign_up("aiko")
        for number in range(5):
            server.save_post(self.db_path, aiko, f"post {number}")
        for _ in range(3):
            self.post_too_fast(aiko)
        self.assertEqual(len(self.rows("SELECT * FROM attempts WHERE action = 'post'")), 5)
        # So pressing during the wait does not make the wait longer.
        clock.move(61)
        server.save_post(self.db_path, aiko, "allowed again")

    def test_liking_and_taking_back_share_one_count(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        post_id = server.save_post(self.db_path, aiko, "hello")["id"]
        for _ in range(15):
            server.add_like(self.db_path, aiko, post_id)
            server.remove_like(self.db_path, aiko, post_id)
        with self.assertRaises(server.TooFast) as caught:
            server.add_like(self.db_path, aiko, post_id)
        self.assertIn("Too many likes", str(caught.exception))
        self.assertEqual(self.rows("SELECT * FROM likes"), [])

    def test_a_like_that_breaks_a_rule_is_not_counted(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        post_id = server.save_post(self.db_path, aiko, "hello")["id"]
        server.add_like(self.db_path, aiko, post_id)
        for like in (lambda: server.add_like(self.db_path, aiko, 99),        # no such post
                     lambda: server.add_like(self.db_path, aiko, post_id),   # already liked
                     lambda: server.add_like(self.db_path, aiko, None),      # no post id
                     lambda: server.remove_like(self.db_path, aiko, 99)):    # not liked
            with self.assertRaises(server.RuleBroken):
                like()
        self.assertEqual(len(self.rows("SELECT * FROM attempts WHERE action = 'like'")), 1)

    def test_after_five_wrong_passwords_even_the_right_one_waits_and_is_not_hashed(self):
        use_fake_clock(self)
        self.sign_up("aiko")
        with mock.patch.object(server, "hash_password", wraps=server.hash_password) as hashing:
            for _ in range(5):
                with self.assertRaises(server.NotSignedIn):
                    server.log_in(self.db_path, "aiko", "not the password")
            with self.assertRaises(server.TooFast) as caught:
                server.log_in(self.db_path, "aiko", PASSWORD)
        self.assertEqual(hashing.call_count, 5)
        self.assertEqual(caught.exception.retry_after, 600)
        self.assertIn("wrong passwords", str(caught.exception))

    def test_login_is_counted_the_same_for_any_capitals_and_for_a_name_with_no_account(self):
        use_fake_clock(self)
        self.sign_up("aiko")
        for name in ("Aiko", "aiko", "AIKO", " aiko ", "aIKo"):
            with self.assertRaises(server.NotSignedIn):
                server.log_in(self.db_path, name, "not the password")
        with self.assertRaises(server.TooFast):
            server.log_in(self.db_path, "aiko", PASSWORD)
        # A name with no account is limited the same way, so the limit tells a
        # stranger nothing about which names exist.
        for _ in range(5):
            with self.assertRaises(server.NotSignedIn):
                server.log_in(self.db_path, "nobody", "not the password")
        with self.assertRaises(server.TooFast):
            server.log_in(self.db_path, "nobody", "not the password")

    def test_a_right_password_forgets_the_wrong_ones(self):
        use_fake_clock(self)
        self.sign_up("aiko")
        for _ in range(4):
            with self.assertRaises(server.NotSignedIn):
                server.log_in(self.db_path, "aiko", "not the password")
        server.log_in(self.db_path, "Aiko", PASSWORD)
        self.assertEqual(self.rows("SELECT * FROM attempts WHERE action = 'login'"), [])
        for _ in range(5):
            with self.assertRaises(server.NotSignedIn):
                server.log_in(self.db_path, "aiko", "not the password")

    def test_sign_ups_are_limited_for_each_address_before_hashing(self):
        use_fake_clock(self)
        most, seconds = server.LIMITS["signup"]
        for number in range(most):
            server.create_account(self.db_path, f"user{number}", "", PASSWORD, address="1.2.3.4")
        with mock.patch.object(server, "hash_password", wraps=server.hash_password) as hashing:
            with self.assertRaises(server.TooFast) as caught:
                server.create_account(self.db_path, "one_more", "", PASSWORD, address="1.2.3.4")
        self.assertEqual(hashing.call_count, 0)
        self.assertIn("new accounts", str(caught.exception))
        self.assertEqual(len(self.users()), most)
        # Another address is allowed, and create_account with no address still works.
        server.create_account(self.db_path, "elsewhere", "", PASSWORD, address="5.6.7.8")
        server.create_account(self.db_path, "no_address", "", PASSWORD)

    def test_a_sign_up_with_a_bad_name_is_not_counted(self):
        use_fake_clock(self)
        with self.assertRaises(server.RuleBroken):
            server.create_account(self.db_path, "not one word", "", PASSWORD, address="1.2.3.4")
        self.assertEqual(self.rows("SELECT * FROM attempts"), [])

    def test_ten_posts_at_the_same_moment_save_exactly_five(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        start = threading.Barrier(10)
        results = []

        def post(number):
            start.wait()   # all ten begin together
            try:
                server.save_post(self.db_path, aiko, f"post {number}")
                results.append("saved")
            except server.TooFast:
                results.append("too fast")

        threads = [threading.Thread(target=post, args=(n,)) for n in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), ["saved"] * 5 + ["too fast"] * 5)
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 5)

    def test_old_attempts_are_deleted(self):
        clock = use_fake_clock(self)
        aiko = self.sign_up("aiko")
        for number in range(3):
            server.save_post(self.db_path, aiko, f"post {number}")
        longest = max(window for _, window in server.LIMITS.values())
        clock.move(longest + 1)
        server.save_post(self.db_path, aiko, "much later")
        self.assertEqual(self.rows("SELECT action, key, at FROM attempts"),
                         [("post", str(aiko), clock.now)])

    def test_the_rate_limit_upgrade_keeps_every_row(self):
        # A version-3 database (accounts, groundwork and timestamps) with rows in every table.
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        post_id = server.save_post(self.db_path, aiko, "hello")["id"]
        server.add_like(self.db_path, ben, post_id)
        connection = sqlite3.connect(self.db_path)
        connection.executescript("DROP TABLE attempts; PRAGMA user_version = 3;")
        connection.close()
        tables = ("users", "posts", "likes", "sessions")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}
        server.create_tables(self.db_path)
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("SELECT * FROM attempts"), [])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE type = 'index' "
                                   "AND name = 'attempts_by_key'"), [("attempts_by_key",)])
        server.save_post(self.db_path, aiko, "still works")

    # -- search --
    # Posts are added straight with insert_post here, so 51 posts do not meet
    # the rate limit, and every post gets the same fixed time.

    def posts_saying(self, *texts):
        """Add one post for each text, by one person, oldest first. Return their ids."""
        found = self.rows("SELECT id FROM users WHERE name = 'searcher'")
        author = found[0][0] if found else self.person("searcher")
        connection = server.connect(self.db_path)
        ids = [server.insert_post(connection, author, text,
                                  posted_at=server.utc_text(SOME_MOMENT))
               for text in texts]
        connection.commit()
        connection.close()
        return ids

    def found(self, query):
        """The texts a search finds, in the order it gives them."""
        rows, more = server.search_posts(self.db_path, query)
        return [row["text"] for row in rows]

    def test_a_word_is_found_and_capitals_do_not_matter(self):
        self.posts_saying("the library is open", "no match here")
        self.assertEqual(self.found("Library"), ["the library is open"])
        self.assertEqual(self.found("LIBRARY"), ["the library is open"])

    def test_search_results_are_newest_first(self):
        self.posts_saying("cat one", "cat two", "cat three")
        self.assertEqual(self.found("cat"), ["cat three", "cat two", "cat one"])

    def test_percent_underscore_and_backslash_mean_themselves(self):
        self.posts_saying("100% sure", "100 sure", "a_b", "axb", "back\\slash", "backslash")
        self.assertEqual(self.found("100%"), ["100% sure"])
        self.assertEqual(self.found("a_b"), ["a_b"])
        self.assertEqual(self.found("k\\s"), ["back\\slash"])
        self.assertEqual(server.escape_like("1\\0%_"), "1\\\\0\\%\\_")

    def test_every_word_must_appear_in_any_order(self):
        self.posts_saying("the library is open late tonight", "the library is closed",
                          "late again")
        self.assertEqual(self.found("late library"), ["the library is open late tonight"])

    def test_a_bad_search_is_refused_with_its_own_sentence(self):
        for query, words in (("", "Type a word to search for."),
                             ("   ", "Type a word to search for."),
                             (None, "Type a word to search for."),
                             ("x" * (server.MAX_QUERY + 1),
                              f"A search must be {server.MAX_QUERY} characters or fewer."),
                             ("a b c d e f",
                              f"A search may have at most {server.MAX_QUERY_WORDS} words.")):
            with self.subTest(query=query):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.search_posts(self.db_path, query)
                self.assertEqual(str(caught.exception), words)
        # At the limits is fine.
        self.assertEqual(self.found("x" * server.MAX_QUERY), [])
        self.assertEqual(self.found("a b c d e"), [])

    def test_a_tag_finds_only_that_whole_tag(self):
        self.posts_saying("I love my #cat", "#Cat again", "a #catalog", "a cat", "#cat_food")
        self.assertEqual(self.found("#cat"), ["#Cat again", "I love my #cat"])
        self.assertEqual(self.found("#CAT"), ["#Cat again", "I love my #cat"])
        # A lone # is an ordinary word.
        self.assertEqual(len(self.found("#")), 4)

    def test_tags_in_gives_small_letters_without_the_hash(self):
        self.assertEqual(server.tags_in("#Cat and #東京 は雨, #カレー! #cat"),
                         {"cat", "東京", "カレー"})
        self.assertEqual(server.tags_in("#東京は雨"), {"東京は雨"})
        self.assertEqual(server.tags_in("no tags # here"), set())

    def test_japanese_words_and_tags_are_found(self):
        self.posts_saying("東京は雨です", "#東京 は雨", "大阪は晴れ")
        self.assertEqual(self.found("東京"), ["#東京 は雨", "東京は雨です"])
        self.assertEqual(self.found("#東京"), ["#東京 は雨"])
        # A Japanese full-width space splits words too.
        self.assertEqual(self.found("東京\u3000雨"), ["#東京 は雨", "東京は雨です"])

    def test_at_most_the_limit_and_more_says_so(self):
        self.posts_saying(*["cat " + str(number) for number in range(server.SEARCH_LIMIT)])
        rows, more = server.search_posts(self.db_path, "cat")
        self.assertEqual((len(rows), more), (server.SEARCH_LIMIT, False))
        self.posts_saying("cat newest")
        rows, more = server.search_posts(self.db_path, "cat")
        self.assertEqual((len(rows), more), (server.SEARCH_LIMIT, True))
        self.assertEqual(rows[0]["text"], "cat newest")

    def test_the_tag_rule_is_inside_the_limit(self):
        # Many #catalog posts that LIKE finds but the tag rule refuses must not
        # use up the limit: the one real #cat post is still found.
        self.posts_saying("#cat first")
        self.posts_saying(*["#catalog " + str(number)
                            for number in range(server.SEARCH_LIMIT + 5)])
        rows, more = server.search_posts(self.db_path, "#cat")
        self.assertEqual(([row["text"] for row in rows], more), (["#cat first"], False))

    def test_searching_changes_no_row(self):
        aiko = self.person("aiko")
        post = self.post_by(aiko, "cat")
        self.like(aiko, post)
        before = all_values_in(self.db_path)
        counts = self.counts_of_every_table()
        for query in ("cat", "#cat", "nothing", "a_b%"):
            server.search_posts(self.db_path, query)
            server.search_posts(self.db_path, query, viewer_id=aiko)
        self.assertEqual(self.counts_of_every_table(), counts)
        self.assertEqual(all_values_in(self.db_path), before)

    def test_search_answer_has_posts_and_more(self):
        self.posts_saying("cat")
        rows, more = server.search_posts(self.db_path, "cat")
        answer = server.search_to_json(rows, more)
        self.assertEqual(set(answer), {"posts", "more"})
        self.assertEqual(answer["posts"], server.posts_to_json(rows))

    # -- timeline-flow: one page of older posts at a time --

    def many_posts(self, user_id, count):
        """Save `count` posts, a minute apart on the fake clock, so the rate limit
        never refuses one. Return their ids, oldest first."""
        clock = use_fake_clock(self)
        ids = []
        for number in range(count):
            ids.append(self.post_by(user_id, f"post {number + 1}"))
            clock.move(61)
        return ids

    def ids(self, rows):
        return [row["id"] for row in rows]

    def test_before_0_gives_the_newest_page_newest_first(self):
        ids = self.many_posts(self.person("aiko"), 25)
        page = self.ids(server.posts_before(self.db_path, 0))
        self.assertEqual(len(page), server.PAGE_SIZE)
        self.assertEqual(page, list(reversed(ids))[:server.PAGE_SIZE])

    def test_before_gives_the_next_older_page(self):
        ids = self.many_posts(self.person("aiko"), 25)
        self.assertEqual(self.ids(server.posts_before(self.db_path, ids[5])),
                         list(reversed(ids[:5])))
        self.assertEqual(server.posts_before(self.db_path, ids[0]), [])
        # The address gives it as text; the model takes that too.
        self.assertEqual(self.ids(server.posts_before(self.db_path, str(ids[5]))),
                         list(reversed(ids[:5])))

    def test_a_new_post_does_not_move_a_page(self):
        aiko = self.person("aiko")
        self.many_posts(aiko, 25)
        first = self.ids(server.posts_before(self.db_path, 0))
        self.post_by(self.person("ben"), "a new post between two pages")
        second = self.ids(server.posts_before(self.db_path, first[-1]))
        self.assertEqual(set(first) & set(second), set())
        self.assertEqual(len(first) + len(second), 25)

    def test_before_must_be_a_whole_number_0_or_more(self):
        for wrong in ("abc", "-1", None, "1.5", "", " 3", "+3", -1, True, 1.0):
            with self.subTest(before=wrong):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.posts_before(self.db_path, wrong)
                self.assertEqual(str(caught.exception),
                                 "'before' must be a whole number, 0 or more.")

    def test_posts_before_goes_through_the_visibility_filter(self):
        aiko = self.person("aiko")
        self.post_by(aiko)
        with mock.patch.object(server, "visible_to", return_value=("1 = 0", [])):
            self.assertEqual(server.posts_before(self.db_path, 0), [])

    def test_likes_from_leaves_out_older_posts(self):
        aiko = self.person("aiko")
        ids = self.many_posts(aiko, 10)
        server.add_like(self.db_path, aiko, ids[1])
        server.add_like(self.db_path, aiko, ids[8])
        counts, mine = server.likes_for(self.db_path, aiko, ids[4])
        self.assertEqual([row["post_id"] for row in counts], [ids[8]])
        self.assertEqual([row["post_id"] for row in mine], [ids[8]])
        counts, mine = server.likes_for(self.db_path, aiko)
        self.assertEqual([row["post_id"] for row in counts], [ids[1], ids[8]])
        self.assertEqual([row["post_id"] for row in mine], [ids[1], ids[8]])
        with self.assertRaises(server.RuleBroken) as caught:
            server.likes_for(self.db_path, aiko, "abc")
        self.assertEqual(str(caught.exception), "'from' must be a whole number, 0 or more.")

    # -- place --

    def place_of(self, post_id):
        return self.rows("SELECT place FROM posts WHERE id = ?", (post_id,))[0][0]

    def test_a_post_with_no_place_saves_null(self):
        aiko = self.sign_up("aiko")
        for place in (None, "", "   "):
            with self.subTest(place=place):
                row = server.save_post(self.db_path, aiko, "hello", place=place)
                self.assertIsNone(row["place"])
                self.assertIsNone(self.place_of(row["id"]))
        # And a call with no place at all, as every other feature makes it.
        self.assertIsNone(server.save_post(self.db_path, aiko, "hello")["place"])

    def test_a_place_is_saved_without_extra_spaces(self):
        aiko = self.sign_up("aiko")
        row = server.save_post(self.db_path, aiko, "hello", place=" Osaka ")
        self.assertEqual(row["place"], "Osaka")
        self.assertEqual(self.place_of(row["id"]), "Osaka")

    def test_a_place_of_the_limit_is_allowed_and_one_more_is_refused(self):
        aiko = self.sign_up("aiko")
        row = server.save_post(self.db_path, aiko, "hello", place="a" * server.MAX_PLACE)
        self.assertEqual(len(row["place"]), server.MAX_PLACE)
        with self.assertRaises(server.RuleBroken) as caught:
            server.save_post(self.db_path, aiko, "hello", place="a" * (server.MAX_PLACE + 1))
        self.assertEqual(str(caught.exception),
                         f"The place must be {server.MAX_PLACE} characters or fewer.")
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 1)

    def test_a_place_with_hidden_characters_is_refused_and_nothing_is_saved(self):
        aiko = self.sign_up("aiko")
        for place in ("Osaka\nfake line", "Osa\u2028ka", "Osaka\u202e"):
            with self.subTest(place=repr(place)):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.save_post(self.db_path, aiko, "hello", place=place)
                self.assertEqual(str(caught.exception),
                                 "The place must not have hidden characters or line breaks.")
        self.assertEqual(self.rows("SELECT * FROM posts"), [])
        # A refused place is not counted against the rate limit either.
        self.assertEqual(self.rows("SELECT * FROM attempts WHERE action = 'post'"), [])

    def test_a_place_that_is_not_text_counts_as_no_place(self):
        aiko = self.sign_up("aiko")
        for place in (42, ["Osaka"], {"city": "Osaka"}, True):
            with self.subTest(place=place):
                self.assertIsNone(server.save_post(self.db_path, aiko, "hi", place=place)["place"])

    def test_the_place_is_on_posts_never_on_users(self):
        connection = server.connect(self.db_path)
        posts = [c["name"] for c in connection.execute("PRAGMA table_info(posts)")]
        users = [c["name"] for c in connection.execute("PRAGMA table_info(users)")]
        connection.close()
        self.assertIn("place", posts)
        self.assertNotIn("place", users)

    def test_the_database_itself_refuses_an_empty_or_too_long_place(self):
        aiko = self.sign_up("aiko")
        connection = server.connect(self.db_path)
        for place in ("", "a" * (server.MAX_PLACE + 1)):
            with self.subTest(length=len(place)):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO posts (author_id, text, posted_at, place) "
                                       "VALUES (?, 'hi', '2026-10-02T07:42:10Z', ?)",
                                       (aiko, place))
        connection.close()

    def test_the_place_upgrade_keeps_every_row(self):
        # A database at the version before place: made with the place upgrade
        # turned off, then given rows in every table.
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db_path = os.path.join(folder.name, "old.db")
        # Every later upgrade is held back too (pictures, block, replies, edit-delete),
        # so the file stops before place.
        with mock.patch.object(server, "upgrade_to_place", lambda connection: None), \
                mock.patch.object(server, "upgrade_to_pictures", lambda connection: None), \
                mock.patch.object(server, "upgrade_to_block", lambda connection: None), \
                mock.patch.object(server, "upgrade_to_replies", lambda connection: None), \
                mock.patch.object(server, "upgrade_to_edit_delete", lambda connection: None), \
                mock.patch.object(server, "upgrade_to_report", lambda connection: None):
            server.create_tables(self.db_path)
        old_version = self.rows("PRAGMA user_version")[0][0]
        self.assertLess(old_version, server.LATEST_VERSION)
        columns = [row[1] for row in self.rows("PRAGMA table_info(posts)")]
        self.assertNotIn("place", columns)
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        connection = server.connect(self.db_path)
        for text in ("one", "two"):
            connection.execute("INSERT INTO posts (author_id, text, posted_at) "
                               "VALUES (?, ?, '2026-10-02T07:42:10Z')", (aiko, text))
        connection.execute("INSERT INTO likes (post_id, user_id) VALUES (1, ?)", (ben,))
        connection.commit()
        connection.close()
        tables = ("users", "posts", "likes", "sessions")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}

        server.create_tables(self.db_path)
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        # Every old post is kept, with place NULL at the end (and then replies'
        # parent_id and edit-delete's deleted_at, NULL too).
        self.assertEqual(after["posts"], [row + (None, None, None) for row in before["posts"]])
        for table in ("users", "likes", "sessions"):
            self.assertEqual(after[table], before[table])
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

        # Starting the server again changes nothing more.
        server.create_tables(self.db_path)
        self.assertEqual(self.rows("SELECT * FROM posts ORDER BY 1"), after["posts"])
        row = server.save_post(self.db_path, aiko, "from Kyoto", place="Kyoto")
        self.assertEqual(row["place"], "Kyoto")

    def test_the_log_line_ends_with_the_place_only_when_there_is_one(self):
        aiko = self.sign_up("aiko", "Aiko Tanaka")
        with_place = server.save_post(self.db_path, aiko, "the library is open late",
                                      now=SOME_MOMENT, place="Osaka")
        self.assertEqual(server.post_to_log_line(with_place),
                         '2026-10-02T07:42:10Z  Aiko Tanaka @aiko: '
                         '"the library is open late" · Osaka')
        without = server.save_post(self.db_path, aiko, "line one\nline two", now=SOME_MOMENT)
        self.assertEqual(server.post_to_log_line(without),
                         '2026-10-02T07:42:10Z  Aiko Tanaka @aiko: "line one\\nline two"')

    def test_post_to_json_has_the_place(self):
        aiko = self.sign_up("aiko")
        self.assertEqual(server.post_to_json(
            server.save_post(self.db_path, aiko, "hi", place="Osaka"))["place"], "Osaka")
        self.assertIsNone(server.post_to_json(server.save_post(self.db_path, aiko, "hi"))["place"])

    # -- bookmarks: a post saved by one person, for that person only --

    def bookmark_people(self):
        """Aiko and Ben, and three posts: two by Aiko, one by Ben. Returns the ids."""
        aiko = self.sign_up("aiko", "Aiko Tanaka")
        ben = self.sign_up("ben", "Ben Ito")
        first = server.save_post(self.db_path, aiko, "first", now=SOME_MOMENT)["id"]
        second = server.save_post(self.db_path, aiko, "second", now=SOME_MOMENT)["id"]
        bens = server.save_post(self.db_path, ben, "Ben's", now=SOME_MOMENT)["id"]
        return aiko, ben, first, second, bens

    def test_a_bookmark_is_one_row_with_the_two_ids_and_nothing_else(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        self.assertEqual(server.add_bookmark(self.db_path, aiko, bens), bens)
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [(aiko, bens)])
        columns = [row[1] for row in self.rows("PRAGMA table_info(bookmarks)")]
        self.assertEqual(columns, ["user_id", "post_id"])

    def test_bookmarking_the_same_post_twice_is_refused(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_bookmark(self.db_path, aiko, bens)
        with self.assertRaisesRegex(server.RuleBroken, "already bookmarked"):
            server.add_bookmark(self.db_path, aiko, str(bens))
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [(aiko, bens)])

    def test_the_database_itself_refuses_a_second_bookmark(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_bookmark(self.db_path, aiko, bens)
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO bookmarks (user_id, post_id) VALUES (?, ?)",
                               (aiko, bens))
        connection.close()

    def test_a_bookmark_for_a_missing_post_or_with_no_post_id_is_refused(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        with self.assertRaisesRegex(server.RuleBroken, "That post does not exist."):
            server.add_bookmark(self.db_path, aiko, 999)
        for nothing in (None, "", "seven", [1]):
            with self.subTest(post_id=nothing):
                with self.assertRaisesRegex(server.RuleBroken,
                                            "The bookmark must say which post it is for."):
                    server.add_bookmark(self.db_path, aiko, nothing)
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [])

    def test_taking_a_bookmark_back_deletes_the_row(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_bookmark(self.db_path, aiko, bens)
        self.assertEqual(server.remove_bookmark(self.db_path, aiko, bens), bens)
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [])
        with self.assertRaisesRegex(server.RuleBroken, "You have not bookmarked that post."):
            server.remove_bookmark(self.db_path, aiko, bens)
        with self.assertRaisesRegex(server.RuleBroken, "You have not bookmarked that post."):
            server.remove_bookmark(self.db_path, aiko, first)   # never bookmarked

    def test_your_bookmarks_are_yours_alone(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_bookmark(self.db_path, aiko, bens)
        server.add_bookmark(self.db_path, ben, first)
        self.assertEqual([r["id"] for r in server.bookmarks_for(self.db_path, aiko)], [bens])
        self.assertEqual([r["id"] for r in server.bookmarks_for(self.db_path, ben)], [first])
        # Ben cannot take back Aiko's bookmark: only his own row can be deleted.
        with self.assertRaises(server.RuleBroken):
            server.remove_bookmark(self.db_path, ben, bens)
        self.assertIn((aiko, bens), self.rows("SELECT * FROM bookmarks"))

    def test_a_bookmark_changes_nothing_anyone_else_can_read(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_like(self.db_path, ben, first)
        def public():
            counts, mine = server.likes_for(self.db_path, None)
            return ([tuple(r) for r in server.posts_after(self.db_path, 0)],
                    [tuple(r) for r in counts], [tuple(r) for r in mine],
                    server.posts_to_json(server.posts_after(self.db_path, 0, ben)))
        before = public()
        server.add_bookmark(self.db_path, aiko, first)
        self.assertEqual(public(), before)
        for row in server.posts_after(self.db_path, 0):
            self.assertNotIn("bookmark", " ".join(row.keys()))

    def test_bookmarks_come_newest_post_first_with_names_and_likes(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_like(self.db_path, ben, first)
        for post_id in (first, bens, second):
            server.add_bookmark(self.db_path, aiko, post_id)
        rows = server.bookmarks_for(self.db_path, aiko)
        self.assertEqual([r["id"] for r in rows], [bens, second, first])
        self.assertEqual((rows[0]["author"], rows[0]["display_name"]), ("ben", "Ben Ito"))
        self.assertEqual(rows[2]["like_count"], 1)
        self.assertEqual(server.bookmarks_for(self.db_path, ben), [])

    def test_bookmarks_are_read_through_select_posts(self):
        # So a post this viewer may not see (block, report) is left out too.
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_bookmark(self.db_path, aiko, bens)
        with mock.patch.object(server, "visible_to",
                               lambda viewer: ("posts.author_id != ?", [ben])):
            self.assertEqual(server.bookmarks_for(self.db_path, aiko), [])

    def test_deleting_a_post_deletes_its_bookmarks(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_like(self.db_path, aiko, bens)
        server.add_bookmark(self.db_path, aiko, bens)
        server.add_bookmark(self.db_path, aiko, first)
        connection = server.connect(self.db_path)
        connection.execute("DELETE FROM likes WHERE post_id = ?", (bens,))   # likes do not cascade
        connection.execute("DELETE FROM posts WHERE id = ?", (bens,))
        connection.commit()
        connection.close()
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [(aiko, first)])

    def test_bookmarking_adds_no_user_and_changes_no_like(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_like(self.db_path, aiko, bens)
        users, likes = self.users(), self.rows("SELECT * FROM likes")
        server.add_bookmark(self.db_path, aiko, bens)
        server.remove_bookmark(self.db_path, aiko, bens)
        server.add_bookmark(self.db_path, ben, bens)
        self.assertEqual(self.users(), users)
        self.assertEqual(self.rows("SELECT * FROM likes"), likes)

    def test_the_bookmarks_upgrade_keeps_every_row(self):
        aiko, ben, first, second, bens = self.bookmark_people()
        server.add_like(self.db_path, ben, first)
        connection = sqlite3.connect(self.db_path)
        connection.executescript("DROP TABLE bookmarks; PRAGMA user_version = 4;")
        tables = ("users", "posts", "likes", "sessions", "attempts")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}
        server.upgrade_to_bookmarks(connection)
        connection.close()
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        server.create_tables(self.db_path)   # twice is harmless
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        server.add_bookmark(self.db_path, aiko, bens)
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [(aiko, bens)])

    def test_the_bookmarks_table_cascades_and_has_its_key(self):
        sql = self.rows("SELECT sql FROM sqlite_master WHERE name = 'bookmarks'")[0][0]
        self.assertIn("PRIMARY KEY (user_id, post_id)", sql)
        self.assertEqual(sql.count("ON DELETE CASCADE"), 2)

    # -- japanese: a refusal names its rule by a code --

    def test_a_problem_has_a_code_values_and_the_same_english_as_before(self):
        problem = server.RuleBroken("text_too_long", limit=280)
        self.assertEqual(problem.code, "text_too_long")
        self.assertEqual(problem.values, {"limit": 280})
        self.assertEqual(str(problem), "The post must be 280 characters or fewer.")
        self.assertIsInstance(problem, server.Problem)
        self.assertIsInstance(server.NotSignedIn("login_needed"), server.Problem)

    def test_a_code_that_is_not_in_problems_fails_at_once(self):
        with self.assertRaises(KeyError):
            server.RuleBroken("no_such_code")

    def test_a_refused_post_says_which_rule_by_its_code(self):
        aiko = self.sign_up("aiko")
        with self.assertRaises(server.RuleBroken) as empty:
            server.save_post(self.db_path, aiko, "   ")
        self.assertEqual((empty.exception.code, empty.exception.values), ("text_empty", {}))
        with self.assertRaises(server.RuleBroken) as too_long:
            server.save_post(self.db_path, aiko, "a" * (server.MAX_TEXT + 1))
        self.assertEqual((too_long.exception.code, too_long.exception.values),
                         ("text_too_long", {"limit": server.MAX_TEXT}))

    def test_every_sentence_in_problems_can_be_filled_in(self):
        for code, sentence in server.PROBLEMS.items():
            with self.subTest(code=code):
                self.assertRegex(code, r"^[a-z][a-z0-9_]*$")
                values = {name: "x" for name in value_names(sentence)}
                self.assertNotIn("{", sentence.format(**values))

    def test_words_with_a_number_are_a_pair_chosen_by_count(self):
        for code in server.PROBLEMS:
            for this, other in (("_one", "_other"), ("_other", "_one")):
                if code.endswith(this):
                    with self.subTest(code=code):
                        pair = code[:-len(this)] + other
                        self.assertIn(pair, server.PROBLEMS)
                        self.assertEqual(value_names(server.PROBLEMS[code]) | {"count"},
                                         value_names(server.PROBLEMS[pair]) | {"count"})
        one = server.TooFast("post_too_fast", count=1)
        many = server.TooFast("post_too_fast", count=60)
        self.assertEqual(str(one), "Too many posts. Please try again in 1 second.")
        self.assertEqual(str(many), "Too many posts. Please try again in 60 seconds.")
        self.assertEqual((one.code, one.values, one.retry_after), ("post_too_fast", {"count": 1}, 1))
        with self.assertRaises(KeyError):
            server.Problem("post_too_fast")   # no count: no way to choose

    def test_the_view_sends_the_english_the_code_and_the_values(self):
        problem = server.RuleBroken("text_too_long", limit=280)
        self.assertEqual(server.problem_to_json(problem),
                         {"error": "The post must be 280 characters or fewer.",
                          "code": "text_too_long", "values": {"limit": 280}})

    # -- pictures --

    def picture_post(self, user_id, data=PNG, alt="a small square", text="look"):
        return server.save_post(self.db_path, user_id, text, picture=as_base64(data),
                                picture_alt=alt)

    def picture_counts(self):
        return (self.rows("SELECT COUNT(*) FROM posts")[0][0],
                self.rows("SELECT COUNT(*) FROM pictures")[0][0])

    def test_each_kind_of_picture_is_found_from_its_first_bytes(self):
        for data, kind in ((PNG, "png"), (JPEG, "jpeg"), (GIF, "gif"), (WEBP, "webp")):
            with self.subTest(kind=kind):
                self.assertEqual(server.picture_kind(data), kind)
                self.assertEqual(server.check_picture(as_base64(data)), (kind, data))
        self.assertEqual(set(server.PICTURE_TYPES), {"png", "jpeg", "gif", "webp"})

    def test_a_file_that_is_not_a_picture_is_refused(self):
        for name, data in NOT_PICTURES.items():
            with self.subTest(file=name):
                self.assertIsNone(server.picture_kind(data))
                with self.assertRaises(server.RuleBroken) as caught:
                    server.check_picture(as_base64(data))
                self.assertIn("PNG, JPEG, GIF or WebP", str(caught.exception))
                self.assertEqual(caught.exception.code, "picture_wrong_kind")

    def test_a_picture_at_the_size_limit_is_kept_and_one_byte_more_is_refused(self):
        aiko = self.person("aiko")
        biggest = PNG + bytes(server.MAX_PICTURE_BYTES - len(PNG))
        post = self.picture_post(aiko, biggest)
        self.assertEqual(server.picture_for(self.db_path, post["id"])["bytes"], biggest)
        with self.assertRaises(server.RuleBroken) as caught:
            self.picture_post(aiko, biggest + b"\x00")
        self.assertIn("2 MB", str(caught.exception))
        self.assertEqual((caught.exception.code, caught.exception.values),
                         ("picture_too_big", {"limit": 2}))

    def test_bad_base64_a_data_start_and_a_tiny_file_are_refused(self):
        for picture in ("not base64 at all!", "data:image/png;base64," + as_base64(PNG),
                        as_base64(PNG) + "\n", "", 12345, ["a"], as_base64(b"\xff\xd8\xff")):
            with self.subTest(picture=str(picture)[:30]):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.check_picture(picture)
                self.assertEqual(str(caught.exception), "The picture could not be read.")

    def test_the_rules_for_the_description(self):
        aiko = self.person("aiko")
        for alt in ("", "   ", None, 7, "a" * (server.MAX_ALT_TEXT + 1), "two\nlines",
                    "turned \u202earound"):
            with self.subTest(alt=alt):
                with self.assertRaises(server.RuleBroken):
                    self.picture_post(aiko, alt=alt)
        post = self.picture_post(aiko, alt="  " + "a" * server.MAX_ALT_TEXT + "  ")
        self.assertEqual(server.post_to_json(post)["picture"]["alt"], "a" * server.MAX_ALT_TEXT)

    def test_a_description_without_a_picture_is_refused(self):
        aiko = self.person("aiko")
        with self.assertRaises(server.RuleBroken) as caught:
            server.save_post(self.db_path, aiko, "hello", picture_alt="a cat")
        self.assertEqual(str(caught.exception), "Please choose a picture for this description.")

    def test_no_picture_only_posts(self):
        aiko = self.person("aiko")
        with self.assertRaises(server.RuleBroken):
            self.picture_post(aiko, text="   ")

    def test_a_broken_rule_saves_nothing_and_uses_no_allowance(self):
        aiko = self.person("aiko")
        for data, alt in ((NOT_PICTURES["svg"], "a picture"), (PNG, ""), (GIF, "x" * 201)):
            with self.assertRaises(server.RuleBroken):
                self.picture_post(aiko, data, alt)
        self.assertEqual(self.picture_counts(), (0, 0))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM attempts"), [(0,)])

    def test_the_bytes_read_back_are_the_bytes_sent(self):
        aiko = self.person("aiko")
        for data, kind in ((PNG, "png"), (JPEG, "jpeg"), (GIF, "gif"), (WEBP, "webp")):
            with self.subTest(kind=kind):
                post = self.picture_post(aiko, data)
                picture = server.picture_for(self.db_path, post["id"])
                self.assertEqual((picture["kind"], picture["bytes"]), (kind, data))
                self.assertEqual(server.post_to_json(post)["picture"],
                                 {"url": "/pictures/" + str(post["id"]), "alt": "a small square"})

    def test_a_post_with_a_picture_counts_as_one_post(self):
        use_fake_clock(self)
        aiko = self.person("aiko")
        self.picture_post(aiko)
        self.assertEqual(self.rows("SELECT action, key FROM attempts"), [("post", str(aiko))])

    def test_a_post_without_a_picture_has_none_and_no_query_reads_the_bytes(self):
        aiko = self.person("aiko")
        plain = self.post_by(aiko)
        self.picture_post(aiko)
        rows = server.posts_after(self.db_path, 0)
        self.assertEqual([server.post_to_json(row)["picture"] is None for row in rows],
                         [True, False])
        for row in rows:
            self.assertNotIn("bytes", row.keys())
        self.assertIsNone(server.picture_for(self.db_path, plain))
        self.assertIsNone(server.picture_for(self.db_path, 999))

    def test_the_database_itself_refuses_a_bad_picture(self):
        aiko = self.person("aiko")
        post = self.picture_post(aiko)["id"]
        plain = self.post_by(aiko)
        bad = [
            ("a second picture", post, "png", "a", PNG),
            ("svg", plain, "svg", "a", PNG),
            ("too many bytes", plain, "png", "a", PNG + bytes(server.MAX_PICTURE_BYTES)),
            ("too few bytes", plain, "png", "a", PNG[:11]),
            ("text, not bytes", plain, "png", "a", "x" * 100),
            ("no description", plain, "png", "", PNG),
            ("no such post", 999, "png", "a", PNG),
        ]
        for what, post_id, kind, alt, data in bad:
            with self.subTest(what=what):
                connection = server.connect(self.db_path)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO pictures (post_id, kind, alt_text, bytes) "
                                       "VALUES (?, ?, ?, ?)", (post_id, kind, alt, data))
                connection.close()

    def test_the_numbers_in_the_table_are_the_model_s(self):
        sql = self.rows("SELECT sql FROM sqlite_master WHERE name = 'pictures'")[0][0]
        self.assertEqual(re.search(r"length\(bytes\) BETWEEN (\d+) AND (\d+)", sql).groups(),
                         (str(server.MIN_PICTURE_BYTES), str(server.MAX_PICTURE_BYTES)))
        self.assertIn(f"length(alt_text) BETWEEN 1 AND {server.MAX_ALT_TEXT}", sql)
        self.assertEqual(server.MAX_PICTURE_MB * 1024 * 1024, server.MAX_PICTURE_BYTES)
        for kind in server.PICTURE_TYPES:
            self.assertIn(f"'{kind}'", sql)

    def test_deleting_a_post_deletes_its_picture(self):
        aiko = self.person("aiko")
        post = self.picture_post(aiko)["id"]
        connection = server.connect(self.db_path)
        connection.execute("DELETE FROM posts WHERE id = ?", (post,))
        connection.commit()
        connection.close()
        self.assertEqual(self.picture_counts(), (0, 0))

    def test_a_post_the_viewer_may_not_see_has_no_picture(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        post = self.picture_post(aiko)["id"]
        # As block will: Ben may not see Aiko's posts. visible_to is the one
        # place that decides, so the picture must follow it too.
        hide_aiko_from_ben = lambda viewer: ("posts.author_id != ? OR ? IS NULL",
                                             [aiko if viewer == ben else 0, viewer])
        with mock.patch.object(server, "visible_to", hide_aiko_from_ben):
            self.assertIsNone(server.picture_for(self.db_path, post, ben))
            self.assertEqual(server.picture_for(self.db_path, post, aiko)["bytes"], PNG)
            self.assertEqual(server.picture_for(self.db_path, post, None)["bytes"], PNG)

    def test_the_pictures_upgrade_keeps_every_row(self):
        # A version-6 database (before pictures) with rows in every table.
        aiko = self.sign_up("aiko")
        ben = self.person("ben")
        post_id = self.post_by(aiko)
        server.add_like(self.db_path, ben, post_id)
        connection = sqlite3.connect(self.db_path)
        connection.executescript("DROP TABLE pictures; PRAGMA user_version = 6;")
        connection.close()
        tables = ("users", "posts", "likes", "sessions", "attempts", "bookmarks")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}
        server.create_tables(self.db_path)
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("SELECT * FROM pictures"), [])
        self.assertIsNone(server.post_to_json(server.posts_after(self.db_path, 0)[0])["picture"])
        self.picture_post(aiko)
        server.create_tables(self.db_path)   # twice is harmless
        self.assertEqual(self.picture_counts(), (2, 1))

    # -- block --
    #
    # People are made with SQL (self.person), so no test hashes a password.

    def authors_seen_by(self, viewer_id):
        return [row["author"] for row in server.posts_after(self.db_path, 0, viewer_id)]

    def block_rows(self):
        return self.rows("SELECT blocker_id, blocked_id FROM blocks ORDER BY 1, 2")

    def test_a_blocked_person_s_posts_are_left_out_only_for_the_blocker(self):
        aiko, ben, carol = self.person("aiko"), self.person("ben"), self.person("carol")
        self.post_by(aiko, "a1")
        self.post_by(ben, "b1")
        server.add_block(self.db_path, aiko, "ben")
        self.assertEqual(self.authors_seen_by(aiko), ["aiko"])
        self.assertEqual(self.authors_seen_by(carol), ["aiko", "ben"])
        self.assertEqual(self.authors_seen_by(None), ["aiko", "ben"])
        # Decision 1: Ben still reads Aiko's posts.
        self.assertEqual(self.authors_seen_by(ben), ["aiko", "ben"])
        # A post Ben writes after the block never comes to Aiko either.
        later = self.post_by(ben, "b2")
        self.assertEqual(server.posts_after(self.db_path, later - 1, aiko), [])

    def test_the_block_is_inside_visible_to(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        self.post_by(aiko)
        self.post_by(ben)
        server.add_block(self.db_path, aiko, "ben")
        sql, params = server.visible_to(aiko)
        self.assertEqual(self.rows("SELECT id FROM posts WHERE " + sql, params), [(1,)])
        sql, params = server.visible_to(None)
        self.assertEqual(self.rows("SELECT id FROM posts WHERE " + sql, params), [(1,), (2,)])

    def test_nobody_can_block_themselves(self):
        aiko = self.person("aiko")
        with self.assertRaises(server.RuleBroken) as caught:
            server.add_block(self.db_path, aiko, "AIKO")
        self.assertEqual(str(caught.exception), "You cannot block yourself.")
        # The database refuses it too, even if the model is got around.
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO blocks VALUES (?, ?)", (aiko, aiko))
        connection.close()
        self.assertEqual(self.block_rows(), [])

    def test_the_same_block_twice_is_refused(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        server.add_block(self.db_path, aiko, "ben")
        with self.assertRaises(server.RuleBroken) as caught:
            server.add_block(self.db_path, aiko, "ben")
        self.assertEqual(str(caught.exception), "You have already blocked @ben.")
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO blocks VALUES (?, ?)", (aiko, ben))
        connection.close()
        self.assertEqual(self.block_rows(), [(aiko, ben)])

    def test_blocking_an_account_that_does_not_exist_adds_no_user(self):
        aiko = self.person("aiko")
        before = self.users()
        for name, words in (("nobody", "There is no account @nobody."),
                            ("", "must not be empty"), ("two words", "only letters")):
            with self.subTest(name=name):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.add_block(self.db_path, aiko, name)
                self.assertIn(words, str(caught.exception))
        with self.assertRaises(server.RuleBroken):
            server.remove_block(self.db_path, aiko, "nobody")
        self.assertEqual(self.users(), before)
        self.assertEqual(self.block_rows(), [])

    def test_capitals_do_not_matter(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        blocked = server.add_block(self.db_path, aiko, "BEN")
        self.assertEqual(blocked["name"], "ben")
        self.assertEqual(self.block_rows(), [(aiko, ben)])

    def test_unblocking_deletes_the_row_and_brings_the_old_posts_back(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        self.post_by(ben, "old")
        server.add_block(self.db_path, aiko, "ben")
        self.assertEqual(self.authors_seen_by(aiko), [])
        server.remove_block(self.db_path, aiko, "ben")
        self.assertEqual(self.block_rows(), [])
        self.assertEqual(self.authors_seen_by(aiko), ["ben"])
        with self.assertRaises(server.RuleBroken) as caught:
            server.remove_block(self.db_path, aiko, "ben")
        self.assertEqual(str(caught.exception), "You have not blocked @ben.")

    def test_a_blocked_person_cannot_like_the_blocker_s_posts(self):
        aiko, ben, carol = self.person("aiko"), self.person("ben"), self.person("carol")
        first = self.post_by(aiko, "first")
        second = self.post_by(aiko, "second")
        carols = self.post_by(carol)
        self.like(ben, first)                     # before the block
        server.add_block(self.db_path, aiko, "ben")
        with self.assertRaises(server.RuleBroken) as caught:
            server.add_like(self.db_path, ben, second)
        self.assertEqual(str(caught.exception), "You cannot like this post.")
        self.assertEqual(self.rows("SELECT * FROM likes WHERE post_id = ?", (second,)), [])
        self.like(ben, carols)                    # someone else's post is fine
        # Decision 3: the like from before stays, and is counted for everyone.
        self.assertEqual(server.posts_after(self.db_path, 0, carol)[0]["like_count"], 1)
        # A blocked person may still take back a like they gave before.
        self.assertEqual(server.remove_like(self.db_path, ben, first), (first, 0))
        # Aiko may still like Ben's posts: the rule is only one way.
        self.like(aiko, self.post_by(ben))

    def test_check_not_blocked_by_author_names_what_was_refused(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        post = self.post_by(aiko)
        server.add_block(self.db_path, aiko, "ben")
        connection = server.connect(self.db_path)
        try:
            server.check_not_blocked_by_author(connection, post, aiko)   # the author: fine
            with self.assertRaises(server.RuleBroken) as caught:
                server.check_not_blocked_by_author(connection, post, ben)
            self.assertEqual(caught.exception.code, "like_blocked")
            # replies adds "reply" to BLOCKED_CODES; a name not there is a mistake in the code.
            with self.assertRaises(KeyError):
                server.check_not_blocked_by_author(connection, post, ben, "nothing")
        finally:
            connection.close()

    def test_blocks_for_lists_exactly_the_people_this_person_blocked(self):
        aiko, ben, carol = self.person("aiko"), self.person("ben", "Ben Ito"), self.person("Carol")
        server.add_block(self.db_path, aiko, "carol")
        server.add_block(self.db_path, aiko, "ben")
        server.add_block(self.db_path, ben, "aiko")
        self.assertEqual([tuple(row) for row in server.blocks_for(self.db_path, aiko)],
                         [("ben", "Ben Ito"), ("Carol", "Carol")])
        self.assertEqual(self.names(server.blocks_for(self.db_path, carol)), [])
        self.assertEqual(server.blocks_to_json(server.blocks_for(self.db_path, ben)),
                         {"blocked": [{"account_name": "aiko", "display_name": "aiko"}]})

    def test_a_block_on_an_old_name_holds_after_it_is_claimed(self):
        aiko = self.person("aiko")
        old_ben = self.person("ben")   # an old user: no password yet
        self.post_by(old_ben, "old post")
        server.add_block(self.db_path, aiko, "ben")
        claimed = self.sign_up("Ben")
        self.assertEqual(claimed, old_ben)
        self.post_by(claimed, "new post")
        self.assertEqual(self.authors_seen_by(aiko), [])

    def test_who_liked_leaves_out_blocked_names_but_keeps_the_count(self):
        aiko, ben, carol = self.person("aiko"), self.person("ben"), self.person("carol")
        post = self.post_by(carol)
        self.like(ben, post)
        self.like(carol, post)
        server.add_block(self.db_path, aiko, "ben")
        post_id, rows, count = server.who_liked(self.db_path, post, aiko)
        self.assertEqual((self.names(rows), count), (["carol"], 2))
        post_id, rows, count = server.who_liked(self.db_path, post, carol)
        self.assertEqual((self.names(rows), count), (["ben", "carol"], 2))
        self.assertEqual(self.names(server.who_liked(self.db_path, post)[1]), ["ben", "carol"])
        summary = self.summary(aiko, post)
        self.assertEqual((self.names(summary["leaders"]), summary["like_count"]), (["carol"], 2))
        # Carol is more popular (Ben liked her post), so she comes first.
        self.assertEqual(self.leaders(None, post), ["carol", "ben"])

    def test_the_block_upgrade_keeps_every_row(self):
        aiko = self.sign_up("aiko")
        ben = self.person("ben")
        post_id = self.post_by(aiko)
        server.add_like(self.db_path, ben, post_id)
        # The database as it was one version before: no blocks table.
        connection = sqlite3.connect(self.db_path)
        # (block is version 8; replies, version 9, runs again harmlessly.)
        connection.executescript("DROP TABLE blocks; PRAGMA user_version = 7;")
        connection.close()
        tables = ("users", "posts", "likes", "sessions", "attempts")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}
        server.create_tables(self.db_path)
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.block_rows(), [])
        server.add_block(self.db_path, aiko, "ben")
        self.assertEqual(self.block_rows(), [(aiko, ben)])

    def test_a_blocked_person_s_posts_are_in_no_search_and_no_bookmarks(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        aikos = self.post_by(aiko, "a cat by aiko")
        bens = self.post_by(ben, "a cat by ben")
        server.add_bookmark(self.db_path, aiko, aikos)
        server.add_bookmark(self.db_path, aiko, bens)    # saved before the block
        server.add_block(self.db_path, aiko, "ben")
        rows, more = server.search_posts(self.db_path, "cat", aiko)
        self.assertEqual([row["author"] for row in rows], ["aiko"])
        rows, more = server.search_posts(self.db_path, "cat", None)
        self.assertEqual([row["author"] for row in rows], ["ben", "aiko"])
        self.assertEqual([row["id"] for row in server.bookmarks_for(self.db_path, aiko)],
                         [aikos])
        # The bookmark row is kept: after an unblock the post is in the list again.
        self.assertEqual(len(self.rows("SELECT * FROM bookmarks")), 2)
        self.assertEqual(server.posts_before(self.db_path, 0, aiko)[0]["author"], "aiko")
        server.remove_block(self.db_path, aiko, "ben")
        self.assertEqual([row["id"] for row in server.bookmarks_for(self.db_path, aiko)],
                         [bens, aikos])

    def test_every_block_refusal_has_a_code(self):
        aiko, ben = self.person("aiko"), self.person("ben")
        post = self.post_by(aiko)
        server.add_block(self.db_path, aiko, "ben")
        for code, action in (("account_missing", lambda: server.add_block(self.db_path, aiko, "x")),
                             ("block_self", lambda: server.add_block(self.db_path, aiko, "aiko")),
                             ("block_already", lambda: server.add_block(self.db_path, aiko, "ben")),
                             ("block_not_there",
                              lambda: server.remove_block(self.db_path, ben, "aiko")),
                             ("like_blocked", lambda: server.add_like(self.db_path, ben, post))):
            with self.subTest(code=code):
                with self.assertRaises(server.RuleBroken) as caught:
                    action()
                self.assertEqual(caught.exception.code, code)


    # -- replies: a post that answers another post --

    def reply_by(self, user_id, parent_id, text="an answer"):
        return server.save_reply(self.db_path, user_id, text, parent_id, now=SOME_MOMENT)

    def test_a_reply_is_saved_with_its_parent_and_comes_back_with_the_parent_s_name(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        ken = self.sign_up("ken")
        post = server.save_post(self.db_path, aiko, "lunch?", now=SOME_MOMENT)
        reply = self.reply_by(ken, post["id"], "yes!")
        self.assertEqual((reply["parent_id"], reply["parent_author"], reply["author"]),
                         (post["id"], "aiko", "ken"))
        self.assertEqual(self.rows("SELECT id, author_id, parent_id FROM posts ORDER BY id"),
                         [(1, aiko, None), (2, ken, 1)])
        posts = server.posts_to_json(server.posts_after(self.db_path, 0))
        self.assertEqual([(p["id"], p["parent_id"], p["parent_author"]) for p in posts],
                         [(1, None, None), (2, 1, "aiko")])
        # The count and the newest reply counted, from the rows.
        self.assertEqual([(p["reply_count"], p["newest_reply_id"]) for p in posts],
                         [(1, 2), (0, None)])

    def test_a_reply_to_a_post_that_does_not_exist_is_refused(self):
        aiko = self.sign_up("aiko")
        with self.assertRaisesRegex(server.RuleBroken, "That post does not exist."):
            self.reply_by(aiko, 99)
        self.assertEqual(self.rows("SELECT * FROM posts"), [])

    def test_a_reply_to_a_reply_is_refused_by_the_rule_and_by_the_database(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        reply = self.reply_by(aiko, post["id"])
        with self.assertRaisesRegex(server.RuleBroken, "only reply to a post, not to a reply"):
            self.reply_by(aiko, reply["id"])
        # Even written straight in SQL, past every rule, the trigger refuses it.
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO posts (author_id, text, posted_at, parent_id) "
                               "VALUES (?, 'x', '2026-10-02T07:42:10Z', ?)", (aiko, reply["id"]))
        connection.close()
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 2)

    def test_a_parent_id_that_is_not_a_post_id_is_refused(self):
        aiko = self.sign_up("aiko")
        server.save_post(self.db_path, aiko, "a post")
        for wrong in ("abc", [], {}, True, 1.5, -1, "", "1; DROP TABLE posts", 10 ** 30):
            with self.subTest(parent_id=wrong):
                with self.assertRaisesRegex(server.RuleBroken, "which post it answers"):
                    self.reply_by(aiko, wrong)
        self.assertEqual(server.check_parent_id("1"), 1)
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 1)

    def test_you_may_reply_to_your_own_post(self):
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        self.assertEqual(self.reply_by(aiko, post["id"])["parent_author"], "aiko")

    def test_a_reply_follows_the_text_rules(self):
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        for text in ("", "   ", "x" * (server.MAX_TEXT + 1)):
            with self.subTest(length=len(text)):
                with self.assertRaises(server.RuleBroken):
                    self.reply_by(aiko, post["id"], text)
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 1)

    def test_the_reply_count_is_the_number_of_rows_and_is_never_kept(self):
        use_fake_clock(self)
        aiko = self.sign_up("aiko")
        ken = self.sign_up("ken")
        post = server.save_post(self.db_path, aiko, "a post")
        self.reply_by(ken, post["id"])
        self.reply_by(aiko, post["id"])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts WHERE parent_id = ?",
                                   (post["id"],)), [(2,)])
        self.assertEqual(server.posts_after(self.db_path, 0)[0]["reply_count"], 2)
        columns = [row[1] for row in self.rows("PRAGMA table_info(posts)")]
        self.assertFalse([c for c in columns if "count" in c])

    def test_the_database_refuses_to_delete_a_post_that_has_a_reply(self):
        # The contract for edit-delete: it asks has_replies first.
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        lonely = server.save_post(self.db_path, aiko, "nobody answers")
        self.reply_by(aiko, post["id"])
        connection = server.connect(self.db_path)
        self.assertTrue(server.has_replies(connection, post["id"]))
        self.assertFalse(server.has_replies(connection, lonely["id"]))
        self.assertFalse(server.has_replies(connection, 99))
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM posts WHERE id = ?", (post["id"],))
        connection.close()
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 3)

    def test_a_reply_is_counted_by_the_post_rate_limit(self):
        clock = use_fake_clock(self)
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        # A refused reply is not counted.
        with self.assertRaises(server.RuleBroken):
            self.reply_by(aiko, 99)
        for _ in range(4):
            self.reply_by(aiko, post["id"])
        with self.assertRaises(server.TooFast):
            self.reply_by(aiko, post["id"])
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 5)
        clock.move(61)
        self.reply_by(aiko, post["id"])

    def test_the_replies_upgrade_keeps_every_post_with_no_parent(self):
        users, posts, likes = self.use_an_old_database()
        self.assertEqual(self.rows("SELECT id, author_id, text, old_clock_time, parent_id "
                                   "FROM posts ORDER BY id"),
                         [row + (None,) for row in posts])
        self.assertEqual(self.rows("SELECT * FROM likes ORDER BY post_id, user_id"), likes)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("SELECT type, name FROM sqlite_master "
                                   "WHERE name IN ('posts_by_parent', 'replies_are_one_level') "
                                   "ORDER BY name"),
                         [("index", "posts_by_parent"), ("trigger", "replies_are_one_level")])
        server.create_tables(self.db_path)   # twice is harmless
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 3)

    def test_rebuilding_posts_keeps_the_one_level_rule(self):
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        reply = self.reply_by(aiko, post["id"])
        connection = server.connect(self.db_path)
        server.rebuild_table(connection, "posts", lambda sql: sql[:-1] + ", note TEXT)")
        connection.close()
        with self.assertRaisesRegex(server.RuleBroken, "not to a reply"):
            self.reply_by(aiko, reply["id"])
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            server.insert_post(connection, aiko, "x", parent_id=reply["id"])
        connection.close()

    def test_a_blocked_person_cannot_reply_and_their_replies_are_not_counted(self):
        use_fake_clock(self)
        aiko, ben, carol = self.sign_up("aiko"), self.sign_up("ben"), self.sign_up("carol")
        post = server.save_post(self.db_path, aiko, "a post")
        self.reply_by(ben, post["id"])
        self.reply_by(carol, post["id"])
        server.add_block(self.db_path, aiko, "ben")
        # Ben can no longer answer Aiko's posts.
        with self.assertRaises(server.RuleBroken) as caught:
            self.reply_by(ben, post["id"])
        self.assertEqual(caught.exception.code, "reply_blocked")
        # Aiko does not see Ben's reply, so it is not in her count. Everyone
        # else (Carol, or nobody logged in) still counts both.
        for viewer, count, newest in ((aiko, 1, 3), (carol, 2, 3), (None, 2, 3)):
            with self.subTest(viewer=viewer):
                first = server.posts_after(self.db_path, 0, viewer)[0]
                self.assertEqual((first["reply_count"], first["newest_reply_id"]),
                                 (count, newest))
        server.add_block(self.db_path, aiko, "carol")
        first = server.posts_after(self.db_path, 0, aiko)[0]
        self.assertEqual((first["reply_count"], first["newest_reply_id"]), (0, None))
        # The rows are all still there: a block hides, it never deletes.
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts WHERE parent_id = 1"), [(2,)])

    def test_a_reply_may_say_where_it_was_written(self):
        aiko = self.sign_up("aiko")
        post = server.save_post(self.db_path, aiko, "a post")
        reply = server.save_reply(self.db_path, aiko, "from Kyoto", post["id"], place="Kyoto")
        self.assertEqual((reply["place"], reply["parent_id"]), ("Kyoto", post["id"]))
        with self.assertRaises(server.RuleBroken):
            server.save_reply(self.db_path, aiko, "x", post["id"], place="x" * 41)

    # -- edit-delete --

    def edit_delete_people(self):
        """Aiko and Ben, fixed clocks, and one post by Aiko that Ben liked. Return all three."""
        self.clock = use_fake_clock(self)
        patcher = mock.patch.object(server, "utc_now", lambda: SOME_MOMENT)
        patcher.start()
        self.addCleanup(patcher.stop)
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        post_id = self.post_by_ed(aiko, "first words")["id"]
        server.add_like(self.db_path, ben, post_id)
        return aiko, ben, post_id

    def post_by_ed(self, user_id, text, **more):
        """A new post. The fake clock moves a minute first, so the rate limit never counts."""
        self.clock.move(61)
        return server.save_post(self.db_path, user_id, text, **more)

    def reply_by_ed(self, user_id, parent_id, text="an answer"):
        self.clock.move(61)
        return server.save_reply(self.db_path, user_id, text, parent_id)

    def refused_code(self, kind, function, *arguments):
        with self.assertRaises(kind) as caught:
            function(*arguments)
        return caught.exception.code

    def test_the_author_can_edit_and_the_old_words_are_kept(self):
        aiko, ben, post_id = self.edit_delete_people()
        row = server.edit_post(self.db_path, aiko, post_id, "  second words  ")
        post = server.post_to_json(row)
        self.assertEqual((post["text"], post["edited"], post["deleted"], post["like_count"]),
                         ("second words", True, False, 1))
        self.assertEqual(self.rows("SELECT post_id, text, replaced_at FROM post_versions"),
                         [(post_id, "first words", "2026-10-02T07:42:10Z")])
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(post_id, ben)])
        server.edit_post(self.db_path, aiko, post_id, "third words")
        self.assertEqual([v["text"] for v in server.versions_of(self.db_path, str(post_id))],
                         ["first words", "second words"])
        other = self.post_by_ed(ben, "never edited")
        self.assertFalse(server.post_to_json(other)["edited"])
        self.assertEqual(server.versions_of(self.db_path, other["id"]), [])
        self.assertEqual(server.versions_of(self.db_path, 999), [])

    def test_an_edit_follows_the_rules_of_a_new_post(self):
        aiko, ben, post_id = self.edit_delete_people()
        for text, code in (("   ", "text_empty"), ("x" * (server.MAX_TEXT + 1), "text_too_long"),
                           ("first words", "edit_unchanged")):
            with self.subTest(code=code):
                self.assertEqual(self.refused_code(server.RuleBroken, server.edit_post,
                                                   self.db_path, aiko, post_id, text), code)
        self.assertEqual(self.refused_code(server.RuleBroken, server.edit_post,
                                           self.db_path, aiko, 999, "no such post"),
                         "post_missing")
        for post_id_sent in (None, "x", True, [1], 2.5):
            with self.subTest(post_id=post_id_sent):
                self.assertEqual(self.refused_code(server.RuleBroken, server.edit_post,
                                                   self.db_path, aiko, post_id_sent, "hi"),
                                 "post_id_missing")
        self.assertEqual(server.edit_post(self.db_path, aiko, post_id, "x" * server.MAX_TEXT)
                         ["text"], "x" * server.MAX_TEXT)
        self.assertEqual(len(self.rows("SELECT * FROM post_versions")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM changes")), 1)

    def test_nobody_else_can_edit_or_delete_a_post(self):
        aiko, ben, post_id = self.edit_delete_people()
        tables = ("posts", "likes", "post_versions", "changes")
        before = {table: self.rows("SELECT * FROM " + table) for table in tables}
        self.assertEqual(self.refused_code(server.NotAllowed, server.edit_post,
                                           self.db_path, ben, post_id, "Ben's words"),
                         "post_not_yours")
        self.assertEqual(self.refused_code(server.NotAllowed, server.delete_post,
                                           self.db_path, ben, post_id), "post_not_yours")
        self.assertEqual({table: self.rows("SELECT * FROM " + table) for table in tables},
                         before)

    def test_the_author_can_delete_and_nothing_of_it_stays(self):
        aiko, ben, post_id = self.edit_delete_people()
        server.edit_post(self.db_path, aiko, post_id, "edited words")
        server.add_bookmark(self.db_path, ben, post_id)
        pictured = self.post_by_ed(aiko, "with a picture", picture=as_base64(PNG),
                                   picture_alt="a dot")["id"]
        self.assertEqual(server.delete_post(self.db_path, aiko, post_id), (post_id, None))
        self.assertEqual(server.delete_post(self.db_path, aiko, pictured), (pictured, None))
        for table in ("posts", "likes", "post_versions", "bookmarks", "pictures"):
            with self.subTest(table=table):
                self.assertEqual(self.rows("SELECT COUNT(*) FROM " + table), [(0,)])
        self.assertEqual(self.rows("SELECT post_id, kind FROM changes ORDER BY id"),
                         [(post_id, "edited"), (post_id, "deleted"), (pictured, "deleted")])
        for value in all_values_in(self.db_path):
            self.assertNotIn("words", value)
        self.assertEqual(self.refused_code(server.RuleBroken, server.delete_post,
                                           self.db_path, aiko, post_id), "post_missing")

    def test_the_id_of_a_deleted_post_is_never_given_again(self):
        aiko, ben, post_id = self.edit_delete_people()
        third = self.post_by_ed(aiko, "three")["id"]
        server.delete_post(self.db_path, aiko, third)
        self.assertEqual(self.post_by_ed(aiko, "four")["id"], third + 1)

    def test_the_changes_feed(self):
        aiko, ben, post_id = self.edit_delete_people()
        self.assertEqual(server.changes_after(self.db_path, None), (0, []))
        server.edit_post(self.db_path, aiko, post_id, "new words")
        self.assertEqual(server.changes_after(self.db_path, None), (1, []))
        latest, rows = server.changes_after(self.db_path, "0")
        self.assertEqual([(c["id"], c["post_id"], c["kind"], p["text"]) for c, p in rows],
                         [(1, post_id, "edited", "new words")])
        server.delete_post(self.db_path, aiko, post_id)
        latest, rows = server.changes_after(self.db_path, "1")
        self.assertEqual((latest, [(c["kind"], p) for c, p in rows]), (2, [("deleted", None)]))
        # Edited, then deleted: both changes now bring no post.
        latest, rows = server.changes_after(self.db_path, "0")
        self.assertEqual(server.changes_to_json(latest, rows)["changes"],
                         [{"id": 1, "post_id": post_id, "kind": "edited", "post": None},
                          {"id": 2, "post_id": post_id, "kind": "deleted", "post": None}])
        for after in ("x", "-1", "1.5", ""):
            with self.subTest(after=after):
                self.assertEqual(self.refused_code(server.RuleBroken, server.changes_after,
                                                   self.db_path, after), "id_bound_not_number")

    def test_a_change_shows_the_post_as_this_viewer_may_see_it(self):
        # block: Ben blocked Aiko, so her edited post comes to him as None.
        aiko, ben, post_id = self.edit_delete_people()
        server.add_block(self.db_path, ben, "aiko")
        server.edit_post(self.db_path, aiko, post_id, "new words")
        self.assertEqual([p for c, p in server.changes_after(self.db_path, "0", ben)[1]], [None])
        self.assertEqual([p["text"] for c, p in server.changes_after(self.db_path, "0")[1]],
                         ["new words"])
        self.assertEqual(server.versions_of(self.db_path, post_id, ben), [])

    def test_record_change_refuses_a_kind_it_does_not_know(self):
        aiko, ben, post_id = self.edit_delete_people()
        connection = server.connect(self.db_path)
        with self.assertRaises(ValueError):
            server.record_change(connection, post_id, "renamed")
        connection.close()
        self.assertEqual(self.rows("SELECT * FROM changes"), [])

    def test_a_post_with_replies_is_kept_as_deleted_until_its_last_reply_goes(self):
        aiko, ben, post_id = self.edit_delete_people()
        server.edit_post(self.db_path, aiko, post_id, "edited words")
        server.add_bookmark(self.db_path, ben, post_id)
        reply_id = self.reply_by_ed(ben, post_id)["id"]
        other_reply = self.reply_by_ed(aiko, post_id)["id"]

        # 1. Aiko deletes her post. It has replies, so its row stays, with nothing in it.
        deleted_id, row = server.delete_post(self.db_path, aiko, post_id)
        post = server.post_to_json(row)
        self.assertEqual((post["text"], post["place"], post["deleted"], post["edited"],
                          post["like_count"], post["reply_count"], post["picture"]),
                         ("", None, True, False, 0, 2, None))
        self.assertEqual(self.rows("SELECT text, place, deleted_at FROM posts WHERE id = ?",
                                   (post_id,)), [("", None, "2026-10-02T07:42:10Z")])
        for table in ("likes", "post_versions", "bookmarks"):
            with self.subTest(table=table):
                self.assertEqual(self.rows("SELECT COUNT(*) FROM " + table), [(0,)])
        self.assertEqual(self.rows("SELECT parent_id FROM posts WHERE id IN (?, ?)",
                                   (reply_id, other_reply)), [(post_id,), (post_id,)])
        # 2. It can no longer be edited, deleted, liked, saved, answered or found.
        for function, arguments, code in (
                (server.edit_post, (aiko, post_id, "back again"), "post_deleted"),
                (server.delete_post, (aiko, post_id), "post_deleted"),
                (server.add_like, (ben, post_id), "post_missing"),
                (server.add_bookmark, (ben, post_id), "post_missing"),
                (self.reply_by_ed, (ben, post_id), "reply_to_deleted")):
            with self.subTest(code=code, function=function.__name__):
                if function == self.reply_by_ed:
                    self.assertEqual(self.refused_code(server.RuleBroken, function, *arguments),
                                     code)
                else:
                    self.assertEqual(self.refused_code(server.RuleBroken, function,
                                                       self.db_path, *arguments), code)
        self.assertEqual(server.search_posts(self.db_path, "words"), ([], False))
        # 3. Ben deletes his reply: Aiko's post has another reply, so it stays,
        #    and it is told its reply count changed.
        server.delete_post(self.db_path, ben, reply_id)
        self.assertEqual(self.rows("SELECT post_id, kind FROM changes WHERE id > 1 ORDER BY id"),
                         [(post_id, "deleted"), (reply_id, "deleted"),
                          (post_id, "replies_changed")])
        latest, rows = server.changes_after(self.db_path, "3")
        self.assertEqual([(c["kind"], p["reply_count"]) for c, p in rows],
                         [("replies_changed", 1)])
        # 4. The last reply goes: nothing is left to keep the post for, so it goes too.
        server.delete_post(self.db_path, aiko, other_reply)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts"), [(0,)])
        latest, rows = server.changes_after(self.db_path, str(latest))
        self.assertEqual([(c["post_id"], c["kind"], p) for c, p in rows],
                         [(other_reply, "deleted", None), (post_id, "deleted", None)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_deleting_a_reply_changes_its_post_s_count(self):
        aiko, ben, post_id = self.edit_delete_people()
        reply_id = self.reply_by_ed(ben, post_id)["id"]
        server.delete_post(self.db_path, ben, reply_id)
        latest, rows = server.changes_after(self.db_path, "0")
        self.assertEqual([(c["post_id"], c["kind"]) for c, p in rows],
                         [(reply_id, "deleted"), (post_id, "replies_changed")])
        self.assertEqual((rows[1][1]["reply_count"], rows[1][1]["deleted"]), (0, False))

    def test_the_database_refuses_a_deleted_post_that_keeps_words(self):
        aiko, ben, post_id = self.edit_delete_people()
        connection = server.connect(self.db_path)
        for sql in ("UPDATE posts SET deleted_at = '2026-10-02T07:42:10Z'",
                    "UPDATE posts SET text = '', place = 'Osaka', "
                    "deleted_at = '2026-10-02T07:42:10Z'",
                    "UPDATE posts SET text = '', deleted_at = 'yesterday'"):
            with self.subTest(sql=sql):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(sql)
        connection.close()

    def test_the_edit_delete_upgrade_keeps_every_row(self):
        # A database at the version before edit-delete, with rows, a reply,
        # and an extra column and index on posts, the way another plan would add them.
        self.db_path = os.path.join(self.folder.name, "before-edit-delete.db")
        # report (the next version) is held back too, so the file stops before edit-delete.
        with mock.patch.object(server, "upgrade_to_edit_delete", lambda connection: None), \
                mock.patch.object(server, "upgrade_to_report", lambda connection: None):
            server.create_tables(self.db_path)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION - 2,)])
        self.clock = use_fake_clock(self)
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        connection = server.connect(self.db_path)
        post_id = server.insert_post(connection, aiko, "first words", place="Osaka")
        server.insert_post(connection, ben, "an answer", parent_id=post_id)
        connection.execute("INSERT INTO likes VALUES (?, ?)", (post_id, ben))
        connection.execute("INSERT INTO bookmarks VALUES (?, ?)", (ben, post_id))
        connection.commit()
        connection.executescript("ALTER TABLE posts ADD COLUMN mood TEXT; "
                                 "CREATE INDEX posts_by_mood ON posts (mood);")
        connection.close()
        tables = ("users", "posts", "likes", "sessions", "attempts", "bookmarks", "blocks")
        before = {t: self.rows("SELECT * FROM " + t + " ORDER BY 1, 2") for t in tables}
        server.create_tables(self.db_path)
        after = {t: self.rows("SELECT * FROM " + t + " ORDER BY 1, 2") for t in tables}
        after["posts"] = [row[:-1] for row in after["posts"]]   # without deleted_at
        self.assertEqual(after, before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name IN "
                                   "('posts_by_mood', 'post_versions', 'changes', "
                                   "'post_versions_by_post', 'posts_by_parent', "
                                   "'replies_are_one_level') ORDER BY name"),
                         [("changes",), ("post_versions",), ("post_versions_by_post",),
                          ("posts_by_mood",), ("posts_by_parent",), ("replies_are_one_level",)])
        server.create_tables(self.db_path)   # twice is harmless
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        with mock.patch.object(server, "utc_now", lambda: SOME_MOMENT):
            server.edit_post(self.db_path, aiko, post_id, "still works")
            self.assertTrue(server.delete_post(self.db_path, aiko, post_id)[1]["deleted"])

    # -- report --
    #
    # People are made with SQL (self.person), so no password is hashed.

    def report_people(self, first=("ben", "chika", "dai")):
        """Ben, Chika and Dai each post first; then Aiko posts the target. Emi never posts."""
        people = {name: self.person(name) for name in ("aiko", "ben", "chika", "dai", "emi")}
        for name in first:
            self.post_by(people[name], name + " was here first")
        target = self.post_by(people["aiko"], "the target")
        return people, target

    def report_three_times(self, people, target):
        for name in ("ben", "chika", "dai"):
            server.add_report(self.db_path, people[name], target)

    def seen_by(self, viewer_id, post_id):
        return post_id in [row["id"] for row in server.posts_after(self.db_path, 0, viewer_id)]

    def report_refused(self, *arguments):
        with self.assertRaises(server.RuleBroken) as caught:
            server.add_report(self.db_path, *arguments)
        return caught.exception.code

    def test_a_report_is_one_row_with_its_reason_or_null(self):
        people, target = self.report_people()
        server.add_report(self.db_path, people["ben"], target, "  rude  ")
        server.add_report(self.db_path, people["chika"], target)
        server.add_report(self.db_path, people["dai"], target, "   ")
        self.assertEqual(self.rows("SELECT post_id, user_id, reason FROM reports ORDER BY user_id"),
                         [(target, people["ben"], "rude"), (target, people["chika"], None),
                          (target, people["dai"], None)])

    def test_the_same_person_cannot_report_the_same_post_twice(self):
        people, target = self.report_people()
        server.add_report(self.db_path, people["ben"], target)
        self.assertEqual(self.report_refused(people["ben"], target), "report_already")
        # Even past every check in the code, the database refuses a second row.
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO reports (post_id, user_id) VALUES (?, ?)",
                               (target, people["ben"]))
        connection.close()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM reports"), [(1,)])

    def test_your_own_post_or_a_missing_post_cannot_be_reported(self):
        people, target = self.report_people()
        for user, post_id, code in ((people["aiko"], target, "report_own_post"),
                                    (people["ben"], 99, "post_missing"),
                                    (people["ben"], "x", "post_id_missing"),
                                    (people["ben"], None, "post_id_missing")):
            with self.subTest(post_id=post_id):
                self.assertEqual(self.report_refused(user, post_id), code)
        self.assertEqual(self.rows("SELECT * FROM reports"), [])

    def test_you_can_report_only_after_posting_before_the_post(self):
        people, target = self.report_people()
        self.assertEqual(self.report_refused(people["emi"], target), "report_too_early")
        self.post_by(people["emi"], "my first post")                  # newer than the target
        self.assertEqual(self.report_refused(people["emi"], target), "report_too_early")
        later = self.post_by(people["aiko"], "a later post")          # newer than Emi's post
        server.add_report(self.db_path, people["emi"], later)
        self.assertEqual(self.rows("SELECT post_id, user_id FROM reports"),
                         [(later, people["emi"])])

    def test_a_reason_may_be_200_characters_and_no_more(self):
        people, target = self.report_people()
        for reason, code in (("a" * (server.MAX_REASON + 1), "report_reason_too_long"),
                             (42, "report_reason_not_text"), (["a list"], "report_reason_not_text")):
            with self.subTest(reason=reason):
                self.assertEqual(self.report_refused(people["ben"], target, reason), code)
        server.add_report(self.db_path, people["ben"], target, "a" * server.MAX_REASON)
        self.assertEqual(self.rows("SELECT length(reason) FROM reports"), [(200,)])
        # The database refuses 201 too, with its CHECK.
        connection = server.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO reports VALUES (?, ?, ?)",
                               (target, people["chika"], "a" * 201))
        connection.close()

    def test_three_reports_hide_a_post_from_everyone_but_its_author(self):
        people, target = self.report_people()
        server.add_report(self.db_path, people["ben"], target)
        server.add_report(self.db_path, people["chika"], target)
        for viewer in (None, people["ben"], people["emi"], people["aiko"]):
            self.assertTrue(self.seen_by(viewer, target))   # two are not enough
        server.add_report(self.db_path, people["dai"], target)
        for viewer in (None, people["ben"], people["emi"]):
            with self.subTest(viewer=viewer):
                self.assertFalse(self.seen_by(viewer, target))
        self.assertTrue(self.seen_by(people["aiko"], target))
        # Only the author is sent it, so only the author ever sees hidden_by_reports true.
        mine = [row for row in server.posts_after(self.db_path, 0, people["aiko"])
                if row["id"] == target][0]
        self.assertTrue(server.post_to_json(mine)["hidden_by_reports"])
        self.assertFalse(any(server.post_to_json(row)["hidden_by_reports"]
                             for row in server.posts_after(self.db_path, 0, None)))
        # The other posts are still there for everyone, and the row is kept.
        self.assertEqual(len(server.posts_after(self.db_path, 0, None)), 3)
        self.assertEqual(self.rows("SELECT text FROM posts WHERE id = ?", (target,)),
                         [("the target",)])

    def test_taking_a_report_back_shows_the_post_again(self):
        people, target = self.report_people()
        self.report_three_times(people, target)
        self.assertEqual(server.remove_report(self.db_path, people["dai"], target), target)
        self.assertTrue(self.seen_by(None, target))
        for user in (people["dai"], people["emi"]):   # twice, and never at all
            with self.subTest(user=user):
                with self.assertRaises(server.RuleBroken) as caught:
                    server.remove_report(self.db_path, user, target)
                self.assertEqual(caught.exception.code, "report_not_there")

    def test_reports_for_gives_the_three_lists(self):
        people, target = self.report_people()
        dai_post = 3   # Chika posted before it (post 2)
        self.report_three_times(people, target)
        server.add_report(self.db_path, people["chika"], dai_post)
        self.assertEqual(server.reports_for(self.db_path, None), ([target], [], []))
        self.assertEqual(server.reports_for(self.db_path, people["aiko"]), ([], [target], []))
        self.assertEqual(server.reports_for(self.db_path, people["chika"]),
                         ([target], [], [dai_post, target]))
        self.assertEqual(server.reports_for(self.db_path, people["emi"]), ([target], [], []))

    def test_hidden_is_counted_never_stored(self):
        columns = [row[1] for row in self.rows("PRAGMA table_info(posts)")]
        self.assertFalse([c for c in columns if "hidden" in c or "report" in c or "count" in c])
        self.assertEqual([row[1] for row in self.rows("PRAGMA table_info(reports)")],
                         ["post_id", "user_id", "reason"])

    def test_report_and_block_are_each_one_condition_in_visible_to(self):
        sql, params = server.visible_to(7)
        for piece_sql, piece_params in (server.not_blocked_sql(7), server.not_hidden_sql(7)):
            self.assertIn("(" + piece_sql + ")", sql)
        self.assertEqual(params, server.not_blocked_sql(7)[1] + server.not_hidden_sql(7)[1])

    def test_a_hidden_post_is_in_no_search_and_its_picture_is_not_given(self):
        people = {name: self.person(name) for name in ("aiko", "ben", "chika", "dai")}
        for name in ("ben", "chika", "dai"):
            self.post_by(people[name], "first")
        target = self.picture_post(people["aiko"], text="my #cat")["id"]
        self.report_three_times(people, target)
        rows, more = server.search_posts(self.db_path, "#cat", people["ben"])
        self.assertEqual(rows, [])
        self.assertEqual([row["id"] for row in
                          server.search_posts(self.db_path, "#cat", people["aiko"])[0]], [target])
        for viewer in (None, people["ben"]):
            self.assertIsNone(server.picture_for(self.db_path, target, viewer))
        self.assertIsNotNone(server.picture_for(self.db_path, target, people["aiko"]))

    def test_crossing_the_limit_writes_hidden_and_shown_changes(self):
        people, target = self.report_people(first=("ben", "chika", "dai", "emi"))
        news = "SELECT post_id, kind FROM changes ORDER BY id"
        server.add_report(self.db_path, people["ben"], target)
        server.add_report(self.db_path, people["chika"], target)
        self.assertEqual(self.rows(news), [])                        # still shown
        server.add_report(self.db_path, people["dai"], target)
        self.assertEqual(self.rows(news), [(target, "hidden")])      # 2 -> 3
        server.add_report(self.db_path, people["emi"], target)
        self.assertEqual(len(self.rows(news)), 1)                    # 3 -> 4: no news
        server.remove_report(self.db_path, people["emi"], target)
        self.assertEqual(len(self.rows(news)), 1)                    # 4 -> 3: no news
        server.remove_report(self.db_path, people["dai"], target)
        self.assertEqual(self.rows(news), [(target, "hidden"), (target, "shown")])   # 3 -> 2
        # A refused report writes nothing.
        with self.assertRaises(server.RuleBroken):
            server.add_report(self.db_path, people["ben"], target)
        self.assertEqual(len(self.rows(news)), 2)

    def test_the_hidden_change_keeps_the_post_for_its_author_only(self):
        people, target = self.report_people()
        latest = server.changes_after(self.db_path, None)[0]
        self.report_three_times(people, target)
        for viewer, shown in ((people["aiko"], True), (people["ben"], False), (None, False)):
            with self.subTest(viewer=viewer):
                rows = server.changes_after(self.db_path, str(latest), viewer)[1]
                self.assertEqual([(change["kind"], post is not None) for change, post in rows],
                                 [("hidden", shown)])

    def test_a_deleted_post_takes_its_reports_with_it(self):
        people, target = self.report_people()
        server.add_report(self.db_path, people["ben"], target)
        server.delete_post(self.db_path, people["aiko"], target)
        self.assertEqual(self.rows("SELECT * FROM reports"), [])
        # And a post kept for its replies: its reports go too, and it cannot be reported.
        people_post = self.post_by(people["aiko"], "kept for its reply")
        self.post_by(people["ben"], "ben again")
        server.add_report(self.db_path, people["ben"], people_post)
        server.save_reply(self.db_path, people["ben"], "an answer", people_post)
        server.delete_post(self.db_path, people["aiko"], people_post)
        self.assertEqual(self.rows("SELECT * FROM reports"), [])
        self.assertEqual(self.report_refused(people["chika"], people_post), "post_missing")

    def test_the_report_upgrade_keeps_every_row(self):
        # A database from just before report, with rows in every table.
        aiko = self.sign_up("aiko")
        ben = self.sign_up("ben")
        post_id = server.save_post(self.db_path, aiko, "hello")["id"]
        server.add_like(self.db_path, ben, post_id)
        server.edit_post(self.db_path, aiko, post_id, "hello again")
        connection = sqlite3.connect(self.db_path)
        connection.executescript(f"DROP TABLE reports; "
                                 f"PRAGMA user_version = {server.LATEST_VERSION - 1};")
        connection.close()
        tables = ("users", "posts", "likes", "sessions", "attempts", "post_versions", "changes")
        before = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                  for table in tables}
        server.create_tables(self.db_path)
        after = {table: self.rows("SELECT * FROM " + table + " ORDER BY 1, 2")
                 for table in tables}
        self.assertEqual(after, before)
        self.assertEqual(self.rows("PRAGMA user_version"), [(server.LATEST_VERSION,)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.rows("SELECT * FROM reports"), [])
        server.create_tables(self.db_path)   # twice is harmless


class RealServerTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.folder.name, "test.db")
        # Port 0 asks the computer for any free port.
        self.server = server.make_server(0, db_path)
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # A cookie jar is the browser's memory for cookies: one jar, one window.
        self.window = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    def send(self, path, data, method="POST", content_type="application/json"):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": content_type},
            method=method,
        )
        return self.window.open(request)

    def refused(self, path, data, method="POST", content_type="application/json"):
        """Send a request the server should refuse. Return the code and the reason."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.send(path, data, method, content_type)
        reason = json.loads(caught.exception.read())["error"]
        caught.exception.close()
        return caught.exception.code, reason

    def sign_up(self, name="aiko", display_name="Aiko Tanaka"):
        return self.send("/accounts", {"account_name": name, "display_name": display_name,
                                       "password": PASSWORD})

    def get(self, path):
        with self.window.open(self.base + path) as answer:
            return json.loads(answer.read())

    def test_sign_up_sets_a_cookie_the_page_cannot_read(self):
        with self.sign_up() as answer:
            self.assertEqual(answer.status, 201)
            cookie = answer.headers["Set-Cookie"]
            self.assertEqual(json.loads(answer.read()),
                             {"account_name": "aiko", "display_name": "Aiko Tanaka"})
        self.assertTrue(cookie.startswith("session="))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_who_am_i_is_401_then_200_after_login(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/sessions")
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()
        self.sign_up().close()
        self.assertEqual(self.get("/sessions"),
                         {"account_name": "aiko", "display_name": "Aiko Tanaka"})

    def test_post_without_a_cookie_gets_401(self):
        code, reason = self.refused("/posts", {"text": "hello"})
        self.assertEqual(code, 401)
        self.assertIn("log in", reason)

    def test_a_request_that_is_not_json_gets_400(self):
        self.sign_up().close()
        code, reason = self.refused("/posts", {"text": "hello"}, content_type="text/plain")
        self.assertEqual(code, 400)
        self.assertIn("JSON", reason)
        self.assertEqual(self.get("/posts?after=0"), [])

    def test_post_then_get(self):
        self.sign_up().close()
        with self.send("/posts", {"text": "hello"}) as answer:
            self.assertEqual(answer.status, 201)
        posts = self.get("/posts?after=0")
        self.assertEqual(len(posts), 1)
        self.assertEqual((posts[0]["author"], posts[0]["display_name"], posts[0]["text"]),
                         ("aiko", "Aiko Tanaka", "hello"))

    def test_like_then_get_likes(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        with self.send("/likes", {"post_id": 1}) as answer:
            self.assertEqual(answer.status, 201)
            self.assertEqual(json.loads(answer.read()), {"post_id": 1, "like_count": 1})
        self.assertEqual(self.get("/likes"), {"counts": {"1": 1}, "mine": [1]})

    def test_a_second_like_gets_400_and_a_reason(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        self.send("/likes", {"post_id": 1}).close()
        code, reason = self.refused("/likes", {"post_id": 1})
        self.assertEqual(code, 400)
        self.assertIn("already", reason)

    def test_empty_post_gets_400_and_a_reason(self):
        self.sign_up().close()
        code, reason = self.refused("/posts", {"text": ""})
        self.assertEqual(code, 400)
        self.assertIn("empty", reason)

    def test_a_wrong_password_gets_401(self):
        self.sign_up().close()
        code, reason = self.refused("/sessions", {"account_name": "aiko",
                                                  "password": "not the password"})
        self.assertEqual((code, reason), (401, server.PROBLEMS[server.WRONG_LOGIN]))

    def test_the_served_page_has_the_colours_switch(self):
        with self.window.open(self.base + "/") as answer:
            page = answer.read().decode("utf-8")
        self.assertIn('id="theme"', page)
        self.assertIn('localStorage.getItem("timeline-theme")', page)

    def test_a_body_over_the_size_limit_gets_413_and_is_not_read(self):
        self.sign_up().close()
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1],
                                                timeout=5)
        connection.putrequest("POST", "/posts")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(server.MAX_REQUEST_BYTES + 1))
        connection.endheaders()
        # Only the headers were sent, never the body. A server that tried to
        # read the body would wait for it, and this would time out.
        answer = connection.getresponse()
        self.assertEqual(answer.status, 413)
        self.assertIn("too big", json.loads(answer.read())["error"])
        connection.close()
        self.assertEqual(self.get("/posts?after=0"), [])

    def test_an_unknown_route_gets_one_sentence(self):
        for method in ("GET", "POST", "DELETE"):
            with self.subTest(method=method):
                request = urllib.request.Request(self.base + "/nowhere", method=method,
                                                 data=b"{}" if method != "GET" else None,
                                                 headers={"Content-Type": "application/json"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.window.open(request)
                reason = json.loads(caught.exception.read())["error"]
                caught.exception.close()
                self.assertEqual((caught.exception.code, reason),
                                 (404, f"There is nothing to {method} at /nowhere."))

    # -- long-posts --

    def test_a_post_at_the_limit_gets_201_and_one_more_gets_400(self):
        self.sign_up().close()
        with self.send("/posts", {"text": "a" * server.MAX_TEXT}) as answer:
            self.assertEqual(answer.status, 201)
        code, reason = self.refused("/posts", {"text": "a" * (server.MAX_TEXT + 1)})
        self.assertEqual(code, 400)
        self.assertIn("560", reason)

    # -- who-liked --

    def refused_get(self, opener, path):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            opener.open(self.base + path)
        reason = json.loads(caught.exception.read())["error"]
        caught.exception.close()
        return caught.exception.code, reason

    def test_anyone_can_see_who_liked_a_post(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        self.send("/likes", {"post_id": 1}).close()
        stranger = urllib.request.build_opener()   # no cookie at all
        with stranger.open(self.base + "/likers?post_id=1") as answer:
            self.assertEqual(json.loads(answer.read()), {
                "post_id": 1, "like_count": 1,
                "likers": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}]})
        for path, words in (("/likers", "which post"), ("/likers?post_id=abc", "which post"),
                            ("/likers?post_id=99", "does not exist")):
            with self.subTest(path=path):
                code, reason = self.refused_get(stranger, path)
                self.assertEqual(code, 400)
                self.assertIn(words, reason)

    def test_the_summary_says_you_only_with_your_cookie(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        self.send("/likes", {"post_id": 1}).close()
        stranger = urllib.request.build_opener()
        with stranger.open(self.base + "/likesummary?post_ids=1") as answer:
            self.assertEqual(json.loads(answer.read()), {"summaries": {"1": {
                "like_count": 1, "you": False,
                "leaders": [{"account_name": "aiko", "display_name": "Aiko Tanaka"}]}}})
        self.assertEqual(self.get("/likesummary?post_ids=1"), {"summaries": {"1": {
            "like_count": 1, "you": True, "leaders": []}}})
        code, reason = self.refused_get(stranger, "/likesummary?post_ids=" +
                                        ",".join(str(n) for n in range(1, 102)))
        self.assertEqual(code, 400)
        self.assertIn("at most 100", reason)
        for path in ("/likesummary?post_ids=x", "/likesummary"):
            with self.subTest(path=path):
                code, reason = self.refused_get(stranger, path)
                self.assertEqual(code, 400)
                self.assertIn("which posts", reason)


    def test_a_new_post_has_a_full_utc_time_and_no_old_clock_time(self):
        self.sign_up().close()
        with self.send("/posts", {"text": "hello"}) as answer:
            self.assertEqual(answer.status, 201)
            post = json.loads(answer.read())
        self.assertRegex(post["posted_at"], ISO_TIME)
        self.assertIsNone(post["old_clock_time"])
        self.assertEqual(self.get("/posts?after=0")[0]["posted_at"], post["posted_at"])

    def test_the_sixth_post_gets_429_with_the_wait(self):
        use_fake_clock(self)
        self.sign_up().close()
        for number in range(5):
            self.send("/posts", {"text": f"post {number}"}).close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.send("/posts", {"text": "the sixth"})
        answer = json.loads(caught.exception.read())
        header = caught.exception.headers["Retry-After"]
        caught.exception.close()
        self.assertEqual(caught.exception.code, 429)
        self.assertTrue(header.isdigit() and int(header) >= 1)
        self.assertEqual(answer, {"error": "Too many posts. Please try again in "
                                           + header + " seconds.",
                                  "code": "post_too_fast", "values": {"count": int(header)},
                                  "retry_after": int(header)})
        self.assertEqual(len(self.get("/posts?after=0")), 5)

    def test_wrong_passwords_get_401_five_times_then_429(self):
        use_fake_clock(self)
        self.sign_up().close()
        wrong = {"account_name": "aiko", "password": "not the password"}
        for _ in range(5):
            self.assertEqual(self.refused("/sessions", wrong)[0], 401)
        code, reason = self.refused("/sessions", wrong)
        self.assertEqual(code, 429)
        self.assertIn("wrong passwords", reason)

    def test_reading_is_never_limited(self):
        use_fake_clock(self)
        self.sign_up().close()
        for _ in range(100):
            self.get("/posts?after=0")
            self.get("/likes")

    def test_a_post_with_no_cookie_is_still_401_not_429(self):
        use_fake_clock(self)
        self.sign_up().close()
        for number in range(5):
            self.send("/posts", {"text": f"post {number}"}).close()
        self.window = urllib.request.build_opener()   # a window with no cookie
        self.assertEqual(self.refused("/posts", {"text": "hello"})[0], 401)

    # -- search --

    def test_anyone_can_search_without_a_cookie(self):
        self.sign_up().close()
        self.send("/posts", {"text": "my #cat is asleep"}).close()
        self.send("/posts", {"text": "a catalog came"}).close()
        self.window = urllib.request.build_opener()   # a window with no cookie
        answer = self.get("/search?q=cat")
        self.assertEqual(set(answer), {"posts", "more"})
        self.assertEqual([post["text"] for post in answer["posts"]],
                         ["a catalog came", "my #cat is asleep"])
        self.assertFalse(answer["more"])
        # The # written as %23, as the page does with encodeURIComponent.
        answer = self.get("/search?q=%23cat")
        self.assertEqual([post["text"] for post in answer["posts"]], ["my #cat is asleep"])
        self.assertEqual(set(answer["posts"][0]), set(server.post_to_json(
            {key: None for key in ("id", "author", "display_name", "text", "posted_at",
                                   "old_clock_time", "like_count", "place",
                                   "picture_alt", "parent_id", "parent_author",
                                   "reply_count", "newest_reply_id", "edited",
                                   "hidden_by_reports",
                                   "deleted")})))

    def test_a_search_with_no_words_gets_400_and_a_reason(self):
        for path in ("/search", "/search?q=", "/search?q=%20%20",
                     "/search?q=a+b+c+d+e+f"):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.get(path)
                self.assertEqual(caught.exception.code, 400)
                self.assertTrue(json.loads(caught.exception.read())["error"])
                caught.exception.close()

    def test_a_search_is_not_printed_in_the_terminal(self):
        with mock.patch("http.server.BaseHTTPRequestHandler.log_message") as printed:
            self.get("/search?q=secret")
        printed.assert_not_called()

    # -- timeline-flow --

    def refused_get_plain(self, path):
        """A GET the server should refuse. Return the code and the reason."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.window.open(self.base + path)
        reason = json.loads(caught.exception.read())["error"]
        caught.exception.close()
        return caught.exception.code, reason

    def test_get_posts_before_0(self):
        clock = use_fake_clock(self)
        self.sign_up()
        for number in range(3):
            self.send("/posts", {"text": f"post {number}"})
            clock.move(61)
        posts = self.get("/posts?before=0")
        self.assertIsInstance(posts, list)
        self.assertLessEqual(len(posts), server.PAGE_SIZE)
        self.assertEqual([post["text"] for post in posts], ["post 2", "post 1", "post 0"])
        # The same JSON as an `after` answer, field for field.
        self.assertEqual(posts[0], self.get("/posts?after=0")[-1])

    def test_before_that_is_not_a_number_gets_400_and_a_reason(self):
        for wrong in ("abc", "-1", "1.5", ""):
            with self.subTest(before=wrong):
                self.assertEqual(self.refused_get_plain("/posts?before=" + wrong),
                                 (400, "'before' must be a whole number, 0 or more."))

    def test_before_and_after_together_get_400(self):
        self.assertEqual(self.refused_get_plain("/posts?before=300&after=12"),
                         (400, "Ask for 'before' or 'after', not both."))

    def test_likes_from_that_is_not_a_number_gets_400(self):
        self.assertEqual(self.refused_get_plain("/likes?from=abc"),
                         (400, "'from' must be a whole number, 0 or more."))
        self.assertEqual(self.get("/likes?from=5"), self.get("/likes"))

    # -- place --

    def test_a_post_with_a_place_shows_it_to_everyone(self):
        self.sign_up().close()
        with self.send("/posts", {"text": "hello", "place": "Osaka"}) as answer:
            self.assertEqual(answer.status, 201)
            self.assertEqual(json.loads(answer.read())["place"], "Osaka")
        self.window = urllib.request.build_opener()   # a window with no cookie
        self.assertEqual([post["place"] for post in self.get("/posts?after=0")], ["Osaka"])

    def test_a_place_with_a_line_break_is_400_with_a_reason(self):
        self.sign_up().close()
        code, reason = self.refused("/posts", {"text": "hello", "place": "Osaka\nfake"})
        self.assertEqual(code, 400)
        self.assertEqual(reason, "The place must not have hidden characters or line breaks.")
        self.assertEqual(self.get("/posts?after=0"), [])

    def test_a_post_with_no_place_key_still_works(self):
        self.sign_up().close()
        with self.send("/posts", {"text": "hello"}) as answer:
            self.assertEqual(answer.status, 201)
            self.assertIsNone(json.loads(answer.read())["place"])

    def test_a_place_without_a_login_is_401(self):
        self.assertEqual(self.refused("/posts", {"text": "hi", "place": "Osaka"})[0], 401)

    # -- bookmarks --

    def test_bookmarks_need_a_login(self):
        self.assertEqual(self.refused_get(self.window, "/bookmarks")[0], 401)
        self.sign_up().close()
        post_id = json.loads(self.send("/posts", {"text": "hello"}).read())["id"]
        self.window = urllib.request.build_opener()   # a window with no cookie
        self.assertEqual(self.refused("/bookmarks", {"post_id": post_id})[0], 401)
        self.assertEqual(self.refused("/bookmarks", {"post_id": post_id}, "DELETE")[0], 401)
        connection = server.connect(self.server.db_path)
        self.assertEqual(connection.execute("SELECT * FROM bookmarks").fetchall(), [])
        connection.close()

    def test_bookmark_list_and_take_back(self):
        self.sign_up().close()
        post_id = json.loads(self.send("/posts", {"text": "hello"}).read())["id"]
        with self.send("/bookmarks", {"post_id": post_id}) as answer:
            self.assertEqual(answer.status, 201)
            self.assertEqual(json.loads(answer.read()), {"post_id": post_id, "bookmarked": True})
        listed = self.get("/bookmarks")
        self.assertEqual(listed, self.get("/posts?after=0"))   # the same shape as /posts
        code, reason = self.refused("/bookmarks", {"post_id": post_id})
        self.assertEqual((code, reason), (400, "You have already bookmarked that post."))
        with self.send("/bookmarks", {"post_id": post_id}, "DELETE") as answer:
            self.assertEqual(answer.status, 200)
            self.assertEqual(json.loads(answer.read()), {"post_id": post_id, "bookmarked": False})
        self.assertEqual(self.get("/bookmarks"), [])

    def test_a_bookmark_that_is_not_json_is_refused(self):
        self.sign_up().close()
        post_id = json.loads(self.send("/posts", {"text": "hello"}).read())["id"]
        code, reason = self.refused("/bookmarks", {"post_id": post_id},
                                    content_type="text/plain")
        self.assertEqual((code, reason), (400, "The request must be JSON."))
        self.assertEqual(self.get("/bookmarks"), [])

    # -- japanese: every refusal carries a code --

    def refused_answer(self, request):
        """Send a request the server should refuse. Return the code and the whole JSON answer."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.window.open(request)
        answer = json.loads(caught.exception.read())
        caught.exception.close()
        return caught.exception.code, answer

    def request(self, path, data=None, method="GET", content_type="application/json"):
        return urllib.request.Request(
            self.base + path, method=method, headers={"Content-Type": content_type},
            data=json.dumps(data).encode("utf-8") if data is not None else None)

    def test_an_empty_post_is_refused_with_its_code(self):
        self.sign_up().close()
        code, answer = self.refused_answer(self.request("/posts", {"text": ""}, "POST"))
        self.assertEqual((code, answer), (400, {"error": "The post must not be empty.",
                                                "code": "text_empty", "values": {}}))

    def test_a_post_with_no_cookie_is_refused_with_login_needed(self):
        code, answer = self.refused_answer(self.request("/posts", {"text": "hello"}, "POST"))
        self.assertEqual((code, answer["code"]), (401, "login_needed"))

    def test_a_request_that_is_not_json_is_refused_with_not_json(self):
        code, answer = self.refused_answer(self.request("/posts", {"text": "hello"}, "POST",
                                                        content_type="text/plain"))
        self.assertEqual((code, answer["code"]), (400, "not_json"))

    def test_an_unknown_path_is_refused_with_nothing_here_and_its_values(self):
        code, answer = self.refused_answer(self.request("/nothing"))
        self.assertEqual((code, answer["code"], answer["values"]),
                         (404, "nothing_here", {"method": "GET", "path": "/nothing"}))

    def test_the_server_gives_the_page_its_words(self):
        with self.window.open(self.base + "/words.js") as answer:
            self.assertEqual(answer.status, 200)
            self.assertTrue(answer.headers["Content-Type"].startswith("text/javascript"))
            self.assertIn("const WORDS = {", answer.read().decode("utf-8"))

    def test_every_refusal_has_its_english_its_code_and_its_values(self):
        self.sign_up().close()
        requests = [
            self.request("/posts?after=x"),
            self.request("/nowhere", {}, "POST"),
            self.request("/posts", {"text": "a" * (server.MAX_TEXT + 1)}, "POST"),
            self.request("/likesummary?post_ids=x"),
            self.request("/likers?post_id=99"),
            self.request("/posts", [1, 2], "POST"),
            self.request("/likes", {"post_id": 99}, "POST"),
            self.request("/likes", {"post_id": 99}, "DELETE"),
            self.request("/likes", {}, "POST"),
            self.request("/accounts", {"account_name": "aiko", "password": PASSWORD}, "POST"),
            self.request("/accounts", {"account_name": "a b", "password": PASSWORD}, "POST"),
            self.request("/sessions", {"account_name": "aiko", "password": "wrong!!!"}, "POST"),
        ]
        for request in requests:
            with self.subTest(request=request.get_method() + " " + request.full_url):
                status, answer = self.refused_answer(request)
                self.assertIn(status, (400, 401, 404))
                self.assertEqual(set(answer), {"error", "code", "values"})
                self.assertIn(answer["code"], server.PROBLEMS)
                self.assertEqual(answer["error"],
                                 server.PROBLEMS[answer["code"]].format(**answer["values"]))

    # -- pictures --

    def raw_get(self, path):
        """GET a path exactly as written (no tidying of ".."). Return code, headers, body."""
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1],
                                                timeout=5)
        connection.request("GET", path)
        answer = connection.getresponse()
        result = answer.status, answer.headers, answer.read()
        connection.close()
        return result

    def post_picture(self, data, alt="a small square"):
        with self.send("/posts", {"text": "look", "picture": as_base64(data),
                                  "picture_alt": alt}) as answer:
            self.assertEqual(answer.status, 201)
            return json.loads(answer.read())

    def test_a_png_is_posted_and_sent_back_only_as_a_picture(self):
        self.sign_up().close()
        post = self.post_picture(PNG)
        self.assertEqual(post["picture"], {"url": "/pictures/1", "alt": "a small square"})
        code, headers, body = self.raw_get(post["picture"]["url"])
        self.assertEqual((code, body), (200, PNG))
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'none'; sandbox")
        self.assertIn("max-age=", headers["Cache-Control"])
        self.assertEqual(self.get("/posts?after=0")[0]["picture"], post["picture"])

    def test_the_type_comes_from_the_bytes(self):
        # A GIF the person named photo.jpg: the name never reaches the server,
        # and the type is found from the bytes.
        self.sign_up().close()
        post = self.post_picture(GIF)
        code, headers, body = self.raw_get(post["picture"]["url"])
        self.assertEqual((code, headers["Content-Type"], body), (200, "image/gif", GIF))

    def test_odd_picture_addresses_get_404_and_never_a_file(self):
        self.sign_up().close()
        self.post_picture(PNG)
        with self.send("/posts", {"text": "no picture"}) as answer:
            plain = json.loads(answer.read())
        self.assertIsNone(plain["picture"])
        for path in ("/pictures/999", "/pictures/2", "/pictures/abc", "/pictures/1.png",
                     "/pictures/", "/pictures/-1", "/pictures/1/", "/pictures/../timeline.db",
                     "/pictures/%2e%2e%2fserver.py", "/pictures/..%2Fserver.py",
                     "/pictures/" + "9" * 19):
            with self.subTest(path=path):
                code, headers, body = self.raw_get(path)
                self.assertEqual(code, 404)
                self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
                self.assertNotIn(b"SQLite", body)
                self.assertNotIn(b"import", body)

    def test_a_picture_post_needs_a_login_and_json(self):
        data = {"text": "look", "picture": as_base64(PNG), "picture_alt": "a square"}
        self.assertEqual(self.refused("/posts", data)[0], 401)
        self.sign_up().close()
        self.assertEqual(self.refused("/posts", data, content_type="text/plain")[0], 400)
        self.assertEqual(self.get("/posts?after=0"), [])

    def test_a_picture_that_is_not_one_gets_400(self):
        self.sign_up().close()
        code, reason = self.refused("/posts", {"text": "look", "picture_alt": "a cat",
                                               "picture": as_base64(NOT_PICTURES["html"])})
        self.assertEqual((code, reason), (400, "The picture must be a PNG, JPEG, GIF or WebP file."))
        self.assertEqual(self.get("/posts?after=0"), [])

    def test_a_search_result_carries_its_picture_and_hides_it_as_the_timeline_does(self):
        self.sign_up().close()
        self.post_picture(PNG, alt="my #cat asleep")
        found = self.get("/search?q=look")["posts"]
        self.assertEqual(found[0]["picture"], {"url": "/pictures/1", "alt": "my #cat asleep"})
        # A post this viewer may not see is in no search, and its picture is 404.
        with mock.patch.object(server, "visible_to", lambda viewer: ("0 = 1", [])):
            self.assertEqual(self.get("/search?q=look")["posts"], [])
            self.assertEqual(self.raw_get("/pictures/1")[0], 404)

    def test_the_biggest_picture_fits_in_one_request(self):
        self.sign_up().close()
        biggest = PNG + bytes(server.MAX_PICTURE_BYTES - len(PNG))
        post = self.post_picture(biggest)
        code, headers, body = self.raw_get(post["picture"]["url"])
        self.assertEqual((code, len(body)), (200, server.MAX_PICTURE_BYTES))

    # -- block --

    def test_blocks_need_a_login_and_json(self):
        stranger = urllib.request.build_opener()
        self.assertEqual(self.refused_get(stranger, "/blocks")[0], 401)
        self.assertEqual(self.refused("/blocks", {"account_name": "ben"})[0], 401)
        self.assertEqual(self.refused("/blocks", {"account_name": "ben"}, "DELETE")[0], 401)
        self.sign_up().close()
        code, reason = self.refused("/blocks", {"account_name": "ben"},
                                    content_type="text/plain")
        self.assertEqual((code, reason), (400, "The request must be JSON."))

    def test_posts_by_someone_you_blocked_are_left_out_only_with_your_cookie(self):
        ben = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        aiko = self.window
        self.window = ben
        self.sign_up("ben", "Ben Ito").close()
        self.send("/posts", {"text": "from ben"}).close()
        self.window = aiko
        self.sign_up().close()
        with self.send("/blocks", {"account_name": "ben"}) as answer:
            self.assertEqual(answer.status, 201)
            self.assertEqual(json.loads(answer.read()),
                             {"account_name": "ben", "display_name": "Ben Ito"})
        self.assertEqual(self.get("/posts?after=0"), [])
        self.assertEqual(self.get("/blocks"),
                         {"blocked": [{"account_name": "ben", "display_name": "Ben Ito"}]})
        for name, opener in (("no cookie", urllib.request.build_opener()),
                             ("wrong cookie", urllib.request.build_opener())):
            with self.subTest(window=name):
                request = urllib.request.Request(self.base + "/posts?after=0")
                if name == "wrong cookie":
                    request.add_header("Cookie", "session=not-a-real-token")
                with opener.open(request) as answer:
                    self.assertEqual([p["author"] for p in json.loads(answer.read())], ["ben"])
        self.assertEqual(self.refused("/blocks", {"account_name": "aiko"}),
                         (400, "You cannot block yourself."))
        with self.send("/blocks", {"account_name": "ben"}, "DELETE") as answer:
            self.assertEqual(answer.status, 200)
        self.assertEqual([p["author"] for p in self.get("/posts?after=0")], ["ben"])
        self.assertEqual(self.get("/blocks"), {"blocked": []})

    # -- replies --

    def test_a_reply_gets_201_with_its_parent(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        with self.send("/posts", {"text": "hi back", "parent_id": 1}) as answer:
            self.assertEqual(answer.status, 201)
            reply = json.loads(answer.read())
        self.assertEqual((reply["parent_id"], reply["parent_author"]), (1, "aiko"))
        posts = self.get("/posts?after=0")
        self.assertEqual([(p["id"], p["parent_id"], p["reply_count"]) for p in posts],
                         [(1, None, 1), (2, 1, 0)])
        # null is a normal post.
        with self.send("/posts", {"text": "plain", "parent_id": None}) as answer:
            self.assertIsNone(json.loads(answer.read())["parent_id"])

    def test_a_reply_without_a_cookie_gets_401_and_no_row(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        self.window = urllib.request.build_opener()   # a window with no cookie
        code, reason = self.refused("/posts", {"text": "hi", "parent_id": 1})
        self.assertEqual(code, 401)
        self.assertEqual(len(self.get("/posts?after=0")), 1)

    def test_a_reply_to_nothing_or_to_a_word_gets_400(self):
        self.sign_up().close()
        code, reason = self.refused("/posts", {"text": "hi", "parent_id": 9999})
        self.assertEqual((code, reason), (400, "That post does not exist."))
        code, reason = self.refused("/posts", {"text": "hi", "parent_id": "abc"})
        self.assertEqual((code, reason), (400, "The reply must say which post it answers."))
        self.assertEqual(self.get("/posts?after=0"), [])

    def test_the_reply_email_hook_runs_once_for_a_reply_after_the_answer(self):
        seen = []

        def hook(handler, row):
            seen.append((row["id"], row["parent_id"], row["parent_author"]))

        with mock.patch.object(server.TimelineHandler, "after_reply_saved", hook):
            self.sign_up().close()
            self.send("/posts", {"text": "hello"}).close()
            self.assertEqual(seen, [])   # not for a normal post
            self.send("/posts", {"text": "hi", "parent_id": 1}).close()
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.send("/posts", {"text": "hi", "parent_id": 2})   # refused
            caught.exception.close()
        self.assertEqual(seen, [(2, 1, "aiko")])

    def test_a_refused_reply_names_its_code(self):
        self.sign_up().close()
        self.send("/posts", {"text": "hello"}).close()
        self.send("/posts", {"text": "hi", "parent_id": 1}).close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.send("/posts", {"text": "hi", "parent_id": 2})
        answer = json.loads(caught.exception.read())
        caught.exception.close()
        self.assertEqual((caught.exception.code, answer["code"]), (400, "reply_to_reply"))

    # -- edit-delete --

    def change(self, path, data, method):
        with self.send(path, data, method) as answer:
            return answer.status, json.loads(answer.read())

    def refused_with_code(self, path, data, method):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.send(path, data, method)
        answer = json.loads(caught.exception.read())
        caught.exception.close()
        return caught.exception.code, answer["code"]

    def test_editing_needs_a_login_and_your_own_post(self):
        use_fake_clock(self)
        with mock.patch.object(server, "utc_now", lambda: SOME_MOMENT):
            self.sign_up("aiko").close()
            post_id = json.loads(self.send("/posts", {"text": "hello"}).read())["id"]
            me = self.window
            self.window = urllib.request.build_opener()   # no cookie
            self.assertEqual(self.refused_with_code("/posts", {"post_id": post_id, "text": "x"},
                                                    "PATCH"), (401, "login_needed"))
            self.assertEqual(self.refused_with_code("/posts", {"post_id": post_id}, "DELETE"),
                             (401, "login_needed"))
            self.window = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            self.sign_up("ben", "Ben Ito").close()
            self.assertEqual(self.refused_with_code("/posts", {"post_id": post_id, "text": "x"},
                                                    "PATCH"), (403, "post_not_yours"))
            self.assertEqual(self.refused_with_code("/posts", {"post_id": post_id}, "DELETE"),
                             (403, "post_not_yours"))
            self.window = me
            self.assertEqual(self.refused("/posts", "text", "PATCH", "text/plain")[0], 400)
            status, post = self.change("/posts", {"post_id": post_id, "text": "hello again"},
                                       "PATCH")
            self.assertEqual((status, post["text"], post["edited"]), (200, "hello again", True))
            self.assertEqual(self.refused_with_code("/posts", {"text": "x"}, "PATCH"),
                             (400, "post_id_missing"))
            self.assertEqual(self.refused("/nothing", {}, "PATCH"),
                             (404, "There is nothing to PATCH at /nothing."))

    def test_delete_then_delete_again(self):
        use_fake_clock(self)
        with mock.patch.object(server, "utc_now", lambda: SOME_MOMENT):
            self.sign_up().close()
            post_id = json.loads(self.send("/posts", {"text": "hello"}).read())["id"]
            self.assertEqual(self.change("/posts", {"post_id": post_id}, "DELETE"),
                             (200, {"post_id": post_id, "post": None}))
            self.assertEqual(self.refused_with_code("/posts", {"post_id": post_id}, "DELETE"),
                             (400, "post_missing"))
            self.assertEqual(self.get("/posts?after=0"), [])

    def test_changes_and_versions_over_http(self):
        use_fake_clock(self)
        with mock.patch.object(server, "utc_now", lambda: SOME_MOMENT):
            self.assertEqual(self.get("/changes"), {"latest": 0, "changes": []})
            for path in ("/changes?after=x", "/changes?after=", "/versions?post_id=x",
                         "/versions"):
                with self.subTest(path=path):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        self.get(path)
                    self.assertEqual(caught.exception.code, 400)
                    caught.exception.close()
            self.sign_up().close()
            post_id = json.loads(self.send("/posts", {"text": "one"}).read())["id"]
            self.change("/posts", {"post_id": post_id, "text": "two"}, "PATCH")
            self.change("/posts", {"post_id": post_id, "text": "three"}, "PATCH")
            self.window = urllib.request.build_opener()   # reading needs no login
            self.assertEqual(self.get("/versions?post_id=" + str(post_id)),
                             [{"text": "one", "replaced_at": "2026-10-02T07:42:10Z"},
                              {"text": "two", "replaced_at": "2026-10-02T07:42:10Z"}])
            answer = self.get("/changes?after=1")
            self.assertEqual(answer["latest"], 2)
            self.assertEqual([(c["id"], c["kind"], c["post"]["text"]) for c in answer["changes"]],
                             [(2, "edited", "three")])

    # -- report --

    def test_a_report_without_a_cookie_gets_401_and_not_json_gets_400(self):
        self.assertEqual(self.refused("/reports", {"post_id": 1})[0], 401)
        self.assertEqual(self.refused("/reports", {"post_id": 1}, method="DELETE")[0], 401)
        self.sign_up().close()
        code, reason = self.refused("/reports", {"post_id": 1}, content_type="text/plain")
        self.assertEqual(code, 400)
        self.assertIn("JSON", reason)

    def test_anyone_may_ask_which_posts_are_hidden(self):
        self.assertEqual(self.get("/reports"),
                         {"hidden": [], "mine_hidden": [], "reported": []})


class JourneyTest(unittest.TestCase):
    """One whole journey, through all three levels at once.

    The other tests look at one level each. This one follows two people from
    sign-up to likes and back, the way they really would, each in a window of
    their own.

    Every request below is one the page itself makes, with the same method and
    the same JSON: see `askWhoIAm`, `signUp`, `logIn`, `logOut`,
    `checkForNewPosts`, `sendPost` and `pressHeart` in `app.js`. The answers come
    from the real server over real HTTP. After each step the database file is
    opened and read with SQL, so a step is believed only if the rows agree
    with what the page was told.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "test.db")
        self.server = server.make_server(0, self.db_path)
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    # -- a window: a browser with its own cookies --

    def open_window(self):
        """A new browser window. Its cookie jar keeps the session cookie, as a browser does."""
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    # -- the requests the page makes, under the page's own names --

    def page_asks_for_new_posts(self, window, after=0):
        """checkForNewPosts: GET /posts?after=<the newest id this window has>"""
        with window.open(self.base + "/posts?after=" + str(after)) as answer:
            return json.loads(answer.read())

    def page_asks_for_counts(self, window):
        """checkForNewPosts: GET /likes. "mine" comes from the cookie, not from a name."""
        with window.open(self.base + "/likes") as answer:
            return json.loads(answer.read())

    def page_sends(self, window, path, data, method):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode("utf-8") if data is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with window.open(request) as answer:
            return answer.status, json.loads(answer.read())

    def page_signs_up(self, window, name, display_name):
        """signUp: POST /accounts"""
        return self.page_sends(window, "/accounts", {"account_name": name,
                                                     "display_name": display_name,
                                                     "password": PASSWORD}, "POST")

    def page_logs_in(self, window, name):
        """logIn: POST /sessions"""
        return self.page_sends(window, "/sessions", {"account_name": name,
                                                     "password": PASSWORD}, "POST")

    def page_logs_out(self, window):
        """logOut: DELETE /sessions"""
        return self.page_sends(window, "/sessions", None, "DELETE")

    def page_posts(self, window, text):
        """sendPost: POST /posts, with only the text"""
        return self.page_sends(window, "/posts", {"text": text}, "POST")

    def page_presses_heart(self, window, post_id, already_liked):
        """pressHeart: POST /likes to like, DELETE /likes to take the like back"""
        return self.page_sends(window, "/likes", {"post_id": post_id},
                               "DELETE" if already_liked else "POST")

    def is_refused(self, send, *arguments):
        """A request the server refuses. The page shows the reason it gives."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            send(*arguments)
        reason = json.loads(caught.exception.read())["error"]
        caught.exception.close()
        return caught.exception.code, reason

    # -- the store, read straight out of the file --

    def rows(self, sql):
        connection = server.connect(self.db_path)
        rows = [tuple(row) for row in connection.execute(sql).fetchall()]
        connection.close()
        return rows

    def test_the_whole_journey_of_two_accounts_and_a_like(self):
        aiko = self.open_window()
        ben = self.open_window()

        # 1. Aiko opens the page. Nothing anywhere yet, and nobody is logged in.
        self.assertEqual(self.page_asks_for_new_posts(aiko), [])
        self.assertEqual(self.page_asks_for_counts(aiko), {"counts": {}, "mine": []})
        code, reason = self.is_refused(self.page_sends, aiko, "/sessions", None, "GET")
        self.assertEqual(code, 401)
        self.assertEqual(self.rows("SELECT * FROM users"), [])

        # 2. Aiko signs up. One user, one session, and she is logged in.
        status, me = self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.assertEqual((status, me), (201, {"account_name": "aiko",
                                              "display_name": "Aiko Tanaka"}))
        self.assertEqual(self.rows("SELECT id, name, display_name FROM users"),
                         [(1, "aiko", "Aiko Tanaka")])
        self.assertEqual(self.rows("SELECT user_id FROM sessions"), [(1,)])

        # 3. Aiko posts. One post, pointing at her, no likes.
        status, post = self.page_posts(aiko, "the library is open late tonight")
        self.assertEqual(status, 201)
        self.assertEqual((post["author"], post["like_count"]), ("aiko", 0))
        self.assertEqual(self.rows("SELECT id, author_id FROM posts"), [(1, 1)])
        self.assertEqual(self.rows("SELECT * FROM likes"), [])

        # 4. Ben's window opens. Not logged in, Ben can read but cannot like.
        self.assertEqual(len(self.page_asks_for_new_posts(ben, 0)), 1)
        code, reason = self.is_refused(self.page_presses_heart, ben, 1, False)
        self.assertEqual(code, 401)
        self.assertEqual(self.rows("SELECT * FROM likes"), [])

        # 5. Ben signs up, then tries to post as Aiko by writing her name into
        #    the JSON. The server never reads it: the post is Ben's.
        self.page_signs_up(ben, "ben", "Ben Ito")
        status, post = self.page_sends(ben, "/posts", {"author": "aiko", "text": "I am Aiko"},
                                       "POST")
        self.assertEqual((post["author"], post["display_name"]), ("ben", "Ben Ito"))
        self.assertEqual(self.rows("SELECT id, author_id FROM posts ORDER BY id"),
                         [(1, 1), (2, 2)])

        # 6. Ben presses the heart on Aiko's post. One row, pointing at Ben and the post.
        status, answer = self.page_presses_heart(ben, 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 1}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 2)])

        # 7. Both windows poll. The count is 1 in each, but the heart is Ben's.
        self.assertEqual(self.page_asks_for_counts(aiko), {"counts": {"1": 1}, "mine": []})
        self.assertEqual(self.page_asks_for_counts(ben), {"counts": {"1": 1}, "mine": [1]})

        # 8. Ben presses the same heart again. The row is gone, not marked.
        status, answer = self.page_presses_heart(ben, 1, already_liked=True)
        self.assertEqual((status, answer), (200, {"post_id": 1, "like_count": 0}))
        self.assertEqual(self.rows("SELECT * FROM likes"), [])
        # With no likes left, the post has no entry at all. The page shows 0
        # because of the `|| 0` in checkForNewPosts.
        self.assertEqual(self.page_asks_for_counts(ben), {"counts": {}, "mine": []})

        # 9. And a third press likes it again, so nothing was left behind.
        status, answer = self.page_presses_heart(ben, 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 1}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 2)])

        # 10. Aiko likes her own post too: two rows, two people, one post.
        status, answer = self.page_presses_heart(aiko, 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 2}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes ORDER BY user_id"),
                         [(1, 1), (1, 2)])

        # 11. A window whose heart is out of date presses to like what it has
        #     already liked. The server refuses, and the store does not move.
        code, reason = self.is_refused(self.page_presses_heart, ben, 1, False)
        self.assertEqual(code, 400)
        self.assertIn("already", reason)
        self.assertEqual(len(self.rows("SELECT * FROM likes")), 2)

        # 12. Ben takes the like back, then presses again in a window that still
        #     shows it pressed. The second one is refused, and Aiko's row stays.
        self.page_presses_heart(ben, 1, already_liked=True)
        code, reason = self.is_refused(self.page_presses_heart, ben, 1, True)
        self.assertEqual(code, 400)
        self.assertIn("not liked", reason)
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 1)])
        self.assertEqual(self.page_asks_for_counts(aiko), {"counts": {"1": 1}, "mine": [1]})

        # 13. Ben logs out. His session row is gone, and a like now gets 401.
        status, answer = self.page_logs_out(ben)
        self.assertEqual(status, 200)
        self.assertEqual(self.rows("SELECT user_id FROM sessions"), [(1,)])
        code, reason = self.is_refused(self.page_presses_heart, ben, 1, False)
        self.assertEqual(code, 401)
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 1)])
        self.assertEqual(self.page_asks_for_counts(ben), {"counts": {"1": 1}, "mine": []})

        # 14. Ben logs in again, and the like works.
        status, me = self.page_logs_in(ben, "ben")
        self.assertEqual((status, me), (201, {"account_name": "ben", "display_name": "Ben Ito"}))
        status, answer = self.page_presses_heart(ben, 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 2}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes ORDER BY user_id"),
                         [(1, 1), (1, 2)])

        # 15. Through all of that, two people were added and no more, and the
        #     plain password is nowhere in the file.
        self.assertEqual(self.rows("SELECT name FROM users ORDER BY id"), [("aiko",), ("ben",)])
        for value in all_values_in(self.db_path):
            self.assertNotIn(PASSWORD, value)

    # -- who-liked --

    def page_asks_for_summaries(self, window, *post_ids):
        """askForSummaries: GET /likesummary?post_ids=3,7,9, with the cookie if any"""
        path = "/likesummary?post_ids=" + ",".join(str(p) for p in post_ids)
        with window.open(self.base + path) as answer:
            return json.loads(answer.read())["summaries"]

    def page_asks_who_liked(self, window, post_id):
        """showLikers: GET /likers?post_id=7"""
        with window.open(self.base + "/likers?post_id=" + str(post_id)) as answer:
            return json.loads(answer.read())

    def counts_of_every_table(self):
        return [self.rows(f"SELECT COUNT(*) FROM {table}")[0][0]
                for table in ("users", "posts", "likes", "sessions")]

    def test_the_whole_journey_of_who_liked(self):
        anika, ben, chika = self.open_window(), self.open_window(), self.open_window()
        nobody = self.open_window()

        def names(people):
            return [person["account_name"] for person in people]

        def read_only(ask, *arguments):
            # Asking who liked a post never adds or removes a row anywhere.
            before = self.counts_of_every_table()
            answer = ask(*arguments)
            self.assertEqual(self.counts_of_every_table(), before)
            return answer

        # 1. Three people sign up. Chika posts twice and Anika once; Ben likes
        #    all three, so Chika's popularity is 2 and Anika's is 1. Ben posts P.
        self.page_signs_up(anika, "anika", "Anika")
        self.page_signs_up(ben, "ben", "Ben Ito")
        self.page_signs_up(chika, "chika", "Chika")
        chika_one = self.page_posts(chika, "one")[1]["id"]
        chika_two = self.page_posts(chika, "two")[1]["id"]
        anika_one = self.page_posts(anika, "three")[1]["id"]
        for post_id in (chika_one, chika_two, anika_one):
            self.page_presses_heart(ben, post_id, already_liked=False)
        p = self.page_posts(ben, "P")[1]["id"]

        # 2. Nobody liked P yet: no names, count 0, and an empty list.
        self.assertEqual(read_only(self.page_asks_for_summaries, nobody, p),
                         {str(p): {"like_count": 0, "you": False, "leaders": []}})
        self.assertEqual(read_only(self.page_asks_who_liked, nobody, p),
                         {"post_id": p, "like_count": 0, "likers": []})

        # 3. Anika and Chika like P. The more popular one, Chika, comes first.
        self.page_presses_heart(anika, p, already_liked=False)
        self.page_presses_heart(chika, p, already_liked=False)
        summary = read_only(self.page_asks_for_summaries, nobody, p)[str(p)]
        self.assertEqual(names(summary["leaders"]), ["chika", "anika"])
        self.assertEqual(self.rows(f"SELECT user_id FROM likes WHERE post_id = {p} "
                                   "ORDER BY user_id"), [(1,), (3,)])

        # 4. Ben likes P. In his window he is "You", with one leader; the count
        #    is 3, the same as GET /likes. A window not logged in sees two names.
        #    P is Ben's own post, and Anika and Chika liked it, so Ben's
        #    popularity is 2 now, the same as Chika's: A to Z, Ben comes first.
        self.page_presses_heart(ben, p, already_liked=False)
        summary = read_only(self.page_asks_for_summaries, ben, p)[str(p)]
        self.assertEqual((summary["you"], names(summary["leaders"]), summary["like_count"]),
                         (True, ["chika"], 3))
        self.assertEqual(self.page_asks_for_counts(ben)["counts"][str(p)], 3)
        summary = read_only(self.page_asks_for_summaries, nobody, p)[str(p)]
        self.assertEqual((summary["you"], names(summary["leaders"]), summary["like_count"]),
                         (False, ["ben", "chika"], 3))

        # 5. Ben takes back one like on Chika's post: Chika's popularity is now
        #    1, the same as Anika's, so Ben's window (where Ben is "You") gets
        #    the first of them A to Z: Anika. With no cookie: Ben, then Anika.
        self.page_presses_heart(ben, chika_one, already_liked=True)
        summary = read_only(self.page_asks_for_summaries, ben, p)[str(p)]
        self.assertEqual((summary["you"], names(summary["leaders"])), (True, ["anika"]))
        summary = read_only(self.page_asks_for_summaries, nobody, p)[str(p)]
        self.assertEqual(names(summary["leaders"]), ["ben", "anika"])

        # 6. The full list: everyone, A to Z, and the rows agree.
        likers = read_only(self.page_asks_who_liked, nobody, p)
        self.assertEqual((names(likers["likers"]), likers["like_count"]),
                         (["anika", "ben", "chika"], 3))
        self.assertEqual(self.rows(f"SELECT users.name FROM likes JOIN users "
                                   f"ON users.id = likes.user_id WHERE post_id = {p} "
                                   "ORDER BY users.name"), [("anika",), ("ben",), ("chika",)])
        self.assertEqual([person["display_name"] for person in likers["likers"]],
                         ["Anika", "Ben Ito", "Chika"])


    def test_an_old_post_keeps_its_clock_time_and_a_new_one_gets_the_server_s_time(self):
        # A database file in the old format (before accounts), with one post at 15:42.
        old_path = os.path.join(self.folder.name, "old.db")
        connection = sqlite3.connect(old_path)
        connection.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE posts (id INTEGER PRIMARY KEY,
                                author_id INTEGER NOT NULL REFERENCES users(id),
                                text TEXT NOT NULL, posted_at TEXT NOT NULL);
            CREATE TABLE likes (post_id INTEGER NOT NULL REFERENCES posts(id),
                                user_id INTEGER NOT NULL REFERENCES users(id),
                                PRIMARY KEY (post_id, user_id));
            INSERT INTO users VALUES (1, 'Aiko');
            INSERT INTO posts VALUES (1, 1, 'from before', '15:42');
        """)
        connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.db_path = old_path
        self.server = server.make_server(0, old_path)   # the server upgrades it as it starts
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        ben = self.open_window()

        # 1. The old post shows its old clock time, and no date.
        old = self.page_asks_for_new_posts(ben)
        self.assertEqual([(post["id"], post["posted_at"], post["old_clock_time"]) for post in old],
                         [(1, None, "15:42")])
        self.assertEqual(self.rows("SELECT id, posted_at, old_clock_time FROM posts"),
                         [(1, None, "15:42")])

        # 2. Ben signs up and posts, with a made-up time in the JSON. The server
        #    never reads it: the time comes from the server's own clock.
        self.page_signs_up(ben, "ben", "Ben Ito")
        with mock.patch("server.utc_now", return_value=SOME_MOMENT):
            status, post = self.page_sends(ben, "/posts", {"text": "hello",
                                                           "posted_at": "1999-01-01T00:00:00Z"},
                                           "POST")
        self.assertEqual(status, 201)
        self.assertEqual((post["posted_at"], post["old_clock_time"]),
                         ("2026-10-02T07:42:10Z", None))
        self.assertEqual(self.rows("SELECT id, posted_at, old_clock_time FROM posts ORDER BY id"),
                         [(1, None, "15:42"), (2, "2026-10-02T07:42:10Z", None)])

        # 3. "after" is still a post id, not a time: only the new post comes back.
        self.assertEqual([post["id"] for post in self.page_asks_for_new_posts(ben, 1)], [2])

    def test_too_fast_journey(self):
        clock = use_fake_clock(self)
        aiko = self.open_window()
        ben = self.open_window()
        stranger = self.open_window()

        # 1. Aiko and Ben sign up.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ben, "ben", "Ben Ito")

        # 2. Aiko posts five times. The sixth is refused with 429, and the
        #    store has five posts and five counted attempts, no more.
        for number in range(5):
            status, post = self.page_posts(aiko, f"post {number}")
            self.assertEqual(status, 201)
        code, reason = self.is_refused(self.page_posts, aiko, "the sixth")
        self.assertEqual(code, 429)
        self.assertIn("60 seconds", reason)
        self.assertEqual(len(self.rows("SELECT * FROM posts")), 5)
        self.assertEqual(self.rows("SELECT key, COUNT(*) FROM attempts WHERE action = 'post' "
                                   "GROUP BY key"), [("1", 5)])

        # 3. Ben's own count is his own.
        status, post = self.page_posts(ben, "Ben is fine")
        self.assertEqual(status, 201)

        # 4. A stranger tries five wrong passwords for aiko. The sixth is 429.
        wrong = {"account_name": "aiko", "password": "not the password"}
        for _ in range(5):
            code, reason = self.is_refused(self.page_sends, stranger, "/sessions", wrong, "POST")
            self.assertEqual(code, 401)
        code, reason = self.is_refused(self.page_sends, stranger, "/sessions", wrong, "POST")
        self.assertEqual(code, 429)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM attempts WHERE action = 'login' "
                                   "AND key = 'aiko'"), [(5,)])

        # 5. Aiko's own window is still logged in: a minute later she can post.
        clock.move(61)
        status, post = self.page_posts(aiko, "still here")
        self.assertEqual(status, 201)

        # 6. Ten minutes later Aiko logs in from a new window. Her wrong-password
        #    count is gone.
        clock.move(600)
        status, me = self.page_logs_in(self.open_window(), "aiko")
        self.assertEqual(status, 201)
        self.assertEqual(self.rows("SELECT * FROM attempts WHERE action = 'login' "
                                   "AND key = 'aiko'"), [])

        # 7. No counted attempt holds a password or a post's words.
        for action, key, at in self.rows("SELECT action, key, at FROM attempts"):
            self.assertNotIn(key, (PASSWORD, "not the password"))
            self.assertNotIn("post", key)
        for value in all_values_in(self.db_path):
            self.assertNotIn(PASSWORD, value)

    # -- search --

    def page_searches(self, window, query):
        """runSearch: GET /search?q=<the search, written with encodeURIComponent>"""
        url = self.base + "/search?q=" + urllib.parse.quote(query, safe="")
        with window.open(url) as answer:
            return answer.status, json.loads(answer.read())

    def ids_sql_finds(self, *likes):
        """The post ids whose text is LIKE every pattern, newest first, read from the file."""
        where = " AND ".join("text LIKE ?" for _ in likes)
        connection = server.connect(self.db_path)
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM posts WHERE " + where + " ORDER BY id DESC", likes)]
        connection.close()
        return ids

    def test_the_whole_journey_of_a_search(self):
        use_fake_clock(self)
        aiko = self.open_window()
        ben = self.open_window()
        stranger = self.open_window()   # never signs up

        # 1. Two people sign up and post: one tag, and one word that only starts the same.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ben, "ben", "Ben")
        status, cat_post = self.page_posts(aiko, "My #cat sleeps all day")
        self.assertEqual(status, 201)
        status, catalog_post = self.page_posts(ben, "The new catalog came")
        self.assertEqual(status, 201)
        self.page_presses_heart(ben, cat_post["id"], already_liked=False)
        tables_before = all_values_in(self.db_path)

        # 2. Someone who is not logged in searches for the tag: only Aiko's post.
        status, answer = self.page_searches(stranger, "#cat")
        self.assertEqual(status, 200)
        self.assertEqual([post["id"] for post in answer["posts"]], [cat_post["id"]])
        self.assertEqual(answer["posts"][0]["like_count"], 1)
        self.assertEqual(answer["posts"][0]["author"], "aiko")
        self.assertFalse(answer["more"])
        # SQL on the file agrees: #cat is in only that post.
        self.assertEqual(self.ids_sql_finds("%#cat%"), [cat_post["id"]])

        # 3. The word "cat" finds both, newest first, as SQL does.
        status, answer = self.page_searches(aiko, "cat")
        self.assertEqual([post["id"] for post in answer["posts"]], self.ids_sql_finds("%cat%"))
        self.assertEqual(len(answer["posts"]), 2)

        # 4. Two words: both must appear.
        status, answer = self.page_searches(ben, "day sleeps")
        self.assertEqual([post["id"] for post in answer["posts"]],
                         self.ids_sql_finds("%day%", "%sleeps%"))
        self.assertEqual([post["id"] for post in answer["posts"]], [cat_post["id"]])

        # 5. An empty search is refused, with the reason the page shows.
        code, reason = self.is_refused(self.page_searches, stranger, "   ")
        self.assertEqual((code, reason), (400, "Type a word to search for."))

        # 6. Searching changed nothing in the file: no user, post, like or attempt.
        self.assertEqual(all_values_in(self.db_path), tables_before)

    # -- timeline-flow --

    def page_asks_for_a_page(self, window, before):
        """loadOlderPosts: GET /posts?before=<the oldest id this window shows>, 0 at first"""
        with window.open(self.base + "/posts?before=" + str(before)) as answer:
            return json.loads(answer.read())

    def page_asks_for_counts_from(self, window, from_id):
        """checkForNewPosts: GET /likes?from=<the oldest id this window shows>"""
        with window.open(self.base + "/likes?from=" + str(from_id)) as answer:
            return json.loads(answer.read())

    def test_the_whole_journey_of_scrolling(self):
        clock = use_fake_clock(self)
        aiko = self.open_window()
        ben = self.open_window()
        reader = self.open_window()   # not logged in: reading needs no login

        # 1. Aiko signs up and posts 45 times, a minute apart, so the rate
        #    limit never stops her.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        for number in range(45):
            status, post = self.page_posts(aiko, f"post {number + 1}")
            self.assertEqual(status, 201)
            clock.move(61)
        every_id = [row[0] for row in self.rows("SELECT id FROM posts ORDER BY id DESC")]
        self.assertEqual(len(every_id), 45)

        # 2. The reader's page opens: the newest page, then two older pages as
        #    the reader scrolls. Each page is newest first, and the last one is
        #    short, so the page knows it has reached the end.
        first = self.page_asks_for_a_page(reader, 0)
        self.assertEqual([post["id"] for post in first], every_id[:20])
        second = self.page_asks_for_a_page(reader, first[-1]["id"])
        self.assertEqual([post["id"] for post in second], every_id[20:40])
        third = self.page_asks_for_a_page(reader, second[-1]["id"])
        self.assertEqual([post["id"] for post in third], every_id[40:])
        self.assertLess(len(third), server.PAGE_SIZE)
        shown = [post["id"] for post in first + second + third]
        self.assertEqual(sorted(shown), sorted(every_id))
        self.assertEqual(len(set(shown)), len(shown))
        self.assertEqual(self.page_asks_for_a_page(reader, third[-1]["id"]), [])

        # 3. Ben signs up and posts. The reader asks `after` the newest id of
        #    the first page, and gets exactly that one post.
        self.page_signs_up(ben, "ben", "Ben Ito")
        self.page_posts(ben, "Ben is here")
        new = self.page_asks_for_new_posts(reader, first[0]["id"])
        self.assertEqual([post["id"] for post in new],
                         [row[0] for row in self.rows("SELECT max(id) FROM posts")])
        self.assertEqual(new[0]["text"], "Ben is here")

        # 4. Aiko likes the third post. Asking only from the first page's oldest
        #    post leaves it out; asking from the very oldest has it, with the
        #    count the likes table gives.
        post_3 = every_id[-3]
        status, answer = self.page_presses_heart(aiko, post_3, already_liked=False)
        self.assertEqual(status, 201)
        near = self.page_asks_for_counts_from(aiko, first[-1]["id"])
        self.assertNotIn(str(post_3), near["counts"])
        self.assertNotIn(post_3, near["mine"])
        far = self.page_asks_for_counts_from(aiko, every_id[-1])
        self.assertEqual(far["counts"][str(post_3)],
                         self.rows(f"SELECT count(*) FROM likes WHERE post_id = {post_3}")[0][0])
        self.assertEqual(far["mine"], [post_3])
        # Leaving `from` out gives the same as from the very first post.
        self.assertEqual(self.page_asks_for_counts(aiko), far)

    def test_the_whole_journey_of_a_place(self):
        aiko = self.open_window()
        ben = self.open_window()

        # 1. Aiko signs up and posts from Osaka. The row has the place.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        status, post = self.page_sends(aiko, "/posts", {"text": "lunch", "place": " Osaka "},
                                       "POST")
        self.assertEqual((status, post["place"]), (201, "Osaka"))
        self.assertEqual(self.rows("SELECT id, place FROM posts"), [(1, "Osaka")])

        # 2. She posts with an empty place box: the row has NULL, never ''.
        status, post = self.page_sends(aiko, "/posts", {"text": "back home", "place": ""},
                                       "POST")
        self.assertEqual((status, post["place"]), (201, None))
        self.assertEqual(self.rows("SELECT id, place FROM posts ORDER BY id"),
                         [(1, "Osaka"), (2, None)])

        # 3. A place with a line break is refused, and nothing is saved.
        code, reason = self.is_refused(self.page_sends, aiko, "/posts",
                                       {"text": "sneaky", "place": "Osaka\n15:00  Ben"}, "POST")
        self.assertEqual(code, 400)
        self.assertIn("line breaks", reason)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts"), [(2,)])

        # 4. Ben's window, not logged in, sees both posts: one place, one null.
        posts = self.page_asks_for_new_posts(ben)
        self.assertEqual(sorted((post["id"], post["place"]) for post in posts),
                         [(1, "Osaka"), (2, None)])

        # 5. The place is kept with the post, not with the person: users has no place.
        self.assertNotIn("place", [row[1] for row in self.rows("PRAGMA table_info(users)")])


    def test_the_whole_journey_of_a_picture(self):
        aiko = self.open_window()
        ben = self.open_window()
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ben, "ben", "Ben Ito")

        # 1. Aiko posts with a picture (sendPost: text, picture, picture_alt).
        status, post = self.page_sends(aiko, "/posts", {
            "text": "My desk today", "picture": as_base64(PNG),
            "picture_alt": "A small square, all one colour"}, "POST")
        self.assertEqual(status, 201)
        # The store: one pictures row for that post, with the kind found from the bytes.
        self.assertEqual(self.rows("SELECT post_id, kind, length(bytes), alt_text FROM pictures"),
                         [(post["id"], "png", len(PNG), "A small square, all one colour")])

        # 2. Ben's window gets the post with the picture's address, and loads it.
        seen = self.page_asks_for_new_posts(ben)
        self.assertEqual(seen[0]["picture"], {"url": "/pictures/" + str(post["id"]),
                                              "alt": "A small square, all one colour"})
        with ben.open(self.base + seen[0]["picture"]["url"]) as answer:
            self.assertEqual(answer.headers["Content-Type"], "image/png")
            self.assertEqual(answer.read(), PNG)

        # 3. Ben posts a text file renamed .png: 400, and nothing new is stored.
        code, reason = self.is_refused(self.page_sends, ben, "/posts", {
            "text": "my cat", "picture": as_base64(NOT_PICTURES["text named cat.png"]),
            "picture_alt": "my cat"}, "POST")
        self.assertEqual((code, reason), (400, "The picture must be a PNG, JPEG, GIF or WebP file."))
        self.assertEqual(self.rows("SELECT (SELECT COUNT(*) FROM posts), "
                                   "(SELECT COUNT(*) FROM pictures)"), [(1, 1)])

        # 4. If Ben may not see Aiko's posts (as block or report will decide in
        #    visible_to), he cannot load her picture either. Aiko still can.
        url = self.base + post["picture"]["url"]
        hide_aiko = lambda viewer: ("posts.author_id = 2", []) if viewer == 2 else ("1 = 1", [])
        with mock.patch.object(server, "visible_to", hide_aiko):
            code, reason = self.is_refused(ben.open, url)
            self.assertEqual(code, 404)
            with aiko.open(url) as answer:
                self.assertEqual(answer.read(), PNG)

        # 5. The post's row is deleted (as edit-delete will): its picture goes
        #    with it, and the address answers 404.
        connection = server.connect(self.db_path)
        connection.execute("DELETE FROM posts WHERE id = ?", (post["id"],))
        connection.commit()
        connection.close()
        self.assertEqual(self.rows("SELECT COUNT(*) FROM pictures"), [(0,)])
        self.assertEqual(self.is_refused(ben.open, url)[0], 404)

    # -- block --

    def page_blocks(self, window, name):
        """pressBlock: POST /blocks, with only the account name"""
        return self.page_sends(window, "/blocks", {"account_name": name}, "POST")

    def page_unblocks(self, window, name):
        """unblock: DELETE /blocks, with only the account name"""
        return self.page_sends(window, "/blocks", {"account_name": name}, "DELETE")

    def page_asks_who_is_blocked(self, window):
        """loadBlocked: GET /blocks"""
        with window.open(self.base + "/blocks") as answer:
            return json.loads(answer.read())

    def test_the_whole_journey_of_a_block(self):
        aiko, ben, nobody = self.open_window(), self.open_window(), self.open_window()

        def authors(posts):
            return [(post["author"], post["text"]) for post in posts]

        # 1. Aiko and Ben sign up and each post. Aiko sees Ben's post.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ben, "ben", "Ben Ito")
        aikos = self.page_posts(aiko, "hello from aiko")[1]["id"]
        self.page_posts(ben, "hello from ben")
        self.assertEqual(authors(self.page_asks_for_new_posts(aiko)),
                         [("aiko", "hello from aiko"), ("ben", "hello from ben")])

        # 2. Aiko blocks Ben: one row in blocks, with their two ids.
        status, answer = self.page_blocks(aiko, "ben")
        self.assertEqual((status, answer), (201, {"account_name": "ben",
                                                  "display_name": "Ben Ito"}))
        self.assertEqual(self.rows("SELECT blocker_id, blocked_id FROM blocks"), [(1, 2)])
        self.assertEqual(self.page_asks_who_is_blocked(aiko)["blocked"],
                         [{"account_name": "ben", "display_name": "Ben Ito"}])

        # 3. Aiko's next poll has no post by Ben. A window with no cookie still has it,
        #    and so does Ben's own window (decision 1).
        self.assertEqual(authors(self.page_asks_for_new_posts(aiko)),
                         [("aiko", "hello from aiko")])
        self.assertEqual(len(self.page_asks_for_new_posts(nobody)), 2)
        self.assertEqual(len(self.page_asks_for_new_posts(ben)), 2)
        # The same in a search: Aiko's search has no post by Ben; nobody's has both.
        status, found = self.page_searches(aiko, "hello")
        self.assertEqual([post["author"] for post in found["posts"]], ["aiko"])
        status, found = self.page_searches(nobody, "hello")
        self.assertEqual([post["author"] for post in found["posts"]], ["ben", "aiko"])

        # 4. Ben posts again. Aiko's poll does not bring it.
        newest = self.page_posts(ben, "are you there?")[1]["id"]
        self.assertEqual(self.page_asks_for_new_posts(aiko, newest - 1), [])
        self.assertEqual(self.rows(f"SELECT author_id FROM posts WHERE id = {newest}"), [(2,)])

        # 5. Ben presses the heart on Aiko's post: refused, and no row in likes.
        code, reason = self.is_refused(self.page_presses_heart, ben, aikos, False)
        self.assertEqual((code, reason), (400, "You cannot like this post."))
        self.assertEqual(self.rows("SELECT * FROM likes"), [])

        # 6. Aiko sends "blocker": "ben" in the JSON. It is ignored: the blocker
        #    comes from the cookie, so this blocks nobody new and Ben blocks nobody.
        code, reason = self.is_refused(self.page_sends, aiko, "/blocks",
                                       {"account_name": "ben", "blocker": "ben"}, "POST")
        self.assertEqual((code, reason), (400, "You have already blocked @ben."))
        self.assertEqual(self.rows("SELECT blocker_id, blocked_id FROM blocks"), [(1, 2)])

        # 7. Aiko unblocks Ben: the row is gone, and both of Ben's posts are back, in order.
        status, answer = self.page_unblocks(aiko, "ben")
        self.assertEqual(status, 200)
        self.assertEqual(self.rows("SELECT * FROM blocks"), [])
        self.assertEqual(authors(self.page_asks_for_new_posts(aiko)),
                         [("aiko", "hello from aiko"), ("ben", "hello from ben"),
                          ("ben", "are you there?")])
        self.assertEqual(self.page_asks_who_is_blocked(aiko), {"blocked": []})

        # 8. Now Ben may like Aiko's post again.
        self.assertEqual(self.page_presses_heart(ben, aikos, False)[0], 201)
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(aikos, 2)])

    def test_the_whole_journey_of_a_reply(self):
        use_fake_clock(self)
        aiko = self.open_window()
        ken = self.open_window()
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ken, "ken", "Ken Mori")

        # 1. Aiko posts. Ken replies (sendPost, with parent_id). The row points
        #    at Aiko's post, and its author is Ken.
        status, post = self.page_posts(aiko, "Who is coming to the festival?")
        status, reply = self.page_sends(ken, "/posts", {"text": "Me!",
                                                        "parent_id": post["id"]}, "POST")
        self.assertEqual((status, reply["parent_author"]), (201, "aiko"))
        self.assertEqual(self.rows("SELECT id, author_id, parent_id FROM posts ORDER BY id"),
                         [(1, 1, None), (2, 2, 1)])
        # checkForNewPosts: the reply comes after its post, and the post counts it.
        posts = self.page_asks_for_new_posts(aiko)
        self.assertEqual([(p["id"], p["parent_id"]) for p in posts], [(1, None), (2, 1)])
        self.assertEqual((posts[0]["reply_count"], posts[0]["newest_reply_id"]), (1, 2))

        # 2. Ken writes "author": "aiko" into a reply. It is still Ken's.
        status, reply = self.page_sends(ken, "/posts", {"text": "really me", "author": "aiko",
                                                        "parent_id": 1}, "POST")
        self.assertEqual(reply["author"], "ken")
        self.assertEqual(self.rows("SELECT author_id FROM posts WHERE id = 3"), [(2,)])

        # 3. Aiko replies to her own post: allowed. Ken replies to his reply: 400, no row.
        status, own = self.page_sends(aiko, "/posts", {"text": "Great",
                                                       "parent_id": 1}, "POST")
        self.assertEqual(status, 201)
        code, reason = self.is_refused(self.page_sends, ken, "/posts",
                                       {"text": "and me again", "parent_id": 2}, "POST")
        self.assertEqual((code, reason), (400, "You can only reply to a post, not to a reply."))
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts"), [(4,)])

        # 4. Aiko likes Ken's reply: one row in likes, as for any post.
        status, like = self.page_presses_heart(aiko, 2, False)
        self.assertEqual(like, {"post_id": 2, "like_count": 1})
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(2, 1)])

        # 5. A window that has seen post 1 asks for newer posts: it gets only the
        #    new replies, each newer than the newest reply it was told about.
        newer = self.page_asks_for_new_posts(ken, 2)
        self.assertEqual([p["id"] for p in newer], [3, 4])
        self.assertTrue(all(p["id"] > posts[0]["newest_reply_id"] for p in newer))

        # 6. The count in the rows equals the replies GET /posts gives, and the
        #    count the server sends.
        everything = self.page_asks_for_new_posts(aiko)
        replies = [p for p in everything if p["parent_id"] == 1]
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts WHERE parent_id = 1"),
                         [(len(replies),)])
        self.assertEqual(everything[0]["reply_count"], len(replies))
        self.assertEqual(everything[0]["newest_reply_id"], 4)

        # 7. Aiko blocks Ken. He cannot reply to her post any more, and she no
        #    longer counts his replies; nobody else's count changes.
        self.page_sends(aiko, "/blocks", {"account_name": "ken"}, "POST")
        code, reason = self.is_refused(self.page_sends, ken, "/posts",
                                       {"text": "hello?", "parent_id": 1}, "POST")
        self.assertEqual((code, reason), (400, "You cannot reply to this post."))
        mine = self.page_asks_for_new_posts(aiko)
        self.assertEqual([p["id"] for p in mine], [1, 4])
        self.assertEqual((mine[0]["reply_count"], mine[0]["newest_reply_id"]), (1, 4))
        self.assertEqual(self.page_asks_for_new_posts(self.open_window())[0]["reply_count"], 3)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM posts WHERE parent_id = 1"), [(3,)])

    # -- edit-delete --

    def page_asks_for_changes(self, window, after=None):
        """checkForChanges: GET /changes the first time, then GET /changes?after=<latest>"""
        path = "/changes" if after is None else "/changes?after=" + str(after)
        with window.open(self.base + path) as answer:
            return json.loads(answer.read())

    def page_edits(self, window, post_id, text):
        """sendEdit: PATCH /posts, with the post id and the new words"""
        return self.page_sends(window, "/posts", {"post_id": post_id, "text": text}, "PATCH")

    def page_deletes(self, window, post_id):
        """deletePost: DELETE /posts, with the post id"""
        return self.page_sends(window, "/posts", {"post_id": post_id}, "DELETE")

    def page_replies(self, window, post_id, text):
        """sendPost while replying: POST /posts with parent_id"""
        return self.page_sends(window, "/posts", {"text": text, "parent_id": post_id}, "POST")

    def code_of(self, send, *arguments):
        """The status and the code of a request the server refuses."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            send(*arguments)
        answer = json.loads(caught.exception.read())
        caught.exception.close()
        return caught.exception.code, answer["code"]

    def test_the_whole_journey_of_an_edit_and_a_delete(self):
        clock = use_fake_clock(self)
        patcher = mock.patch.object(server, "utc_now", lambda: SOME_MOMENT)
        patcher.start()
        self.addCleanup(patcher.stop)
        aiko = self.open_window()
        ben = self.open_window()
        watcher = self.open_window()   # no login: it only watches

        # 1. Aiko and Ben sign up. Aiko posts; Ben likes it.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ben, "ben", "Ben Ito")
        status, post = self.page_posts(aiko, "Lunch at noon")
        post_id = post["id"]
        self.page_presses_heart(ben, post_id, False)
        self.assertEqual((post["edited"], post["deleted"]), (False, False))

        # 2. The watcher opens the page: changes first, then posts.
        latest = self.page_asks_for_changes(watcher)["latest"]
        self.assertEqual(latest, 0)
        self.assertEqual([p["id"] for p in self.page_asks_for_new_posts(watcher)], [post_id])

        # 3. Aiko edits. The watcher hears of it, with the new words.
        status, edited = self.page_edits(aiko, post_id, "Lunch at one")
        self.assertEqual((status, edited["text"], edited["edited"], edited["like_count"]),
                         (200, "Lunch at one", True, 1))
        answer = self.page_asks_for_changes(watcher, latest)
        self.assertEqual([(c["post_id"], c["post"]["text"], c["post"]["edited"])
                          for c in answer["changes"]], [(post_id, "Lunch at one", True)])
        latest = answer["latest"]
        self.assertEqual(self.rows("SELECT text FROM posts"), [("Lunch at one",)])
        self.assertEqual(self.rows("SELECT post_id, text FROM post_versions"),
                         [(post_id, "Lunch at noon")])
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(post_id, 2)])

        # 4. Ben tries to edit and to delete Aiko's post: 403, and nothing changes.
        tables = ("posts", "likes", "post_versions", "changes")
        before = [self.rows("SELECT * FROM " + t) for t in tables]
        self.assertEqual(self.code_of(self.page_edits, ben, post_id, "Ben was here"),
                         (403, "post_not_yours"))
        self.assertEqual(self.code_of(self.page_deletes, ben, post_id), (403, "post_not_yours"))
        self.assertEqual([self.rows("SELECT * FROM " + t) for t in tables], before)
        self.assertEqual(self.page_asks_for_changes(watcher, latest)["changes"], [])

        # 5. Aiko deletes it. The watcher is told to take it away; nothing of it stays.
        self.assertEqual(self.page_deletes(aiko, post_id),
                         (200, {"post_id": post_id, "post": None}))
        answer = self.page_asks_for_changes(watcher, latest)
        self.assertEqual([(c["post_id"], c["kind"], c["post"]) for c in answer["changes"]],
                         [(post_id, "deleted", None)])
        latest = answer["latest"]
        for table in ("posts", "likes", "post_versions"):
            self.assertEqual(self.rows("SELECT * FROM " + table), [])

        # 6. Aiko posts again: a larger id, so the watcher's next question brings it.
        clock.move(61)
        status, again = self.page_posts(aiko, "Lunch is cancelled")
        self.assertGreater(again["id"], post_id)
        self.assertEqual([p["id"] for p in self.page_asks_for_new_posts(watcher, post_id)],
                         [again["id"]])

        # 7. Ben replies, then Aiko deletes her post. It has a reply, so it stays
        #    as "This post was deleted", with the reply under it.
        status, reply = self.page_replies(ben, again["id"], "Oh no!")
        self.assertEqual(status, 201)
        status, answer = self.page_deletes(aiko, again["id"])
        self.assertEqual((status, answer["post"]["deleted"], answer["post"]["text"],
                          answer["post"]["reply_count"]), (200, True, "", 1))
        answer = self.page_asks_for_changes(watcher, latest)
        self.assertEqual([(c["post_id"], c["post"]["deleted"]) for c in answer["changes"]],
                         [(again["id"], True)])
        latest = answer["latest"]
        self.assertEqual(self.rows("SELECT id, text, deleted_at IS NOT NULL, parent_id "
                                   "FROM posts ORDER BY id"),
                         [(again["id"], "", 1, None), (reply["id"], "Oh no!", 0, again["id"])])
        shown = self.page_asks_for_new_posts(watcher, post_id)
        self.assertEqual([(p["id"], p["deleted"]) for p in shown],
                         [(again["id"], True), (reply["id"], False)])

        # 8. Nobody can answer, like or edit a deleted post.
        self.assertEqual(self.code_of(self.page_replies, ben, again["id"], "Still there?"),
                         (400, "reply_to_deleted"))
        self.assertEqual(self.code_of(self.page_presses_heart, ben, again["id"], False),
                         (400, "post_missing"))
        self.assertEqual(self.code_of(self.page_edits, aiko, again["id"], "back"),
                         (400, "post_deleted"))

        # 9. Ben deletes his reply, the last one: Aiko's deleted post goes too.
        self.assertEqual(self.page_deletes(ben, reply["id"]),
                         (200, {"post_id": reply["id"], "post": None}))
        answer = self.page_asks_for_changes(watcher, latest)
        self.assertEqual([(c["post_id"], c["post"]) for c in answer["changes"]],
                         [(reply["id"], None), (again["id"], None)])
        self.assertEqual(self.rows("SELECT * FROM posts"), [])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    # -- report --

    def page_reports(self, window, post_id, reason=None):
        """pressReport: POST /reports, with the post and the reason (null if none)"""
        return self.page_sends(window, "/reports", {"post_id": post_id, "reason": reason},
                               "POST")

    def page_takes_report_back(self, window, post_id):
        """pressReport: DELETE /reports"""
        return self.page_sends(window, "/reports", {"post_id": post_id, "reason": None},
                               "DELETE")

    def page_asks_for_reports(self, window):
        """askForReports: GET /reports, on opening, after a login and after a press"""
        with window.open(self.base + "/reports") as answer:
            return json.loads(answer.read())

    def ids_seen(self, window):
        return [post["id"] for post in self.page_asks_for_new_posts(window)]

    def test_the_whole_journey_of_a_report(self):
        windows = {}
        for name in ("aiko", "ben", "chika", "dai", "emi"):
            windows[name] = self.open_window()
            self.page_signs_up(windows[name], name, name.title())
        aiko, ben, chika, dai, emi = (windows[n] for n in ("aiko", "ben", "chika", "dai", "emi"))
        stranger = self.open_window()   # nobody logged in
        for name in ("ben", "chika", "dai"):
            self.page_posts(windows[name], name + " was here first")
        status, post = self.page_posts(aiko, "the target")
        target = post["id"]
        reports = "SELECT user_id, reason FROM reports ORDER BY user_id"
        ids = dict(self.rows("SELECT name, id FROM users"))
        # Every window has asked the changes feed where it is, as checkForChanges does.
        latest = {name: self.page_asks_for_changes(w)["latest"]
                  for name, w in (("aiko", aiko), ("ben", ben), ("stranger", stranger))}

        # Aiko cannot report her own post.
        code, answer = self.is_refused(self.page_reports, aiko, target)
        self.assertEqual((code, answer), (400, "You cannot report your own post."))
        self.assertEqual(self.rows(reports), [])

        # Ben reports it, with a reason; a second time is refused; he takes it back.
        self.assertEqual(self.page_reports(ben, target, "spam"),
                         (201, {"post_id": target, "reported": True}))
        self.assertEqual(self.rows(reports), [(ids["ben"], "spam")])
        self.assertEqual(self.is_refused(self.page_reports, ben, target)[0], 400)
        self.assertEqual(self.rows(reports), [(ids["ben"], "spam")])
        self.assertEqual(self.page_takes_report_back(ben, target),
                         (200, {"post_id": target, "reported": False}))
        self.assertEqual(self.rows(reports), [])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM changes"), [(0,)])   # never crossed

        # Ben, Chika and Dai report it: three rows, and one "hidden" change.
        for window in (ben, chika, dai):
            self.assertEqual(self.page_reports(window, target)[0], 201)
        self.assertEqual(len(self.rows(reports)), 3)
        self.assertEqual(self.rows("SELECT post_id, kind FROM changes"), [(target, "hidden")])

        # Open windows hear it from the changes feed: Ben's and the stranger's
        # get no post (applyChange takes it away); Aiko's gets her post, faded.
        for name, window in (("ben", ben), ("stranger", stranger)):
            changes = self.page_asks_for_changes(window, latest[name])["changes"]
            self.assertEqual([(c["post_id"], c["kind"], c["post"]) for c in changes],
                             [(target, "hidden", None)])
        changes = self.page_asks_for_changes(aiko, latest["aiko"])["changes"]
        self.assertEqual([(c["post_id"], c["kind"]) for c in changes], [(target, "hidden")])
        self.assertEqual(changes[0]["post"]["text"], "the target")
        self.assertTrue(changes[0]["post"]["hidden_by_reports"])

        # Emi has never posted, so she cannot report it.
        code, answer = self.is_refused(self.page_reports, emi, target)
        self.assertEqual(code, 400)
        self.assertIn("only after you have posted", answer)
        self.assertEqual(len(self.rows(reports)), 3)

        # Hidden from Ben, Emi and a window not logged in; Aiko still sees it.
        for window in (ben, emi, stranger):
            self.assertNotIn(target, self.ids_seen(window))
        self.assertIn(target, self.ids_seen(aiko))
        self.assertEqual(self.page_asks_for_reports(ben),
                         {"hidden": [target], "mine_hidden": [], "reported": [target]})
        self.assertEqual(self.page_asks_for_reports(aiko),
                         {"hidden": [], "mine_hidden": [target], "reported": []})
        self.assertEqual(self.page_asks_for_reports(stranger),
                         {"hidden": [target], "mine_hidden": [], "reported": []})
        self.assertEqual(self.rows(f"SELECT text FROM posts WHERE id = {target}"),
                         [("the target",)])

        # Dai takes his report back: a "shown" change, and everyone sees it again.
        latest_now = self.page_asks_for_changes(ben)["latest"]
        self.page_takes_report_back(dai, target)
        changes = self.page_asks_for_changes(ben, latest_now)["changes"]
        self.assertEqual([(c["kind"], c["post"]["text"]) for c in changes],
                         [("shown", "the target")])
        self.assertFalse(changes[0]["post"]["hidden_by_reports"])
        for window in (ben, emi, stranger, aiko):
            self.assertIn(target, self.ids_seen(window))
        self.assertEqual(len(self.rows(reports)), 2)

        # A "user_id" in the JSON is ignored: Dai reports as Dai, from the cookie.
        self.page_sends(dai, "/reports", {"post_id": target, "user_id": ids["ben"]}, "POST")
        self.assertEqual(self.rows("SELECT user_id FROM reports ORDER BY user_id"),
                         [(ids["ben"],), (ids["chika"],), (ids["dai"],)])


    # -- links-and-tags --

    def test_a_post_with_links_tags_and_code_is_kept_letter_for_letter(self):
        # The server neither changes nor refuses such a post: drawing it safely
        # (links as <a>, everything else as words) is the page's job.
        use_fake_clock(self)
        aiko = self.open_window()
        self.page_signs_up(aiko, "aiko", "Aiko")
        text = "see https://x.com. #kyoto @ben javascript:alert(1) <b>hi</b>"
        status, saved = self.page_posts(aiko, text)
        self.assertEqual(status, 201)
        self.assertEqual(saved["text"], text)

        # 1. GET /posts gives it back exactly, with the same keys as any post.
        answer = self.page_asks_for_new_posts(aiko)
        post = [post for post in answer if post["id"] == saved["id"]][0]
        self.assertEqual(post["text"], text)
        self.assertEqual(set(post), set(saved))
        self.assertNotIn("pieces", post)

        # 2. The database file holds exactly the same text.
        connection = server.connect(self.db_path)
        stored = connection.execute("SELECT text FROM posts WHERE id = ?",
                                    (saved["id"],)).fetchone()[0]
        connection.close()
        self.assertEqual(stored, text)

        # 3. A search for the #tag finds it, as a click on the tag would.
        status, found = self.page_searches(aiko, "#Kyoto")
        self.assertEqual([post["id"] for post in found["posts"]], [saved["id"]])

class BookmarkJourneyTest(unittest.TestCase):
    """The journey of a private bookmark, through all three levels at once.

    It borrows JourneyTest's server, windows and helpers (not its tests, so
    those do not run twice). Every request below is one the page makes: see
    `loadBookmarks` and `pressBookmark` in `app.js`.
    """

    setUp = JourneyTest.setUp
    tearDown = JourneyTest.tearDown
    open_window = JourneyTest.open_window
    page_sends = JourneyTest.page_sends
    page_signs_up = JourneyTest.page_signs_up
    page_logs_out = JourneyTest.page_logs_out
    page_posts = JourneyTest.page_posts
    page_presses_heart = JourneyTest.page_presses_heart
    is_refused = JourneyTest.is_refused
    rows = JourneyTest.rows

    def page_asks_for_bookmarks(self, window, query=""):
        """loadBookmarks: GET /bookmarks. Who is asking comes from the cookie."""
        with window.open(self.base + "/bookmarks" + query) as answer:
            return json.loads(answer.read())

    def page_presses_star(self, window, post_id, already_saved):
        """pressBookmark: POST /bookmarks to save, DELETE /bookmarks to take it back"""
        return self.page_sends(window, "/bookmarks", {"post_id": post_id},
                               "DELETE" if already_saved else "POST")

    def public_bytes(self, window):
        """The exact bytes of the two answers every window reads every second."""
        answers = []
        for path in ("/posts?after=0", "/likes"):
            with window.open(self.base + path) as answer:
                answers.append(answer.read())
        return answers

    def test_the_whole_journey_of_a_private_bookmark(self):
        aiko = self.open_window()
        ben = self.open_window()
        nobody = self.open_window()

        # 1. Aiko and Ben sign up. Aiko posts twice; Ben posts once.
        self.page_signs_up(aiko, "aiko", "Aiko Tanaka")
        self.page_signs_up(ben, "ben", "Ben Ito")
        aiko_id = self.rows("SELECT id FROM users WHERE name = 'aiko'")[0][0]
        ben_id = self.rows("SELECT id FROM users WHERE name = 'ben'")[0][0]
        self.page_posts(aiko, "Aiko one")
        self.page_posts(aiko, "Aiko two")
        status, bens_post = self.page_posts(ben, "Ben's post")
        self.page_presses_heart(ben, bens_post["id"], False)

        # 2. What Ben and a window with no login read, byte for byte.
        ben_before, nobody_before = self.public_bytes(ben), self.public_bytes(nobody)

        # 3. Aiko bookmarks Ben's post: one row, her id and that post's id.
        status, answer = self.page_presses_star(aiko, bens_post["id"], False)
        self.assertEqual((status, answer), (201, {"post_id": bens_post["id"],
                                                  "bookmarked": True}))
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [(aiko_id, bens_post["id"])])

        # 4. Privacy: nobody else can tell. The public answers are the same bytes.
        self.assertEqual(self.public_bytes(ben), ben_before)
        self.assertEqual(self.public_bytes(nobody), nobody_before)
        self.assertEqual(self.page_asks_for_bookmarks(ben), [])
        self.assertEqual(self.page_asks_for_bookmarks(ben, "?user=aiko"), [])
        self.assertEqual(self.page_asks_for_bookmarks(ben, "?author=aiko&user_id=1"), [])
        code, reason = self.is_refused(self.page_asks_for_bookmarks, nobody)
        self.assertEqual(code, 401)

        # 5. Ben names Aiko in the JSON: it is ignored, and the row is his.
        status, answer = self.page_sends(ben, "/bookmarks", {"post_id": bens_post["id"],
                                                             "user_id": aiko_id,
                                                             "author": "aiko"}, "POST")
        self.assertEqual(status, 201)
        self.assertEqual(self.rows("SELECT * FROM bookmarks ORDER BY user_id"),
                         [(aiko_id, bens_post["id"]), (ben_id, bens_post["id"])])

        # 6. Ben takes his back, then tries again: refused, and Aiko's row stays.
        self.page_presses_star(ben, bens_post["id"], True)
        code, reason = self.is_refused(self.page_presses_star, ben, bens_post["id"], True)
        self.assertEqual((code, reason), (400, "You have not bookmarked that post."))
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [(aiko_id, bens_post["id"])])

        # 7. Aiko's list is exactly her one post. She takes it back: the row is gone.
        mine = self.page_asks_for_bookmarks(aiko)
        self.assertEqual([post["id"] for post in mine], [bens_post["id"]])
        self.assertEqual(mine[0]["like_count"], 1)
        status, answer = self.page_presses_star(aiko, bens_post["id"], True)
        self.assertEqual((status, answer), (200, {"post_id": bens_post["id"],
                                                  "bookmarked": False}))
        self.assertEqual(self.rows("SELECT * FROM bookmarks"), [])

        # 8. Aiko logs out: her old cookie no longer reads any bookmarks.
        self.page_presses_star(aiko, bens_post["id"], False)
        self.page_logs_out(aiko)
        code, reason = self.is_refused(self.page_asks_for_bookmarks, aiko)
        self.assertEqual(code, 401)
        # Nothing about bookmarks changed the users or the likes.
        self.assertEqual(len(self.rows("SELECT * FROM users")), 2)
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"),
                         [(bens_post["id"], ben_id)])



class PageAndServerAgreeTest(unittest.TestCase):
    """AGENTS.md: "the page and the server must agree".

    The page's own code cannot run here, because that would need a browser or
    Node, and this project needs only python3. So instead these read `app.js`
    and check that every request it names is one the real server answers, that
    it sends the JSON names the server reads, and that it has the same rules.
    A name changed on one side and not the other fails here.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.server = server.make_server(0, os.path.join(self.folder.name, "test.db"))
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        with open(os.path.join(HERE, "app.js"), encoding="utf-8") as page_file:
            self.page_code = page_file.read()
        with open(os.path.join(HERE, "server.py"), encoding="utf-8") as server_file:
            self.server_code = server_file.read()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    def answer_code(self, method, path):
        """The status the server gives this request, whether it likes it or not."""
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps({}).encode("utf-8") if method in ("POST", "PATCH", "DELETE")
            else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request) as answer:
                return answer.status
        except urllib.error.HTTPError as refused:
            code = refused.code
            refused.close()
            return code

    def test_the_page_asks_only_for_routes_the_server_answers(self):
        asked = set(re.findall(r'fetch\("(/[a-z]*)', self.page_code))
        self.assertEqual(asked, {"/posts", "/likes", "/sessions", "/accounts",
                                 "/likers", "/likesummary", "/search", "/bookmarks",
                                 "/blocks", "/changes", "/versions", "/reports"})

    def test_the_page_names_only_the_methods_tried_below(self):
        # A GET needs no method, so the page names only the others.
        named = set(re.findall(r'"(GET|POST|PUT|PATCH|DELETE)"', self.page_code))
        self.assertEqual(named, {"POST", "PATCH", "DELETE"})

    def test_the_server_answers_every_request_the_page_makes(self):
        for method, path in [("GET", "/posts?after=0"), ("POST", "/posts"),
                             ("GET", "/likes"), ("POST", "/likes"), ("DELETE", "/likes"),
                             ("GET", "/sessions"), ("POST", "/sessions"),
                             ("DELETE", "/sessions"), ("POST", "/accounts"),
                             ("GET", "/blocks"), ("POST", "/blocks"), ("DELETE", "/blocks"),
                             ("PATCH", "/posts"), ("DELETE", "/posts"), ("GET", "/changes"),
                             ("GET", "/changes?after=0"), ("GET", "/versions?post_id=1"),
                             ("GET", "/reports"), ("POST", "/reports"), ("DELETE", "/reports")]:
            with self.subTest(request=method + " " + path):
                code = self.answer_code(method, path)
                # 400 or 401 is a fine answer here: the body is empty and nobody
                # is logged in, on purpose. 404 or 501 would mean the server
                # does not know this request at all.
                self.assertNotIn(code, (404, 501))

    def test_the_page_sends_exactly_the_json_names_the_server_reads(self):
        sent = set()
        for inside in re.findall(r"JSON\.stringify\(\{([^}]*)\}\)", self.page_code):
            sent.update(re.findall(r"(\w+):", inside))
        read = set(re.findall(r'data\.get\("(\w+)"\)', self.server_code))
        self.assertEqual(sent, read)
        # And never a name: who is asking comes from the cookie.
        self.assertNotIn("author", sent)

    def test_the_page_shows_the_names_the_server_sends(self):
        for name in ("post.display_name", "post.author", "who.display_name",
                     "who.account_name"):
            self.assertIn(name, self.page_code)

    def test_the_page_has_the_same_patterns_as_the_model(self):
        self.assertIn(server.ACCOUNT_NAME.pattern, self.page_code)
        self.assertIn(server.HIDDEN_CHARACTERS.pattern, self.page_code)

    def test_the_page_has_the_same_limits_as_the_model(self):
        for name in ("MAX_TEXT", "MAX_AUTHOR", "MAX_DISPLAY_NAME", "MIN_PASSWORD",
                     "MAX_PASSWORD"):
            with self.subTest(limit=name):
                self.assertIn(f"const {name} = {getattr(server, name)};", self.page_code)

    def test_the_two_style_files_are_the_same(self):
        with open(os.path.join(HERE, "style.css"), "rb") as one:
            with open(os.path.join(HERE, "..", "page-only", "style.css"), "rb") as other:
                self.assertEqual(one.read(), other.read())

    # -- groundwork --

    def test_every_data_action_has_an_entry_in_actions(self):
        used = set(re.findall(r'dataset\.action = "(\w+)"', self.page_code))
        used.update(re.findall(r'addMenuItem\(\w+, "(\w+)"', self.page_code))
        handled = set(re.findall(r"ACTIONS\.(\w+) = ", self.page_code))
        self.assertIn("like", used)
        self.assertLessEqual(used, handled)
        self.assertNotIn("likeParts", self.page_code)   # replaced by postParts

    def test_show_post_builds_the_post_with_make_post_item(self):
        show_post = re.search(r"\nfunction showPost\(post\) \{\n(.*?)\n\}\n",
                              self.page_code, re.DOTALL).group(1)
        self.assertIn("makePostItem(post)", show_post)
        self.assertIn("placePost(", show_post)

    def test_nothing_new_shows_yet(self):
        # The "⋯" menu starts hidden, and only addMenuItem shows it. (block is
        # the first to call addMenuItem: see test_the_page_never_offers_to_block_yourself.)
        # The views nav starts hidden, with one view.
        self.assertIn("menu.hidden = true;", self.page_code)
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            nav = re.search(r'<nav id="views"[^>]*>', page_file.read()).group(0)
        self.assertIn('aria-label="Views"', nav)
        self.assertIn(" hidden", nav)
        # The timeline, and the views features add: search and bookmarks.
        views = re.findall(r'\baddView\("(\w+)"', self.page_code)
        self.assertEqual(sorted(views), ["bookmarks", "search", "timeline"])

    def test_posts_with_authors_is_used_only_in_select_posts_and_post_by_id(self):
        # Read server.py as Python, and count each use of POSTS_WITH_AUTHORS by
        # the function it is in. A new query that read posts some other way
        # would get round visible_to.
        uses = {}
        for function in ast.walk(ast.parse(self.server_code)):
            if isinstance(function, ast.FunctionDef):
                for node in ast.walk(function):
                    if isinstance(node, ast.Name) and node.id == "POSTS_WITH_AUTHORS":
                        uses[function.name] = uses.get(function.name, 0) + 1
        self.assertEqual(uses, {"select_posts": 1, "post_by_id": 1})

    def test_the_request_limit_is_big_enough_for_a_picture(self):
        # pictures will allow 2 MB. Written as base64 text it is a third bigger,
        # plus the rest of the JSON. pictures will make this check exact.
        picture = 2 * 1024 * 1024
        as_text = (picture + 2) // 3 * 4
        self.assertGreaterEqual(server.MAX_REQUEST_BYTES, as_text + 1024)

    # -- long-posts --
    # MAX_TEXT itself is already compared in test_the_page_has_the_same_limits_as_the_model.

    def function_body(self, name):
        """The text of one top-level function in app.js."""
        return re.search(r"\nfunction " + name + r"\([^)]*\) \{\n(.*?)\n\}\n",
                         self.page_code, re.DOTALL).group(1)

    def test_the_page_counts_characters_as_python_does(self):
        self.assertIn("return [...text].length;", self.function_body("characterCount"))
        self.assertIn("characterCount(text) > MAX_TEXT", self.function_body("textProblem"))
        self.assertIn("characterCount(textBox.value)", self.function_body("updateCount"))
        self.assertNotIn("text.length", self.function_body("textProblem"))
        self.assertNotIn("value.length", self.function_body("updateCount"))

    def test_the_html_does_not_write_the_limit(self):
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            page = page_file.read()
        self.assertNotIn("/ 280", page)
        self.assertNotIn("/ 560", page)
        # updateCount(); with no indent is a start-up line, outside every function.
        self.assertIn("\nupdateCount();\n", self.page_code)

    def test_a_long_post_is_folded_by_the_css_the_page_uses(self):
        for folder in (HERE, os.path.join(HERE, "..", "page-only")):
            with open(os.path.join(folder, "style.css"), encoding="utf-8") as css_file:
                css = css_file.read()
            with self.subTest(folder=folder):
                rule = re.search(r"\.post-text\.collapsed \{(.*?)\}", css, re.DOTALL).group(1)
                self.assertIn("-webkit-line-clamp: 6;", rule)
                self.assertIn("display: -webkit-box;", rule)
                self.assertIn("overflow: hidden;", rule)
                self.assertIn(".show-more {", css)
        self.assertIn('classList.add("collapsed")', self.page_code)
        self.assertIn('classList.toggle("collapsed")', self.page_code)
        self.assertIn('className = "show-more"', self.page_code)

    def test_the_show_more_button_is_accessible(self):
        make = self.function_body("makeExpandable")
        self.assertIn('button.type = "button";', make)
        self.assertIn('"aria-expanded", "false"', make)
        self.assertIn('"aria-controls"', make)
        self.assertIn('"aria-expanded"', self.function_body("toggleExpanded"))
        # The text is only clipped by the CSS, never hidden from a screen reader.
        self.assertNotIn("textElement.hidden", self.page_code)
        self.assertNotIn("aria-hidden", self.page_code)

    def test_show_more_goes_through_the_shared_pieces(self):
        # A part, not a change to showPost; an entry in ACTIONS, not a change to clickOnTimeline.
        self.assertIn("makeExpandable(", self.page_code.split("function expandablePart")[1])
        self.assertIn('dataset.action = "expand"', self.function_body("makeExpandable"))
        self.assertIn("ACTIONS.expand = toggleExpanded;", self.page_code)
        self.assertNotIn("expand", self.function_body("clickOnTimeline"))
        self.assertNotIn("makeExpandable", self.function_body("showPost"))
        # The height is measured again whenever the text changes size on the page.
        self.assertIn("textSizeWatcher.observe(textElement);", self.function_body("makeExpandable"))

    # -- who-liked --

    def test_the_server_answers_the_who_liked_requests(self):
        for path in ("/likers?post_id=1", "/likesummary?post_ids=1"):
            with self.subTest(path=path):
                self.assertNotIn(self.answer_code("GET", path), (404, 501))

    def test_the_page_asks_for_at_most_as_many_posts_as_the_model_allows(self):
        self.assertIn(f"const MAX_SUMMARY_POSTS = {server.MAX_SUMMARY_POSTS};", self.page_code)

    def test_the_page_reads_the_names_the_who_liked_answers_have(self):
        likers = server.likers_to_json(1, [{"name": "a", "display_name": "A"}], 1)
        summaries = server.summaries_to_json(
            {1: {"like_count": 1, "you": False,
                 "leaders": [{"name": "a", "display_name": "A"}]}})
        keys = set(likers) | set(likers["likers"][0]) | set(summaries) \
            | set(summaries["summaries"]["1"])
        for key in ("likers", "summaries", "leaders", "you", "account_name", "display_name",
                    "like_count"):
            with self.subTest(key=key):
                self.assertIn("." + key, self.page_code)
                self.assertIn(key, keys)

    def test_the_page_never_uses_inner_html(self):
        self.assertNotIn("innerHTML =", self.page_code)
        self.assertNotIn("insertAdjacentHTML", self.page_code)


    # -- timestamps --

    def test_the_page_reads_both_times_the_server_sends(self):
        self.assertIn("post.posted_at", self.page_code)
        self.assertIn("post.old_clock_time", self.page_code)
        self.assertNotIn("textContent = post.posted_at", self.page_code)

    def test_the_page_makes_a_time_element_and_refreshes_it(self):
        self.assertIn('createElement("time")', self.page_code)
        self.assertIn('"datetime"', self.page_code)
        self.assertIn("setInterval(refreshTimes", self.page_code)

    def test_the_page_never_sends_a_time(self):
        for inside in re.findall(r"JSON\.stringify\(\{([^}]*)\}\)", self.page_code):
            self.assertNotIn("posted_at", inside)

    def test_the_page_and_the_server_agree_on_429(self):
        self.assertIn("response.status === 429", self.page_code)
        self.assertIn("answer.retry_after", self.page_code)
        self.assertEqual(set(server.too_fast_to_json(server.TooFast("post_too_fast", 3))),
                         {"error", "code", "values", "retry_after"})

    def test_every_request_that_can_be_too_fast_has_a_refused_branch(self):
        functions = functions_in(self.page_code)
        # The five requests the server limits, and the page function that sends each.
        for name, form in (("sendPost", "postForm"), ("logIn", "loginForm"),
                           ("signUp", "signupForm"), ("pressHeart", None)):
            with self.subTest(function=name):
                self.assertIn("!response.ok", functions[name])
                if form is not None:
                    self.assertIn(f"holdForm({form}, answer.retry_after)", functions[name])

    # -- timeline-flow --

    def test_the_page_has_the_same_page_size(self):
        size = re.search(r"\nconst PAGE_SIZE = (\d+);", self.page_code)
        self.assertIsNotNone(size)
        self.assertEqual(int(size.group(1)), server.PAGE_SIZE)

    def test_the_server_answers_the_paging_requests(self):
        for path in ("/posts?before=0", "/likes?from=0"):
            with self.subTest(path=path):
                self.assertNotIn(self.answer_code("GET", path), (404, 501))

    def test_the_page_asks_with_before_and_from(self):
        self.assertIn('"/posts?before="', self.page_code)
        self.assertIn('"/likes?from="', self.page_code)

    def test_the_page_has_the_flow_elements(self):
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            html = page_file.read()
        for element_id in ("new-posts", "older-posts", "load-older"):
            with self.subTest(element=element_id):
                self.assertIn(f'id="{element_id}"', html)
                self.assertIn(f'document.getElementById("{element_id}")', self.page_code)
        self.assertIn('tabindex="-1"', html)

    def test_older_posts_go_through_the_shared_pieces(self):
        # Older posts go at the bottom through placePost, built by makePostItem,
        # and are kept in postParts, so their hearts and who-liked lines are
        # kept up to date. Every time on the page is refreshed, wherever it is.
        functions = functions_in(self.page_code)
        self.assertIn('putPost(post, "bottom")', functions["loadOlderPosts"])
        self.assertIn("makePostItem(post)", functions["putPost"])
        self.assertIn("placePost(", functions["putPost"])
        self.assertIn("postParts[post.id]", functions["putPost"])
        self.assertIn('document.querySelectorAll("time[data-relative]")',
                      functions["refreshTimes"])
        self.assertIn("receiveNewPosts(posts)", functions["checkForNewPosts"])
        self.assertIn("showWaitingPosts()", functions["sendPost"])

    # -- place --

    def test_the_page_has_the_same_place_limit_and_sentences(self):
        self.assertIn(f"const MAX_PLACE = {server.MAX_PLACE};", self.page_code)
        problem = functions_in(self.page_code)["placeProblem"]
        # The page uses the same two codes as the model, and each is in PROBLEMS.
        self.assertEqual(re.findall(r'key: "(\w+)"', problem), ["place_too_long", "place_hidden"])
        self.assertIn("values: { limit: MAX_PLACE }", problem)
        self.assertIn("HIDDEN_CHARACTERS.test(place)", problem)
        with self.assertRaises(server.RuleBroken) as caught:
            server.check_place("a" * (server.MAX_PLACE + 1))
        self.assertEqual((caught.exception.code, caught.exception.values),
                         ("place_too_long", {"limit": server.MAX_PLACE}))
        self.assertEqual(str(caught.exception),
                         f"The place must be {server.MAX_PLACE} characters or fewer.")
        with self.assertRaises(server.RuleBroken) as caught:
            server.check_place("a\tb")
        self.assertEqual(caught.exception.code, "place_hidden")
        self.assertEqual(str(caught.exception),
                         "The place must not have hidden characters or line breaks.")

    def test_the_page_sends_and_shows_the_place(self):
        functions = functions_in(self.page_code)
        self.assertIn("place: place", functions["sendPost"])
        self.assertIn("placeProblem(", functions["sendPost"])
        # "· {place}" is one key; the place itself is never a key.
        self.assertIn('say("post_place", { place: post.place })', self.page_code)
        self.assertIn("redrawPlaces", self.page_code)
        self.assertIn("slots.head.append(place)", self.page_code)

    def test_the_place_is_remembered_in_this_browser_and_forgotten_on_log_out(self):
        functions = functions_in(self.page_code)
        self.assertIn('const PLACE_KEY = "timeline-place";', self.page_code)
        self.assertIn("rememberPlace(", functions["sendPost"])
        send = functions["sendPost"]
        self.assertGreater(send.index("rememberPlace("), send.index("if (!response.ok)"))
        self.assertIn("forgetPlace()", functions["logOut"])
        self.assertIn("placeBox.value = rememberedPlace();", self.page_code)

    def test_the_place_box_says_everyone_can_see_it(self):
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page:
            html = page.read()
        self.assertIn('<label for="place" class="place-label" data-words="place_label">'
                      'Place (anyone can see this)</label>', html)
        self.assertIn('data-words-placeholder="place_example"', html)
        self.assertIn('<input id="place" type="text"', html)


    # -- search --

    def test_the_server_answers_the_search_request(self):
        self.assertNotIn(self.answer_code("GET", "/search?q=x"), (404, 501))

    def test_the_page_has_the_same_tag_pattern_and_search_limits(self):
        self.assertIn(server.TAG.pattern, self.page_code)
        for name in ("MAX_QUERY", "MAX_QUERY_WORDS", "SEARCH_LIMIT"):
            with self.subTest(limit=name):
                self.assertIn(f"const {name} = {getattr(server, name)};", self.page_code)
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            self.assertIn(f'maxlength="{server.MAX_QUERY}"', page_file.read())

    def test_the_page_has_search_for_for_links_and_tags(self):
        functions = functions_in(self.page_code)
        self.assertIn("searchFor", functions)
        self.assertIn('fetch("/search?q=" + encodeURIComponent(query))', functions["runSearch"])
        self.assertIn('"/?q=" + encodeURIComponent(query)', functions["searchAddress"])
        self.assertIn("window.addEventListener(\"popstate\", searchFromAddress);", self.page_code)
        self.assertIn("\nsearchFromAddress();\n", self.page_code)

    def test_the_page_checks_the_same_search_rules(self):
        problem = functions_in(self.page_code)["queryProblem"]
        self.assertIn("characterCount(trimmed) > MAX_QUERY", problem)
        self.assertIn("> MAX_QUERY_WORDS", problem)
        # The same codes as check_query (japanese: the words are in words.js).
        for code in ("search_empty", "search_too_long", "search_too_many_words"):
            self.assertIn('key: "' + code + '"', problem)
            self.assertIn(code, server.PROBLEMS)

    def test_search_results_go_through_the_shared_pieces(self):
        results = functions_in(self.page_code)["showResults"]
        self.assertIn("makePostItem(post)", results)
        self.assertNotIn("postParts", results)
        self.assertIn("likeButton.disabled = true", results)
        self.assertIn('showView("search")', results)
        self.assertIn('resultsList.addEventListener("click", clickOnTimeline);', self.page_code)
        self.assertNotIn("search", functions_in(self.page_code)["makePostItem"])

    def test_search_reads_posts_through_select_posts(self):
        search = re.search(r"\ndef search_posts\(.*?\n(?=\n\n)", self.server_code,
                           re.DOTALL).group(0)
        self.assertIn("select_posts(", search)
    # -- bookmarks --

    def test_the_server_answers_every_bookmark_request(self):
        for method in ("GET", "POST", "DELETE"):
            with self.subTest(method=method):
                self.assertEqual(self.answer_code(method, "/bookmarks"), 401)

    def test_a_bookmark_sends_only_the_post_id(self):
        press = functions_in(self.page_code)["pressBookmark"]
        self.assertIn('fetch("/bookmarks"', press)
        self.assertIn("JSON.stringify({ post_id: postId })", press)
        for name in ("author", "user", "user_id", "account"):
            self.assertNotRegex(press, r"\b" + name + r":")

    def test_bookmarks_are_not_asked_for_every_second(self):
        functions = functions_in(self.page_code)
        for name in ("checkForNewPosts", "keepChecking"):
            self.assertNotIn("/bookmarks", functions[name])
            self.assertNotIn("loadBookmarks", functions[name])

    def test_the_star_goes_through_the_shared_pieces(self):
        self.assertIn("addPostPart(function bookmarkPart", self.page_code)
        self.assertIn("ACTIONS.bookmark = pressBookmark;", self.page_code)
        self.assertIn('addView("bookmarks"', self.page_code)
        list_code = functions_in(self.page_code)["showBookmarkList"]
        self.assertIn("makePostItem(post)", list_code)
        self.assertNotIn("postParts", list_code)   # only the live timeline is kept there

    def test_logging_out_clears_the_bookmarks_from_the_screen(self):
        functions = functions_in(self.page_code)
        self.assertIn("clearBookmarks();", functions["showSignedOut"])
        self.assertIn("loadBookmarks();", functions["showSignedIn"])

    def test_the_public_answers_have_no_bookmark(self):
        for function in (server.post_to_json, server.likes_to_json, server.like_to_json):
            self.assertNotIn("bookmark", ast.get_source_segment(
                self.server_code, next(node for node in ast.walk(ast.parse(self.server_code))
                                       if isinstance(node, ast.FunctionDef)
                                       and node.name == function.__name__)))
        self.assertNotIn("bookmark", server.POSTS_WITH_AUTHORS)

    # -- japanese: the words contract (docs/plans/japanese.md, section 3.4) --
    #
    # The server sends a code; the page shows the words for it, from words.js.
    # These tests are what keep the two tables, PROBLEMS and WORDS, the same,
    # and every word of the page in words.js.

    def words(self):
        return read_words()[2]

    def keys_used_in_the_page_code(self):
        """Every key app.js names, as {key: [the value names given with it, or None]}."""
        code = re.sub(r"^\s*//.*$", "", self.page_code, flags=re.MULTILINE)
        used = {}

        def use(key, names=None):
            used.setdefault(key, []).append(names)

        # The values: a {…} written in the call is checked against the words; no
        # values at all means the words must have no {names}; values in a
        # variable cannot be read here, so they are not checked (None).
        def given(rest, always=frozenset()):
            if rest.startswith("{"):
                return set(re.findall(r"(\w+):", rest)) | always
            if rest.startswith(","):
                return None
            return set(always)

        for key, rest in re.findall(
                r'\b(?:say|showStatus|showSignedOut)\(\s*"(\w*)"\s*(?:,\s*)?(\{[^}]*\}|[^)\s]?)', code):
            if key:
                use(key, given(rest if rest in ("", ")") or rest.startswith("{") else ","))
        for key, inside in re.findall(r'\bkey: "(\w+)", values: \{([^}]*)\}', code):
            use(key, set(re.findall(r"(\w+):", inside)))
        # sayCount("key", n) or sayCount("key", n, { first: ... }): two keys,
        # key_one and key_other. {count} is always given; other values may be.
        for key, rest in re.findall(
                r'\bsayCount\(\s*"(\w+)"\s*,[^,)]*(,\s*\{[^}]*\}|,|)', code):
            rest = rest.lstrip(", \n") if rest != "," else ","
            names = given(rest, {"count"})
            use(key + "_one", ("count", names) if names is not None else None)
            use(key + "_other", ("count", names) if names is not None else None)
        for key in re.findall(r'\baddView\(\s*"\w+",\s*"(\w+)"', code):
            use(key)
        for key in re.findall(r'\baddMenuItem\(\s*\w+,\s*"\w+",\s*"(\w+)"', code):
            use(key)
        for assigned in re.findall(r"\.dataset\.words\w*\s*=\s*([^;]+);", code):
            for key in re.findall(r'"(\w+)"', assigned):
                use(key)
        return used

    def test_words_js_is_read_whole(self):
        # An entry written in another shape would be skipped without a word.
        # So: as many entries found as `en:` lines, and as many as keys.
        text, found, words = read_words()
        self.assertEqual(len(found), len(re.findall(r"^\s*en:", text, re.MULTILINE)))
        self.assertEqual(len(found), len(re.findall(r"^\s*\w+: \{", text, re.MULTILINE)))
        self.assertEqual(len(found), len(words), "a key is written twice")
        self.assertIn("const WORDS = {", text)

    def test_every_code_in_problems_is_in_words_js_with_the_same_english(self):
        words = self.words()
        for code, sentence in server.PROBLEMS.items():
            with self.subTest(code=code):
                self.assertIn(code, words, "add it to words.js, at the end, under your slug")
                self.assertEqual(words[code]["en"], sentence)

    def test_every_problem_is_raised_with_a_known_code_and_its_values(self):
        # server.py is read as Python. Every Problem(...), and every kind of
        # Problem (RuleBroken, NotSignedIn, TooFast, and any new one), must name
        # a code in PROBLEMS, as plain text (never a sentence), and give exactly
        # the values its sentence has. A code may also be read from a table of
        # codes, such as TOO_FAST[action]: then every code in it is checked.
        kinds = {name for name, value in vars(server).items()
                 if isinstance(value, type) and issubclass(value, server.Problem)}
        self.assertLessEqual({"Problem", "RuleBroken", "NotSignedIn", "TooFast"}, kinds)
        calls = 0
        for node in ast.walk(ast.parse(self.server_code)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in kinds):
                continue
            calls += 1
            with self.subTest(line=node.lineno):
                self.assertEqual(len(node.args), 1, "one code, then values by name")
                first = node.args[0]
                if isinstance(first, ast.Name) and first.id == "WRONG_LOGIN":
                    codes = [server.WRONG_LOGIN]
                elif (isinstance(first, ast.Subscript) and isinstance(first.value, ast.Name)
                      and isinstance(getattr(server, first.value.id, None), dict)):
                    codes = list(getattr(server, first.value.id).values())
                else:
                    self.assertIsInstance(first, ast.Constant, 'write the code as "a_code"')
                    codes = [first.value]
                given = {keyword.arg for keyword in node.keywords}
                for code in codes:
                    if code in server.PROBLEMS:
                        self.assertEqual(given, value_names(server.PROBLEMS[code]))
                    else:
                        # Words with a number: code_one and code_other, chosen by count.
                        self.assertIn(code + "_one", server.PROBLEMS)
                        self.assertIn(code + "_other", server.PROBLEMS)
                        self.assertIn("count", given)
                        self.assertEqual(given, value_names(server.PROBLEMS[code + "_one"])
                                         | value_names(server.PROBLEMS[code + "_other"])
                                         | {"count"})
        self.assertGreater(calls, 20)
        self.assertIsNone(re.search(r'\b(' + "|".join(kinds) + r')\(\s*f?"[A-Z]',
                                    self.server_code))

    def test_every_refusal_goes_through_send_problem(self):
        self.assertIsNone(re.search(r"send_json\(\s*4\d\d", self.server_code))
        # The word "error" is written only in the view's problem_to_json, so
        # no answer can have an "error" without a "code".
        uses = []
        for function in ast.walk(ast.parse(self.server_code)):
            if isinstance(function, ast.FunctionDef):
                for node in ast.walk(function):
                    if isinstance(node, ast.Constant) and node.value == "error":
                        uses.append(function.name)
        self.assertEqual(uses, ["problem_to_json"])

    def test_every_key_the_page_code_uses_is_in_words_js(self):
        words = self.words()
        used = self.keys_used_in_the_page_code()
        self.assertIn("cannot_reach", used)
        for key, given in used.items():
            with self.subTest(key=key):
                self.assertIn(key, words)
                for names in given:
                    if isinstance(names, tuple):
                        # sayCount: every {name} in the words must be given
                        # ("1 new post" need not say {count}).
                        self.assertLessEqual(value_names(words[key]["en"]), names[1])
                    elif names is not None:
                        # Values written with the key must be the {names} in its words.
                        self.assertEqual(names, value_names(words[key]["en"]))

    def test_the_page_checks_a_rule_with_the_same_code_as_the_model(self):
        functions = functions_in(self.page_code)
        for name in ("accountProblem", "textProblem", "queryProblem"):
            with self.subTest(function=name):
                keys = re.findall(r'key: "(\w+)"', functions[name])
                self.assertTrue(keys)
                for key in keys:
                    self.assertIn(key, server.PROBLEMS)

    def test_the_status_line_is_never_given_a_sentence(self):
        code = re.sub(r"^\s*//.*$", "", self.page_code, flags=re.MULTILINE)
        for function, words in re.findall(
                r'\b(say|sayCount|showStatus|showSignedOut)\(\s*"([^"]*)"', code):
            with self.subTest(call=function + '("' + words + '")'):
                self.assertRegex(words, r"^[a-z0-9_]*$", "use a key from words.js")
        # The server's English is used only when the page has no words for the code.
        self.assertEqual(re.findall(r"answer\.error", code), ["answer.error"])
        self.assertIn("answer.error", functions_in(self.page_code)["showProblem"])

    def test_the_page_code_writes_no_words_of_its_own(self):
        # A line that puts text on the screen may hold a key, but never words.
        code = re.sub(r"^\s*//.*$", "", self.page_code, flags=re.MULTILINE)
        shows = re.compile(r"\.(textContent|placeholder|title|alt|innerText)\s*=|"
                           r"setAttribute\(\s*\"(aria-label|title|placeholder|alt)\"")
        for line in code.splitlines():
            if not shows.search(line):
                continue
            with self.subTest(line=line.strip()):
                rest = re.sub(r'(set|get)Attribute\(\s*"[\w-]+"', "", line)
                rest = re.sub(r'\b(say|sayCount)\(\s*"\w+"', "", rest)
                for literal in re.findall(r'"((?:[^"\\]|\\.)*)"', rest):
                    literal = json.loads('"' + literal + '"')   # "\u2665" is a heart, not words
                    self.assertIsNone(re.search(r"[^\W\d_]", literal),
                                      "put the words in words.js and use say()")
        # One sentence is one key: never joined from pieces.
        self.assertIsNone(re.search(r"\bsay\([^)]*\)\s*\+|\+\s*say\(", code))

    def test_every_word_in_index_html_names_its_key(self):
        words = self.words()
        page_values = {"min": server.MIN_PASSWORD, "size": server.MAX_PICTURE_MB}
        not_words = {"aiko"}   # an example account name, the same in every language

        class Words(html.parser.HTMLParser):
            EMPTY = {"meta", "link", "input", "br", "img", "hr"}

            def __init__(self):
                super().__init__()
                self.open = []      # the elements we are inside, innermost last
                self.problems = []
                self.keys = []

            def check(self, where, words_now, key):
                if key is None:
                    self.problems.append(where + ": no data-words for " + repr(words_now))
                elif key not in words:
                    self.problems.append(where + ": " + key + " is not in words.js")
                elif words[key]["en"].format(**page_values) != words_now:
                    self.problems.append(where + ": " + repr(words_now) + " is not the "
                                         "English of " + key)

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                for name in ("placeholder", "aria-label", "title", "alt"):
                    value = attrs.get(name)
                    if value and re.search(r"[^\W\d_]", value) and value not in not_words:
                        self.check(tag + " " + name, value, attrs.get("data-words-" + name))
                self.keys += [v for k, v in attrs.items() if k.startswith("data-words")]
                if tag not in self.EMPTY:
                    self.open.append((tag, attrs))

            def handle_endtag(self, tag):
                while self.open and self.open.pop()[0] != tag:
                    pass

            def handle_data(self, data):
                text = " ".join(data.split())
                if not re.search(r"[^\W\d_]", text) or not self.open:
                    return
                tag, attrs = self.open[-1]
                if tag not in ("script", "style"):
                    self.check(tag, text, attrs.get("data-words"))

        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            page = Words()
            page.feed(page_file.read())
        self.assertEqual(page.problems, [])
        self.assertIn("app_name", page.keys)
        for key in page.keys:
            self.assertIn(key, words)

    def test_the_words_load_before_the_page_code(self):
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            page = page_file.read()
        self.assertLess(page.index('<script src="words.js"></script>'),
                        page.index('<script src="app.js"></script>'))

    def test_the_language_button_is_there_but_hidden_until_part_b(self):
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            button = re.search(r'<button[^>]*id="language"[^>]*>', page_file.read()).group(0)
        self.assertIn(" hidden", button)
        self.assertIn('lang="ja"', button)

    def test_the_server_never_translates(self):
        # No Japanese in any text the server could send. A pattern given to
        # re.compile may name Japanese letters (a #tag may be #東京): that is a
        # rule for matching, not words. Comments and docstrings are not sent.
        japanese = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
        tree = ast.parse(self.server_code)
        allowed = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "compile" and node.args):
                allowed.add(id(node.args[0]))
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    allowed.add(id(first.value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in allowed):
                with self.subTest(line=node.lineno):
                    self.assertIsNone(japanese.search(node.value))
        for sentence in server.PROBLEMS.values():
            self.assertIsNone(japanese.search(sentence))
        self.assertNotIn("Accept-Language", self.server_code)

    def test_nobody_writes_japanese_before_part_b(self):
        # japanese Part B writes all the Japanese at once, in one voice. Until
        # then, every entry has en: only. (Part B replaces this test with "every
        # entry has ja:, with the same {names} as its en:".)
        for key, entry in self.words().items():
            with self.subTest(key=key):
                self.assertEqual(set(entry), {"en"})

    # -- pictures --

    def test_the_page_has_the_model_s_picture_rules(self):
        self.assertIn(f"const MAX_PICTURE_BYTES = {server.MAX_PICTURE_BYTES};", self.page_code)
        self.assertIn(f"const MAX_PICTURE_MB = {server.MAX_PICTURE_MB};", self.page_code)
        self.assertIn(f"const MAX_ALT_TEXT = {server.MAX_ALT_TEXT};", self.page_code)
        types = ", ".join('"' + kind + '"' for kind in server.PICTURE_TYPES.values())
        self.assertIn(f"const PICTURE_TYPES = [{types}];", self.page_code)
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            page = page_file.read()
        self.assertIn('accept="' + ",".join(server.PICTURE_TYPES.values()) + '"', page)
        # The page checks with the model's own codes, and the label's {size} is the limit.
        keys = re.findall(r'key: "(\w+)"', functions_in(self.page_code)["pictureProblem"])
        self.assertEqual(len(keys), 6)
        for key in keys:
            self.assertIn(key, server.PROBLEMS)
        self.assertIn("size: MAX_PICTURE_MB", self.page_code)

    def test_the_page_sends_the_picture_with_the_post(self):
        send = functions_in(self.page_code)["sendPost"]   # an async function
        # (replies adds parent_id after these.)
        self.assertIn("JSON.stringify({ text: text, place: place, picture: picture, "
                      "picture_alt: pictureAlt,",
                      send)
        self.assertIn("pictureProblem(", send)
        self.assertIn("clearPictureBoxes()", send)
        self.assertIn('data.get("picture")', self.server_code)
        self.assertIn('data.get("picture_alt")', self.server_code)

    def test_a_jpeg_is_drawn_again_and_a_gif_is_not(self):
        functions = functions_in(self.page_code)
        self.assertIn('if (file.type !== "image/jpeg") {', functions["preparePicture"])
        redraw = functions["redrawJpeg"]
        self.assertIn('imageOrientation: "from-image"', redraw)
        self.assertIn('canvas.toBlob(done, "image/jpeg"', redraw)
        self.assertIn("blob.size <= MAX_PICTURE_BYTES", redraw)

    def test_the_page_shows_the_picture_the_server_names(self):
        self.assertIn("slots.body.append(pictureElement(post.picture));", self.page_code)
        made = self.function_body("pictureElement")
        self.assertIn("image.src = picture.url;", made)
        self.assertIn("image.alt = picture.alt;", made)
        # The page never builds a picture's address itself.
        self.assertNotIn('"/pictures', self.page_code)
        self.assertNotIn("picture", self.function_body("makePostItem"))
        self.assertNotIn("picture", self.function_body("showPost"))
        # Search results are built by makePostItem too, so they get the picture part.
        self.assertIn("makePostItem(post)", functions_in(self.page_code)["showResults"])
        self.assertIn("makePostItem(post)", functions_in(self.page_code)["showBookmarkList"])

    def test_the_server_answers_a_picture_address(self):
        self.assertEqual(self.answer_code("GET", "/pictures/1"), 404)   # known route, no post yet

    def test_the_request_limit_fits_the_biggest_picture_exactly(self):
        as_text = (server.MAX_PICTURE_BYTES + 2) // 3 * 4
        self.assertGreaterEqual(server.MAX_REQUEST_BYTES, as_text + 64 * 1024)

    # -- block --

    def test_the_server_answers_the_block_requests(self):
        for method in ("GET", "POST", "DELETE"):
            with self.subTest(method=method):
                self.assertNotIn(self.answer_code(method, "/blocks"), (404, 501))
        functions = functions_in(self.page_code)
        self.assertIn('fetch("/blocks")', functions["loadBlocked"])
        self.assertIn('method: "POST"', functions["pressBlock"])
        self.assertIn('method: "DELETE"', functions["unblock"])
        for name in ("pressBlock", "unblock"):
            with self.subTest(function=name):
                self.assertIn("account_name: name", functions[name])
                self.assertIn("!response.ok", functions[name])
        self.assertIn('data.get("account_name")', self.function_in_server("take_block"))
        self.assertIn('data.get("account_name")', self.function_in_server("end_block"))

    def function_in_server(self, name):
        for function in ast.walk(ast.parse(self.server_code)):
            if isinstance(function, ast.FunctionDef) and function.name == name:
                return ast.get_source_segment(self.server_code, function)
        raise AssertionError(name + " is not in server.py")

    def test_the_page_never_offers_to_block_yourself(self):
        block_part = re.search(r"addPostPart\(function blockPart\(.*?\n\}\);",
                               self.page_code, re.DOTALL).group(0)
        self.assertIn("account === null", block_part)
        self.assertIn("sameAccount(post.author, account.account_name)", block_part)
        self.assertIn('addMenuItem(slots, "block"', block_part)
        self.assertIn("ACTIONS.block = pressBlock;", self.page_code)

    def test_blocking_removes_posts_and_unblocking_draws_the_timeline_again(self):
        functions = functions_in(self.page_code)
        self.assertIn("hidePostsBy(", functions["pressBlock"])
        self.assertIn("removePost(", functions["hidePostsBy"])
        self.assertIn("reloadTimeline()", functions["unblock"])
        self.assertIn("reloadTimeline()", functions["afterAccountChange"])
        self.assertIn("confirm(", functions["pressBlock"])

    def test_the_page_reads_the_names_the_block_answers_have(self):
        answer = server.blocks_to_json([{"name": "ben", "display_name": "Ben Ito"}])
        self.assertEqual(answer, {"blocked": [{"account_name": "ben",
                                               "display_name": "Ben Ito"}]})
        for key in ("answer.blocked", "person.account_name", "person.display_name",
                    "answer.account_name"):
            with self.subTest(key=key):
                self.assertIn(key, self.page_code)
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            html = page_file.read()
        self.assertIn('id="blocked-section"', html)
        self.assertIn('id="blocked-list"', html)

    # -- replies --

    def test_the_page_sends_parent_id_and_reads_the_reply_names(self):
        send = functions_in(self.page_code)["sendPost"]
        self.assertIn("parent_id: replyingTo === null ? null : replyingTo.id", send)
        row = {"id": 2, "author": "ken", "display_name": "Ken", "text": "x", "posted_at": None,
               "old_clock_time": "09:00", "like_count": 0, "place": None, "picture_alt": None,
               "parent_id": 1, "parent_author": "aiko", "reply_count": 0,
               "newest_reply_id": None, "edited": 0, "deleted": 0,
               "hidden_by_reports": 0}
        sent = server.post_to_json(row)
        for name in ("parent_id", "parent_author", "reply_count", "newest_reply_id"):
            with self.subTest(name=name):
                self.assertIn(name, sent)
                self.assertIn("post." + name, self.page_code)

    def test_a_reply_goes_under_its_post_through_the_shared_pieces(self):
        functions = functions_in(self.page_code)
        self.assertIn('"under-parent"', functions["placePost"])
        self.assertIn("placeUnderParent(item, post)", functions["placePost"])
        self.assertIn("addPostPart(function replyPart(", self.page_code)
        self.assertIn("ACTIONS.reply = startReply;", self.page_code)
        # The page never counts the replies it shows: it starts from the server's count.
        self.assertIn("post.reply_count", self.page_code)
        self.assertNotIn("list.children.length + ", self.page_code)
        # A post taken off the page takes its replies with it, and replies that
        # came before their post (an older page) move under it.
        self.assertIn("removeReplyThread(postId, parts)", functions["removePost"])
        self.assertIn("adoptReplies(post)", functions["placePost"])

    def test_a_reply_is_not_a_new_post_and_goes_under_its_post_at_once(self):
        functions = functions_in(self.page_code)
        receive = functions["receiveNewPosts"]
        self.assertLess(receive.index('putPost(post, "under-parent")'),
                        receive.index("waitingPosts.push(post)"))
        self.assertIn("waitingPosts.filter(countsAsNewPost).length",
                      functions["updateNewPostsButton"])
        self.assertIn("!hasParentOnTimeline(post)", functions["countsAsNewPost"])

    def test_the_reply_words_change_with_the_language(self):
        self.assertIn("whenLanguageChanges(function redrawReplyWords()", self.page_code)
        self.assertIn('sayCount("reply_count", count)', self.page_code)
        for code in ("reply_parent_id_missing", "reply_to_reply", "reply_blocked"):
            self.assertIn(code, server.PROBLEMS)
        self.assertEqual(server.BLOCKED_CODES["reply"], "reply_blocked")

    def test_the_replying_to_line_is_in_the_post_form(self):
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            html = page_file.read()
        form = html[html.index('<form id="post-form">'):]
        form = form[:form.index("</form>")]
        for part in ('id="replying-to" hidden', 'id="replying-to-words"', 'id="cancel-reply"'):
            self.assertIn(part, form)
        self.assertIn('cancelReplyButton.addEventListener("click", cancelReply)', self.page_code)

    # -- edit-delete --

    def test_the_page_asks_for_changes_before_posts(self):
        code = functions_in(self.page_code)
        check = code["checkForNewPosts"]
        self.assertLess(check.index("await checkForChanges();"), check.index("loadOlderPosts"))
        self.assertLess(check.index("await checkForChanges();"), check.index('fetch("/posts'))
        self.assertIn('fetch("/changes"', code["checkForChanges"])
        self.assertIn("lastChangeId = answer.latest;", code["checkForChanges"])

    def test_the_page_sends_exactly_post_id_and_text_for_an_edit_and_post_id_for_a_delete(self):
        code = functions_in(self.page_code)
        self.assertIn("JSON.stringify({ post_id: postId, text: text })", code["sendEdit"])
        self.assertIn('method: "PATCH"', code["sendEdit"])
        self.assertIn("textProblem(text.trim())", code["sendEdit"])
        self.assertIn("JSON.stringify({ post_id: postId })", code["deletePost"])
        self.assertIn('method: "DELETE"', code["deletePost"])
        self.assertIn('confirm(say("delete_confirm"))', code["deletePost"])

    def test_the_page_reads_the_names_the_changes_answers_have(self):
        row = {"id": 1, "author": "a", "display_name": "A", "text": "t", "posted_at": None,
               "old_clock_time": "09:00", "like_count": 0, "place": None, "picture_alt": None,
               "parent_id": None, "parent_author": None, "reply_count": 0,
               "newest_reply_id": None, "edited": 1, "deleted": 0,
               "hidden_by_reports": 0}
        changes = server.changes_to_json(3, [({"id": 3, "post_id": 1, "kind": "edited"}, row)])
        keys = set(changes) | set(changes["changes"][0]) | set(changes["changes"][0]["post"]) \
            | set(server.version_to_json({"text": "t", "replaced_at": "x"})) \
            | set(server.deleted_to_json(1, None))
        for key in ("latest", "changes", "post", "post_id", "edited", "deleted", "replaced_at"):
            with self.subTest(key=key):
                self.assertIn("." + key, self.page_code)
                self.assertIn(key, keys)

    def test_edit_and_delete_use_the_shared_pieces(self):
        code = functions_in(self.page_code)
        for action, function in (("edit", "startEdit"), ("saveEdit", "sendEdit"),
                                 ("cancelEdit", "cancelEdit"), ("delete", "deletePost"),
                                 ("versions", "toggleVersions")):
            with self.subTest(action=action):
                self.assertIn(f"ACTIONS.{action} = {function};", self.page_code)
                self.assertNotIn(action, code["clickOnTimeline"])
        self.assertIn("removePost(postId)", code["showChangedPost"])
        self.assertIn("redrawPost(post)", code["showChangedPost"])
        self.assertNotIn("edit", code["makePostItem"])
        # The menu items only on your own posts, never on a deleted one.
        owner = self.page_code.split("function ownerToolsPart")[1].split("\n});\n")[0]
        self.assertIn("post.deleted", owner)
        self.assertIn("sameAccount(post.author, account.account_name)", owner)
        # A removed or redrawn post stops being watched by the long-posts ResizeObserver.
        self.assertIn("textSizeWatcher.unobserve(", code["stopWatchingText"])
        self.assertIn("stopWatchingText(parts.item);", code["removePost"])
        self.assertIn("stopWatchingText(old.item);", code["redrawPost"])

    def test_a_change_reaches_every_copy_of_a_post(self):
        code = functions_in(self.page_code)
        apply = code["applyChange"]
        # timeline-flow: a post waiting behind "new posts" is changed or removed there.
        self.assertIn("waitingPosts.splice(waiting, 1);", apply)
        self.assertIn("waitingPosts[waiting] = post;", apply)
        self.assertIn("updateNewPostsButton();", apply)
        # Every copy on the page: the timeline, the search results, My bookmarks.
        self.assertIn("li.post[data-post-id=", apply)
        self.assertIn("bookmarked.delete(postId);", apply)

    def test_a_deleted_post_has_no_heart_no_reply_and_no_star(self):
        edited = self.page_code.split("function editedPart")[1].split("\n});\n")[0]
        self.assertIn('say("deleted_post")', edited)
        for selector in (".like", ".reply-button", ".bookmark"):
            self.assertIn(selector, edited)
        # The part runs after the parts that make those buttons.
        for part in ("heartPart", "replyPart", "bookmarkPart", "blockPart"):
            self.assertLess(self.page_code.index("function " + part),
                            self.page_code.index("function editedPart"))

    # -- report --

    def test_the_page_has_the_same_reason_limit_as_the_model(self):
        self.assertIn(f"const MAX_REASON = {server.MAX_REASON};", self.page_code)
        # The database's CHECK says the same number.
        self.assertIn(f"length(reason) <= {server.MAX_REASON}", self.server_code)

    def test_report_is_a_menu_item_and_an_action(self):
        functions = functions_in(self.page_code)
        self.assertIn('addMenuItem(slots, "report", "report_menu")', self.page_code)
        self.assertIn("ACTIONS.report = pressReport;", self.page_code)
        self.assertIn('prompt(say("report_ask_reason"))', functions["pressReport"])
        self.assertIn("showProblem(answer)", functions["pressReport"])
        # Only on another person's post, when logged in (the page's report_own_post).
        part = self.page_code.split("function reportPart")[1].split("\n});\n")[0]
        self.assertIn("sameAccount(post.author, account.account_name)", part)
        self.assertIn("account !== null", part)

    def test_the_page_does_not_ask_for_reports_every_second(self):
        # Open windows hear about a hidden post from the changes feed instead.
        functions = functions_in(self.page_code)
        for name in ("checkForNewPosts", "checkForChanges", "keepChecking"):
            self.assertNotIn("/reports", functions[name])
            self.assertNotIn("askForReports", functions[name])
        self.assertIn("askForReports", functions["afterAccountChange"])
        self.assertIn("askForReports", functions["pressReport"])
        # A post hidden from this person goes the way a change with no post does.
        self.assertIn("applyChange({ post_id: postId, post: null })", functions["showReports"])

    def test_the_page_reads_the_names_the_reports_answers_have(self):
        names = set(server.reports_to_json([], [], [])) | {"hidden_by_reports"}
        self.assertEqual(names, {"hidden", "mine_hidden", "reported", "hidden_by_reports"})
        for name in ("answer.hidden", "answer.mine_hidden", "answer.reported",
                     "post.hidden_by_reports"):
            self.assertIn(name, self.page_code)

    def test_the_hidden_and_shown_kinds_are_known(self):
        self.assertIn("hidden", server.CHANGE_KINDS)
        self.assertIn("shown", server.CHANGE_KINDS)


    # -- links-and-tags --

    def page_pattern(self, name):
        r"""The text of `const NAME = /.../;` in app.js, with \/ turned into /."""
        found = re.search(r"^const " + name + r" = /(.*)/;$", self.page_code, re.MULTILINE)
        self.assertIsNotNone(found, name + " is not in app.js")
        return found.group(1).replace("\\/", "/")

    def test_the_page_has_the_same_link_and_name_patterns(self):
        for name in ("LINK", "LINK_START", "NAME", "TAG"):
            with self.subTest(pattern=name):
                self.assertEqual(self.page_pattern(name), getattr(server, name).pattern)
        self.assertIn(f'const LINK_END = "{server.LINK_END}";', self.page_code)

    def test_a_name_follows_the_account_name_rule(self):
        self.assertEqual(server.ACCOUNT_NAME.pattern, "[A-Za-z0-9_]+")
        self.assertIn("@[A-Za-z0-9_]{1," + str(server.MAX_AUTHOR) + "}", server.NAME.pattern)

    def test_the_page_never_reads_text_as_html(self):
        for unsafe in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn(unsafe, self.page_code)

    def test_a_link_is_only_http_or_https_and_opens_safely(self):
        link = functions_in(self.page_code)["linkElement"]
        self.assertIn('url.protocol !== "http:" && url.protocol !== "https:"', link)
        self.assertIn('link.rel = "noopener noreferrer";', link)
        self.assertIn('link.target = "_blank";', link)
        self.assertIn("link.textContent = address;", link)
        # No other protocol is named where a post's text is drawn. (Elsewhere,
        # pictures may use data: for its own preview, which is not a post's text.)
        functions = functions_in(self.page_code)
        drawing = "".join(functions[name] for name in (
            "showPostText", "postTextPieces", "trimLinkEnd", "pieceElement", "linkElement",
            "searchElement"))
        for protocol in ("javascript:", "data:", "file:", "vbscript:"):
            self.assertNotIn(protocol, drawing)

    def test_the_text_part_uses_show_post_text(self):
        part = re.search(r"^addPostPart\(function textPart\(.*?^\}\);", self.page_code,
                         re.MULTILINE | re.DOTALL).group(0)
        self.assertIn("showPostText(text, post.text);", part)
        self.assertIn('text.className = "post-text";', part)
        self.assertNotIn("text.textContent = post.text", self.page_code)
        functions = functions_in(self.page_code)
        self.assertIn("pieceElement(piece)", functions["showPostText"])
        self.assertIn("document.createTextNode(piece.text)", functions["pieceElement"])
        # An earlier version of an edited post (edit-delete) is drawn the same way.
        self.assertIn("showPostText(words, version.text);", functions["buildVersions"])

    def test_a_tag_or_name_opens_a_search_by_the_contract(self):
        search = functions_in(self.page_code)["searchElement"]
        self.assertIn("link.href = searchAddress(words);", search)
        self.assertIn("event.preventDefault();", search)
        self.assertIn("searchFor(words);", search)
        self.assertIn("link.textContent = words;", search)

    def test_the_page_twin_is_built_the_same_way(self):
        functions = functions_in(self.page_code)
        pieces = functions["postTextPieces"]
        self.assertIn('"(?:" + LINK.source + ")|(?:" + TAG.source + ")|(?:" + NAME.source + ")", "g"',
                      pieces)
        self.assertIn("trimLinkEnd(words)", pieces)
        self.assertIn("LINK_START.test(words)", pieces)
        self.assertEqual(server.PIECE.pattern, "(?:" + server.LINK.pattern + ")|(?:"
                         + server.TAG.pattern + ")|(?:" + server.NAME.pattern + ")")
        trim = functions["trimLinkEnd"]
        self.assertIn("LINK_END.includes(last)", trim)
        self.assertIn('countOf(link, ")") > countOf(link, "(")', trim)
        self.assertIn('countOf(link, "]") > countOf(link, "[")', trim)

class ColoursTest(unittest.TestCase):
    """The Colours switch (Auto, Light, Dark) and the colours themselves.

    The switch lives only in the browser: it never talks to the server. So these
    tests read style.css, index.html and app.js as text, and check the things
    that would break quietly, without anyone seeing an error.
    """

    def read(self, *path):
        with open(os.path.join(HERE, *path), encoding="utf-8") as file:
            return file.read()

    def setUp(self):
        self.css = self.read("style.css")
        self.html = self.read("index.html")
        self.page_code = self.read("app.js")
        # The first :root { ... } block: the colours, in one place.
        self.root_block = re.search(r":root \{(.*?)\}", self.css, re.DOTALL).group(1)
        # Every colour, as {name: (light, dark)}.
        self.colours = {
            name: (light, dark) for name, light, dark in re.findall(
                r"--([\w-]+): light-dark\((#[0-9a-f]{6}), (#[0-9a-f]{6})\);", self.root_block)
        }

    # The WCAG contrast ratio: how different two colours look, from 1 (the
    # same) to 21 (black on white). 4.5 is the rule for normal text, and 3 for
    # the edge of a box or a button.
    def brightness(self, colour):
        def channel(part):
            value = int(colour[part:part + 2], 16) / 255
            if value <= 0.03928:
                return value / 12.92
            return ((value + 0.055) / 1.055) ** 2.4
        return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)

    def contrast(self, one, other):
        lighter, darker = sorted([self.brightness(one), self.brightness(other)], reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    def check_contrast(self, pairs, at_least):
        for mode, which in (("light", 0), ("dark", 1)):
            for front, back in pairs:
                with self.subTest(mode=mode, front=front, back=back):
                    ratio = self.contrast(self.colours[front][which], self.colours[back][which])
                    self.assertGreaterEqual(ratio, at_least)

    def test_every_colour_has_a_light_and_a_dark_value(self):
        names = re.findall(r"--([\w-]+):", self.root_block)
        self.assertGreater(len(names), 0)
        # A colour written any other way (one value only, or a typo) is not in
        # self.colours, so this fails and names it.
        self.assertEqual(sorted(names), sorted(self.colours))

    def test_every_colour_used_is_defined(self):
        for name in set(re.findall(r"var\(--([\w-]+)\)", self.css)):
            with self.subTest(colour=name):
                self.assertIn(name, self.colours)

    def test_text_is_easy_to_read_in_both_modes(self):
        pairs = [(front, back) for front in ("text", "quiet", "author", "warning")
                 for back in ("background", "card")]
        pairs.append(("button-text", "button"))
        self.check_contrast(pairs, 4.5)

    def test_the_edges_of_boxes_can_be_seen_in_both_modes(self):
        self.check_contrast([("border", "background"), ("border", "card")], 3)

    def test_there_are_exactly_three_choices(self):
        self.assertEqual(re.findall(r'<option value="(\w+)"', self.html),
                         ["auto", "light", "dark"])
        self.assertIn(':root[data-theme="light"]', self.css)
        self.assertIn(':root[data-theme="dark"]', self.css)

    def test_the_choice_is_used_before_the_page_is_drawn(self):
        head = self.html[:self.html.index("</head>")]
        script = head.index("<script>")
        self.assertLess(script, head.index('<link rel="stylesheet"'))
        script_code = head[script:head.index("</script>")]
        self.assertIn("localStorage.getItem", script_code)
        self.assertIn("try {", script_code)
        self.assertIn("catch (error)", script_code)

    def test_the_head_script_and_app_js_agree(self):
        self.assertIn('localStorage.getItem("timeline-theme")', self.html)
        self.assertIn('const THEME_KEY = "timeline-theme";', self.page_code)
        for code in (self.html, self.page_code):
            self.assertIn('theme === "light" || theme === "dark"', code)

    def test_the_switch_has_a_label(self):
        self.assertIn('<label for="theme">', self.html)
        self.assertIn('<select id="theme">', self.html)

    def test_page_only_follows_the_computer(self):
        page_only = self.read("..", "page-only", "index.html")
        self.assertNotIn("data-theme", page_only)
        self.assertNotIn("localStorage", page_only)
        self.assertIn("color-scheme: light dark;", self.root_block)
def functions_in(code):
    """Cut app.js into its top-level functions. Gives a map: name -> body.

    A top-level function starts at the left edge with `function name(` or
    `async function name(`, and ends at the first `}` at the left edge.
    """
    found = {}
    pattern = r"^(?:async )?function (\w+)\(.*?^\}"
    for match in re.finditer(pattern, code, re.MULTILINE | re.DOTALL):
        found[match.group(1)] = match.group(0)
    return found


class PageDraftTest(unittest.TestCase):
    """Drafts live only in the page, so these tests read app.js as text.

    They cannot prove a draft comes back after a reload (that would need a
    browser). They check that the code is wired the way the plan agreed.
    """

    def setUp(self):
        with open(os.path.join(HERE, "app.js"), encoding="utf-8") as file:
            self.page_code = file.read()
        self.functions = functions_in(self.page_code)

    def test_a_draft_is_kept_per_account(self):
        self.assertIn('"timeline-draft:"', self.page_code)
        self.assertIn("account_name", self.functions["draftKey"])

    def test_every_use_of_local_storage_is_inside_a_try(self):
        users = [name for name, body in self.functions.items() if "localStorage" in body]
        self.assertTrue(users, "no function uses localStorage")
        for name in users:
            with self.subTest(function=name):
                body = self.functions[name]
                self.assertIn("try {", body)
                self.assertIn("catch", body)
        # No localStorage outside a function (comments do not count).
        outside = self.page_code
        for body in self.functions.values():
            outside = outside.replace(body, "")
        outside = re.sub(r"//.*", "", outside)
        self.assertNotIn("localStorage", outside)

    def test_the_page_uses_no_session_storage(self):
        self.assertNotIn("sessionStorage", self.page_code)

    def test_the_draft_is_forgotten_only_after_a_saved_post_and_on_log_out(self):
        # A call, not the line that defines forgetDraft itself.
        callers = {name for name, body in self.functions.items()
                   if re.search(r"(?<!function )forgetDraft\(\)", body)}
        self.assertEqual(callers, {"sendPost", "logOut"})
        send = self.functions["sendPost"]
        self.assertGreater(send.index("forgetDraft()"), send.index("if (!response.ok)"))
        log_out = self.functions["logOut"]
        # Before showSignedOut, which forgets who is logged in.
        self.assertLess(log_out.index("forgetDraft()"), log_out.index("showSignedOut("))

    def test_the_box_follows_who_is_logged_in(self):
        self.assertIn("showDraft(", self.functions["showSignedIn"])
        self.assertIn("hideDraft()", self.functions["showSignedOut"])

    def test_saving_listens_to_the_box(self):
        self.assertIn('textBox.addEventListener("input", saveDraft)', self.page_code)

    def test_a_draft_is_never_sent(self):
        for inside in re.findall(r"JSON\.stringify\((.*?)\)", self.page_code):
            with self.subTest(sent=inside):
                self.assertNotIn("draft", inside.lower())

    def test_a_draft_remembers_the_post_it_replies_to(self):
        save = self.functions["saveDraft"]
        self.assertIn("reply_to: replyingTo", save)
        self.assertIn('textBox.value.trim() === "" && replyingTo === null', save)
        self.assertIn("readDraft(", self.functions["loadDraft"])
        self.assertIn("showReplyingTo(draft.replyTo)", self.functions["showDraft"])
        self.assertIn("stopReplying()", self.functions["hideDraft"])

    def test_an_old_plain_text_draft_still_loads(self):
        read = self.functions["readDraft"]
        self.assertIn("found.v === 2", read)
        self.assertIn("return { text: kept, replyTo: null };", read)
        self.assertIn("catch", read)


class PostTextTests(unittest.TestCase):
    """links-and-tags: how a post's text is cut into words, links, tags and names.

    The page does the cutting (postTextPieces in app.js), and its JavaScript
    never runs here. So the behaviour is written down once, as EXAMPLES, and
    checked on the model's twin, post_text_pieces. PageAndServerAgreeTest
    checks the page's twin is built from the very same patterns.
    """

    A40 = "@" + "a" * 40
    A41 = "@" + "a" * 41

    # (text, the pieces it is cut into, as (kind, text))
    EXAMPLES = [
        ("hello", [("text", "hello")]),
        ("see https://x.com.", [("text", "see "), ("link", "https://x.com"), ("text", ".")]),
        ("(see https://x.com)", [("text", "(see "), ("link", "https://x.com"), ("text", ")")]),
        ("https://en.wikipedia.org/wiki/Kyoto_(city)",
         [("link", "https://en.wikipedia.org/wiki/Kyoto_(city)")]),
        ("[https://x.com/a]", [("text", "["), ("link", "https://x.com/a"), ("text", "]")]),
        ("https://x.com/?a=1&b=2!!", [("link", "https://x.com/?a=1&b=2"), ("text", "!!")]),
        ("http://x.com", [("link", "http://x.com")]),
        ("javascript:alert(1)", [("text", "javascript:alert(1)")]),
        ("data:text/html,<b>hi</b>", [("text", "data:text/html,<b>hi</b>")]),
        ("ftp://x.com", [("text", "ftp://x.com")]),
        ("HTTPS://x.com", [("text", "HTTPS://x.com")]),
        ("https://.", [("text", "https://.")]),
        ("https://x.com/を見て", [("link", "https://x.com/"), ("text", "を見て")]),
        ('"https://x.com"', [("text", '"'), ("link", "https://x.com"), ("text", '"')]),
        ("<script>alert(1)</script>", [("text", "<script>alert(1)</script>")]),
        ("#kyoto is nice", [("tag", "#kyoto"), ("text", " is nice")]),
        ("#東京は雨。", [("tag", "#東京は雨"), ("text", "。")]),
        ("#kyoto!", [("tag", "#kyoto"), ("text", "!")]),
        # TAG is search's one tag rule: digits alone make a tag, and a tag may
        # come straight after a letter.
        ("we are #1", [("text", "we are "), ("tag", "#1")]),
        ("page#top", [("text", "page"), ("tag", "#top")]),
        ("a lone # here", [("text", "a lone # here")]),
        ("https://x.com/#top", [("link", "https://x.com/#top")]),
        ("hi @aiko's cat", [("text", "hi "), ("name", "@aiko"), ("text", "'s cat")]),
        ("(@ben_2)", [("text", "("), ("name", "@ben_2"), ("text", ")")]),
        ("mail aiko@mail.com", [("text", "mail aiko@mail.com")]),
        (A40, [("name", A40)]),
        (A41, [("text", A41)]),
        ("@aiko #kyoto https://x.com",
         [("name", "@aiko"), ("text", " "), ("tag", "#kyoto"), ("text", " "),
          ("link", "https://x.com")]),
        ("", []),
    ]

    def test_every_example(self):
        for text, expected in self.EXAMPLES:
            with self.subTest(text=text):
                pieces = server.post_text_pieces(text)
                self.assertEqual([(piece["kind"], piece["text"]) for piece in pieces], expected)

    def test_the_pieces_join_to_the_whole_post(self):
        for text, expected in self.EXAMPLES:
            with self.subTest(text=text):
                pieces = server.post_text_pieces(text)
                self.assertEqual("".join(piece["text"] for piece in pieces), text)

    def test_two_text_pieces_are_never_side_by_side(self):
        for text, expected in self.EXAMPLES:
            kinds = [piece["kind"] for piece in server.post_text_pieces(text)]
            for first, second in zip(kinds, kinds[1:]):
                self.assertFalse(first == second == "text", text)

    def test_the_tags_shown_are_the_tags_search_finds(self):
        # Outside a link, a tag on the screen is exactly a tag search finds.
        for text, expected in self.EXAMPLES:
            if any(kind == "link" for kind, words in expected):
                continue
            with self.subTest(text=text):
                shown = {words[1:].lower() for kind, words in expected if kind == "tag"}
                self.assertEqual(shown, server.tags_in(text))

    def test_trim_link_end(self):
        self.assertEqual(server.trim_link_end("https://x.com.,;:!?*'"), "https://x.com")
        self.assertEqual(server.trim_link_end("https://x.com/a_(b))"), "https://x.com/a_(b)")
        self.assertEqual(server.trim_link_end("https://x.com/[1]"), "https://x.com/[1]")
        self.assertEqual(server.trim_link_end("https://x.com/1]."), "https://x.com/1")
        self.assertEqual(server.trim_link_end(""), "")


if __name__ == "__main__":
    unittest.main()
