"""Tests for server.py. Run them with:  python3 -m unittest

Most tests call the MODEL directly, with a database made only for the test.
RealServerTest starts the real server and talks to it, as the page does.
JourneyTest walks one whole journey through all three levels at once: the
requests the page makes, the server that answers them, and the rows in the
database file.
PageAndServerAgreeTest reads app.js and checks the page and the server agree.
"""

import http.cookiejar
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import server

HERE = os.path.dirname(os.path.abspath(server.__file__))

# A password for the tests. It is long enough, and easy to spot in a table.
PASSWORD = "correct horse battery"


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
            server.save_post(self.db_path, aiko, "a" * 281)

    def test_text_of_exactly_280_is_allowed(self):
        aiko = self.sign_up("aiko")
        row = server.save_post(self.db_path, aiko, "a" * 280)
        self.assertEqual(len(row["text"]), 280)

    def test_saved_post_comes_back_with_id_and_time(self):
        aiko = self.sign_up("aiko", "Aiko Tanaka")
        row = server.save_post(self.db_path, aiko, " the library is open late ")
        self.assertEqual(row["id"], 1)
        self.assertEqual(row["author"], "aiko")
        self.assertEqual(row["display_name"], "Aiko Tanaka")
        self.assertEqual(row["text"], "the library is open late")
        self.assertRegex(row["posted_at"], r"^\d\d:\d\d$")

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
        row = server.save_post(self.db_path, aiko, "the library is open late tonight")
        self.assertEqual(server.post_to_log_line(row),
                         row["posted_at"] + '  Aiko Tanaka @aiko: "the library is open late tonight"')

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
        self.assertEqual(self.rows("SELECT * FROM posts ORDER BY id"), posts)
        self.assertEqual(self.rows("SELECT * FROM likes ORDER BY post_id, user_id"), likes)
        self.assertEqual(self.rows("PRAGMA user_version"), [(1,)])

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
        self.assertEqual(self.rows("PRAGMA user_version"), [(1,)])

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
        self.assertEqual(asked, {"/posts", "/likes", "/sessions", "/accounts"})

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
