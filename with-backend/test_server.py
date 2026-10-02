"""Tests for server.py. Run them with:  python3 -m unittest

Most tests call the MODEL directly, with a database made only for the test.
RealServerTest starts the real server and talks to it, as the page does.
JourneyTest walks one whole journey through all three levels at once: the
requests the page makes, the server that answers them, and the rows in the
database file.
"""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

import server


class ModelTests(unittest.TestCase):

    def setUp(self):
        # A new, empty database for every test, in a temporary folder.
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "test.db")
        server.create_tables(self.db_path)

    def tearDown(self):
        self.folder.cleanup()

    def test_empty_text_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, "Aiko", "   ")

    def test_too_long_text_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, "Aiko", "a" * 281)

    def test_text_of_exactly_280_is_allowed(self):
        row = server.save_post(self.db_path, "Aiko", "a" * 280)
        self.assertEqual(len(row["text"]), 280)

    def test_empty_author_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, "", "hello")

    def test_too_long_author_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            server.save_post(self.db_path, "a" * 41, "hello")

    def test_saved_post_comes_back_with_id_and_time(self):
        row = server.save_post(self.db_path, " Aiko ", " the library is open late ")
        self.assertEqual(row["id"], 1)
        self.assertEqual(row["author"], "Aiko")
        self.assertEqual(row["text"], "the library is open late")
        self.assertRegex(row["posted_at"], r"^\d\d:\d\d$")

    def test_the_same_name_is_one_user(self):
        server.save_post(self.db_path, "Aiko", "first")
        server.save_post(self.db_path, "Aiko", "second")
        server.save_post(self.db_path, "Ben", "third")
        connection = server.connect(self.db_path)
        users = connection.execute("SELECT name FROM users ORDER BY id").fetchall()
        connection.close()
        self.assertEqual([u["name"] for u in users], ["Aiko", "Ben"])

    def test_a_post_points_at_its_author_by_id(self):
        server.save_post(self.db_path, "Aiko", "the library is open late tonight")
        connection = server.connect(self.db_path)
        post = connection.execute("SELECT * FROM posts").fetchone()
        user = connection.execute("SELECT * FROM users").fetchone()
        connection.close()
        self.assertEqual(post["author_id"], user["id"])
        self.assertNotIn("author", post.keys())  # the name is kept once, in users

    def test_after_returns_only_newer_posts_oldest_first(self):
        server.save_post(self.db_path, "Aiko", "first")
        server.save_post(self.db_path, "Ben", "second")
        server.save_post(self.db_path, "Aiko", "third")
        rows = server.posts_after(self.db_path, 1)
        self.assertEqual([row["text"] for row in rows], ["second", "third"])


    def test_a_like_is_kept_as_one_row_and_counted(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        post_id, count = server.add_like(self.db_path, "Ben", post["id"])
        self.assertEqual(post_id, post["id"])
        self.assertEqual(count, 1)
        connection = server.connect(self.db_path)
        likes = connection.execute("SELECT * FROM likes").fetchall()
        connection.close()
        self.assertEqual(len(likes), 1)
        self.assertEqual(likes[0]["post_id"], post["id"])

    def test_the_same_name_cannot_like_the_same_post_twice(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, "Ben", post["id"])
        connection = server.connect(self.db_path)
        rows = connection.execute("SELECT COUNT(*) AS n FROM likes").fetchone()
        connection.close()
        self.assertEqual(rows["n"], 1)   # the database keeps only one

    def test_two_people_can_like_the_same_post(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        post_id, count = server.add_like(self.db_path, "Chie", post["id"])
        self.assertEqual(count, 2)

    def test_the_same_person_can_like_two_different_posts(self):
        first = server.save_post(self.db_path, "Aiko", "first")
        second = server.save_post(self.db_path, "Aiko", "second")
        server.add_like(self.db_path, "Ben", first["id"])
        post_id, count = server.add_like(self.db_path, "Ben", second["id"])
        self.assertEqual(count, 1)

    def test_a_like_for_a_post_that_does_not_exist_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, "Ben", 999)

    def test_a_like_without_a_name_is_refused(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, "   ", post["id"])

    def test_a_like_without_a_post_id_is_refused(self):
        with self.assertRaises(server.RuleBroken):
            server.add_like(self.db_path, "Ben", None)

    def test_a_post_comes_back_with_its_like_count(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        self.assertEqual(server.post_to_json(post)["like_count"], 0)
        server.add_like(self.db_path, "Ben", post["id"])
        rows = server.posts_after(self.db_path, 0)
        self.assertEqual(server.post_to_json(rows[0])["like_count"], 1)

    def test_likes_for_gives_the_counts_and_this_name_s_own_likes(self):
        first = server.save_post(self.db_path, "Aiko", "first")
        second = server.save_post(self.db_path, "Aiko", "second")
        server.add_like(self.db_path, "Ben", first["id"])
        server.add_like(self.db_path, "Chie", first["id"])
        server.add_like(self.db_path, "Chie", second["id"])
        counts, mine = server.likes_for(self.db_path, "Chie")
        answer = server.likes_to_json(counts, mine)
        self.assertEqual(answer["counts"], {str(first["id"]): 2, str(second["id"]): 1})
        self.assertEqual(answer["mine"], [first["id"], second["id"]])
        counts, mine = server.likes_for(self.db_path, "Ben")
        self.assertEqual(server.likes_to_json(counts, mine)["mine"], [first["id"]])

    def test_a_like_taken_back_leaves_no_row(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        post_id, count = server.remove_like(self.db_path, "Ben", post["id"])
        self.assertEqual((post_id, count), (post["id"], 0))
        connection = server.connect(self.db_path)
        likes = connection.execute("SELECT * FROM likes").fetchall()
        connection.close()
        self.assertEqual(likes, [])   # the row is gone, not marked

    def test_taking_back_a_like_you_do_not_have_is_refused(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        with self.assertRaises(server.RuleBroken):
            server.remove_like(self.db_path, "Chie", post["id"])

    def test_taking_back_a_like_twice_is_refused(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        server.remove_like(self.db_path, "Ben", post["id"])
        with self.assertRaises(server.RuleBroken):
            server.remove_like(self.db_path, "Ben", post["id"])

    def test_taking_a_like_back_does_not_add_a_user(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        with self.assertRaises(server.RuleBroken):
            server.remove_like(self.db_path, "Nobody", post["id"])
        connection = server.connect(self.db_path)
        users = connection.execute("SELECT name FROM users").fetchall()
        connection.close()
        self.assertEqual([u["name"] for u in users], ["Aiko"])

    def test_like_then_take_it_back_then_like_again(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        server.remove_like(self.db_path, "Ben", post["id"])
        post_id, count = server.add_like(self.db_path, "Ben", post["id"])
        self.assertEqual(count, 1)   # nothing was left behind to get in the way

    def test_taking_one_like_back_leaves_the_other_person_s(self):
        post = server.save_post(self.db_path, "Aiko", "hello")
        server.add_like(self.db_path, "Ben", post["id"])
        server.add_like(self.db_path, "Chie", post["id"])
        post_id, count = server.remove_like(self.db_path, "Ben", post["id"])
        self.assertEqual(count, 1)
        counts, mine = server.likes_for(self.db_path, "Chie")
        self.assertEqual(server.likes_to_json(counts, mine)["mine"], [post["id"]])

    def test_asking_about_likes_does_not_add_a_user(self):
        server.save_post(self.db_path, "Aiko", "hello")
        server.likes_for(self.db_path, "Nobody")
        connection = server.connect(self.db_path)
        users = connection.execute("SELECT name FROM users").fetchall()
        connection.close()
        self.assertEqual([u["name"] for u in users], ["Aiko"])

    def test_log_line_has_the_time_the_author_and_the_text(self):
        row = server.save_post(self.db_path, "Aiko", "the library is open late tonight")
        self.assertEqual(server.post_to_log_line(row),
                         row["posted_at"] + "  Aiko: the library is open late tonight")


class RealServerTest(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        db_path = os.path.join(self.folder.name, "test.db")
        # Port 0 asks the computer for any free port.
        self.server = server.make_server(0, db_path)
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    def post(self, data, path="/posts"):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(request)

    def test_post_then_get(self):
        answer = self.post({"author": "Aiko", "text": "hello"})
        self.assertEqual(answer.status, 201)
        with urllib.request.urlopen(self.base + "/posts?after=0") as answer:
            posts = json.loads(answer.read())
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["author"], "Aiko")
        self.assertEqual(posts[0]["text"], "hello")

    def test_like_then_get_likes(self):
        self.post({"author": "Aiko", "text": "hello"})
        answer = self.post({"author": "Ben", "post_id": 1}, "/likes")
        self.assertEqual(answer.status, 201)
        self.assertEqual(json.loads(answer.read()), {"post_id": 1, "like_count": 1})
        with urllib.request.urlopen(self.base + "/likes?author=Ben") as answer:
            likes = json.loads(answer.read())
        self.assertEqual(likes, {"counts": {"1": 1}, "mine": [1]})

    def test_a_second_like_gets_400_and_a_reason(self):
        self.post({"author": "Aiko", "text": "hello"})
        self.post({"author": "Ben", "post_id": 1}, "/likes")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"author": "Ben", "post_id": 1}, "/likes")
        self.assertEqual(caught.exception.code, 400)
        reason = json.loads(caught.exception.read())["error"]
        self.assertIn("already", reason)
        caught.exception.close()

    def test_empty_post_gets_400_and_a_reason(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"author": "Aiko", "text": ""})
        self.assertEqual(caught.exception.code, 400)
        reason = json.loads(caught.exception.read())["error"]
        self.assertIn("empty", reason)
        caught.exception.close()


class JourneyTest(unittest.TestCase):
    """One whole journey, through all three levels at once.

    The other tests look at one level each. This one follows a like from the
    page to the store and back, the way two people really would.

    Every request below is one the page itself makes, with the same method and
    the same JSON: see `keepChecking`, `sendPost` and `pressHeart` in `app.js`.
    The answers come from the real server over real HTTP. After each step the
    database file is opened and read with SQL, so a step is believed only if
    the rows agree with what the page was told.
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

    # -- the four requests the page makes, under the page's own names --

    def page_asks_for_new_posts(self, after=0):
        """checkForNewPosts: GET /posts?after=<the newest id this window has>"""
        with urllib.request.urlopen(self.base + "/posts?after=" + str(after)) as answer:
            return json.loads(answer.read())

    def page_asks_for_counts(self, author):
        """checkForNewPosts: GET /likes?author=<the name in the name box>"""
        url = self.base + "/likes?author=" + urllib.parse.quote(author)
        with urllib.request.urlopen(url) as answer:
            return json.loads(answer.read())

    def page_sends(self, path, data, method):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request) as answer:
            return answer.status, json.loads(answer.read())

    def page_posts(self, author, text):
        """sendPost: POST /posts"""
        return self.page_sends("/posts", {"author": author, "text": text}, "POST")

    def page_presses_heart(self, author, post_id, already_liked):
        """pressHeart: POST /likes to like, DELETE /likes to take the like back"""
        return self.page_sends("/likes", {"author": author, "post_id": post_id},
                               "DELETE" if already_liked else "POST")

    def press_is_refused(self, author, post_id, already_liked):
        """A press the server refuses. The page shows the reason it gives."""
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.page_presses_heart(author, post_id, already_liked)
        reason = json.loads(caught.exception.read())["error"]
        caught.exception.close()
        return caught.exception.code, reason

    # -- the store, read straight out of the file --

    def rows(self, sql):
        connection = server.connect(self.db_path)
        rows = [tuple(row) for row in connection.execute(sql).fetchall()]
        connection.close()
        return rows

    def test_the_whole_journey_of_a_like(self):
        # 1. Aiko opens the page. Nothing anywhere yet.
        self.assertEqual(self.page_asks_for_new_posts(), [])
        self.assertEqual(self.page_asks_for_counts("Aiko"), {"counts": {}, "mine": []})
        self.assertEqual(self.rows("SELECT * FROM likes"), [])

        # 2. Aiko posts. One user, one post, no likes.
        status, post = self.page_posts("Aiko", "the library is open late tonight")
        self.assertEqual(status, 201)
        self.assertEqual(post["like_count"], 0)
        self.assertEqual(self.rows("SELECT name FROM users"), [("Aiko",)])
        self.assertEqual(self.rows("SELECT id, author_id FROM posts"), [(1, 1)])
        self.assertEqual(self.rows("SELECT * FROM likes"), [])

        # 3. Ben's window polls from 0, and sees Aiko's post with no likes.
        #    Ben has typed a name but done nothing, so Ben is not a user yet.
        posts = self.page_asks_for_new_posts(0)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["like_count"], 0)
        self.assertEqual(self.page_asks_for_counts("Ben"), {"counts": {}, "mine": []})
        self.assertEqual(self.rows("SELECT name FROM users"), [("Aiko",)])

        # 4. Ben presses the heart. One row appears, pointing at Ben and the post.
        status, answer = self.page_presses_heart("Ben", 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 1}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 2)])
        self.assertEqual(self.rows("SELECT id, name FROM users ORDER BY id"),
                         [(1, "Aiko"), (2, "Ben")])

        # 5. Both windows poll. The count is 1 in each, but the heart is Ben's.
        self.assertEqual(self.page_asks_for_counts("Aiko"), {"counts": {"1": 1}, "mine": []})
        self.assertEqual(self.page_asks_for_counts("Ben"), {"counts": {"1": 1}, "mine": [1]})

        # 6. Ben presses the same heart again. The row is gone, not marked.
        status, answer = self.page_presses_heart("Ben", 1, already_liked=True)
        self.assertEqual((status, answer), (200, {"post_id": 1, "like_count": 0}))
        self.assertEqual(self.rows("SELECT * FROM likes"), [])
        # With no likes left, the post has no entry at all. The page shows 0
        # because of the `|| 0` in checkForNewPosts.
        self.assertEqual(self.page_asks_for_counts("Ben"), {"counts": {}, "mine": []})

        # 7. And a third press likes it again, so nothing was left behind.
        status, answer = self.page_presses_heart("Ben", 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 1}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 2)])

        # 8. Chie likes the same post: two rows, two people, one post.
        status, answer = self.page_presses_heart("Chie", 1, already_liked=False)
        self.assertEqual((status, answer), (201, {"post_id": 1, "like_count": 2}))
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes ORDER BY user_id"),
                         [(1, 2), (1, 3)])

        # 9. A window whose heart is out of date presses to like what it has
        #    already liked. The server refuses, and the store does not move.
        code, reason = self.press_is_refused("Ben", 1, already_liked=False)
        self.assertEqual(code, 400)
        self.assertIn("already", reason)
        self.assertEqual(len(self.rows("SELECT * FROM likes")), 2)

        # 10. Ben takes the like back, then presses again in a window that still
        #     shows it pressed. The second one is refused, and Chie's row stays.
        self.page_presses_heart("Ben", 1, already_liked=True)
        code, reason = self.press_is_refused("Ben", 1, already_liked=True)
        self.assertEqual(code, 400)
        self.assertIn("not liked", reason)
        self.assertEqual(self.rows("SELECT post_id, user_id FROM likes"), [(1, 3)])
        self.assertEqual(self.page_asks_for_counts("Chie"), {"counts": {"1": 1}, "mine": [1]})

        # 11. Chie takes hers back too. No likes left, and the post is untouched.
        self.page_presses_heart("Chie", 1, already_liked=True)
        self.assertEqual(self.rows("SELECT * FROM likes"), [])
        self.assertEqual(self.page_asks_for_new_posts(0)[0]["like_count"], 0)
        self.assertEqual(self.rows("SELECT id, text FROM posts"),
                         [(1, "the library is open late tonight")])

        # 12. Through all of that, three people were added and no more: no like,
        #     and no like taken back, ever invented one.
        self.assertEqual(self.rows("SELECT name FROM users ORDER BY id"),
                         [("Aiko",), ("Ben",), ("Chie",)])


class PageAndServerAgreeTest(unittest.TestCase):
    """AGENTS.md: "the page and the server must agree".

    The page's own code cannot run here, because that would need a browser or
    Node, and this project needs only python3. So instead these read `app.js`
    and check that every request it names is one the real server answers. A
    route renamed on one side and not the other fails here.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.server = server.make_server(0, os.path.join(self.folder.name, "test.db"))
        self.base = "http://127.0.0.1:" + str(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        page = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "app.js")
        with open(page, encoding="utf-8") as page_file:
            self.page_code = page_file.read()

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

    def test_the_page_asks_for_nothing_but_posts_and_likes(self):
        asked = set(re.findall(r'fetch\("(/[a-z]*)', self.page_code))
        self.assertEqual(asked, {"/posts", "/likes"})

    def test_the_page_names_only_the_methods_tried_below(self):
        # A GET needs no method, so the page names only the other two.
        named = set(re.findall(r'"(GET|POST|PUT|PATCH|DELETE)"', self.page_code))
        self.assertEqual(named, {"POST", "DELETE"})

    def test_the_server_answers_every_request_the_page_makes(self):
        for method, path in [("GET", "/posts?after=0"), ("POST", "/posts"),
                             ("GET", "/likes?author=Aiko"), ("POST", "/likes"),
                             ("DELETE", "/likes")]:
            with self.subTest(request=method + " " + path):
                code = self.answer_code(method, path)
                # 400 is a fine answer here: the body is empty on purpose, so a
                # rule is broken. 404 or 501 would mean the server does not know
                # this request at all.
                self.assertNotIn(code, (404, 501))


if __name__ == "__main__":
    unittest.main()
