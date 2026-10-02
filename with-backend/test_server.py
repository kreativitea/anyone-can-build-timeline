"""Tests for server.py. Run them with:  python3 -m unittest

Most tests call the MODEL directly, with a database made only for the test.
RealServerTest starts the real server and talks to it, as the page does.
JourneyTest walks one whole journey through all three levels at once: the
requests the page makes, the server that answers them, and the rows in the
database file.
PageAndServerAgreeTest reads app.js and checks the page and the server agree.
"""

import ast
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
        self.assertEqual(str(wrong_name.exception), server.WRONG_LOGIN)

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
        self.assertEqual([row[1] for row in self.rows("PRAGMA table_info(posts)")],
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
        self.assertEqual((code, reason), (401, server.WRONG_LOGIN))

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
                                   "old_clock_time", "like_count")})))

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
            data=json.dumps({}).encode("utf-8") if method in ("POST", "DELETE") else None,
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
                                 "/likers", "/likesummary", "/search"})

    def test_the_page_names_only_the_methods_tried_below(self):
        # A GET needs no method, so the page names only the other two.
        named = set(re.findall(r'"(GET|POST|PUT|PATCH|DELETE)"', self.page_code))
        self.assertEqual(named, {"POST", "DELETE"})

    def test_the_server_answers_every_request_the_page_makes(self):
        for method, path in [("GET", "/posts?after=0"), ("POST", "/posts"),
                             ("GET", "/likes"), ("POST", "/likes"), ("DELETE", "/likes"),
                             ("GET", "/sessions"), ("POST", "/sessions"),
                             ("DELETE", "/sessions"), ("POST", "/accounts")]:
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
        # The "⋯" menu starts hidden, and only addMenuItem shows it; nothing calls
        # addMenuItem yet. The views nav starts hidden, with one view.
        self.assertIn("menu.hidden = true;", self.page_code)
        self.assertEqual(re.findall(r"(?<!function )\baddMenuItem\(", self.page_code), [])
        with open(os.path.join(HERE, "index.html"), encoding="utf-8") as page_file:
            self.assertIn('<nav id="views" aria-label="Views" hidden>', page_file.read())
        # The timeline is the first view; search adds the second.
        self.assertEqual(re.findall(r'\baddView\("(\w+)"', self.page_code), ["timeline", "search"])

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
        self.assertEqual(set(server.too_fast_to_json(server.TooFast("Too many.", 3))),
                         {"error", "retry_after"})

    def test_every_request_that_can_be_too_fast_has_a_refused_branch(self):
        functions = functions_in(self.page_code)
        # The five requests the server limits, and the page function that sends each.
        for name, form in (("sendPost", "postForm"), ("logIn", "loginForm"),
                           ("signUp", "signupForm"), ("pressHeart", None)):
            with self.subTest(function=name):
                self.assertIn("!response.ok", functions[name])
                if form is not None:
                    self.assertIn(f"holdForm({form}, answer.retry_after)", functions[name])


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
        for words in ("Type a word to search for.", "A search must be {max} characters or fewer.",
                      "A search may have at most {max} words."):
            self.assertIn(words, self.page_code)

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
        self.assertEqual(re.findall(r'<option value="(\w+)">', self.html),
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


if __name__ == "__main__":
    unittest.main()
