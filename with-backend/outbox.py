"""Timeline: the outbox. It carries emails out, one at a time, on its own thread.

An outbox decides nothing and reads no database. The model decides whether an
email should be made (reply_email_for in server.py), the view writes it
(reply_email_message), and the outbox only carries it out. Today nothing is
really sent: the running server prints each email in its terminal.

Words used here:
  thread  a second line of work running inside the same program at the same time.
  queue   a waiting line. The server puts an email at the back; the outbox's
          thread takes emails from the front, one at a time.

There are two kinds of outbox:
  ConsoleOutbox  for the running server: prints each whole email in the terminal.
  KeptOutbox     for the tests: keeps each email in a list, and prints nothing.
A later plan may add a third kind here that really sends, and change nothing else.
It uses only the Python standard library.
"""

import queue
import re
import sys
import threading

# A terminal obeys some invisible characters: one can move back to the start of
# the line, another can clear it. They are shown as "?" in a printed email, so
# nothing written in a reply can change what the terminal shows. A tab is kept.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# The two lines around a printed email.
FRAME_WIDTH = 72
EMAIL_START = " EMAIL (printed here, not sent) ".center(FRAME_WIDTH, "=")
EMAIL_END = " END OF EMAIL ".center(FRAME_WIDTH, "=")
# Every line inside the frame starts with this. A post's text may hold line
# breaks, but it can never make a line that starts without "| ", so it can
# never fake the END line, or a post's line in the terminal.
INSIDE = "| "


class Outbox:
    """One queue and one background thread. A kind of outbox writes deliver().

    send_later(message) puts the email in the queue and returns at once, so the
    request that made the email never waits for it. The thread takes each
    email and calls deliver(email). If that fails, one line is printed and the
    email is forgotten: no second try. The reply it was about is already saved.
    """

    def __init__(self, stream=None):
        # Where the one line about a failed email is printed.
        self.stream = stream if stream is not None else sys.stdout
        self.waiting = queue.Queue()
        self.thread = None
        self.starting = threading.Lock()

    def send_later(self, message):
        """Put the email in the queue, and return at once."""
        # The thread starts with the first email, so a server that never makes
        # an email (most tests) never has a thread waiting for nothing.
        with self.starting:
            if self.thread is None:
                # daemon=True: the thread stops when the program stops.
                self.thread = threading.Thread(target=self.keep_delivering, daemon=True)
                self.thread.start()
        self.waiting.put(message)

    def keep_delivering(self):
        """The thread: take each email from the front of the queue and carry it out."""
        while True:
            message = self.waiting.get()
            try:
                self.deliver(message)
            except Exception as error:   # any failure: one line, then the next email
                reason = " ".join(str(error).split()) or type(error).__name__
                self.stream.write("An email could not be printed: " + reason + "\n")
                self.stream.flush()
            finally:
                self.waiting.task_done()

    def wait_until_sent(self):
        """Wait until every email in the queue has been carried out. For the tests."""
        self.waiting.join()

    def deliver(self, message):
        raise NotImplementedError("each kind of outbox writes its own deliver")


class ConsoleOutbox(Outbox):
    """The running server's outbox: it prints each whole email in the terminal.

    Nothing is sent. The person running the server reads the email there, and
    copies a confirm link from it into the browser.
    """

    def deliver(self, message):
        # The headers read this way are decoded, and get_content() decodes the
        # body, so Japanese is printed as Japanese, not as encoded text.
        inside = ["To:      " + message["To"], "Subject: " + message["Subject"], ""]
        # splitlines() splits at every kind of line break, not only \n.
        inside += message.get_content().splitlines()
        lines = [EMAIL_START]
        lines += [INSIDE + CONTROL_CHARACTERS.sub("?", line) for line in inside]
        lines.append(EMAIL_END)
        # One write for the whole email, so a post's line printed at the same
        # moment cannot land in the middle of it.
        self.stream.write("\n".join(lines) + "\n")
        self.stream.flush()


class KeptOutbox(Outbox):
    """The tests' outbox: it keeps each email in the list `sent`, and prints nothing."""

    def __init__(self, stream=None):
        Outbox.__init__(self, stream)
        self.sent = []

    def deliver(self, message):
        self.sent.append(message)
