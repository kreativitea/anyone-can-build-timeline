// Timeline, the version WITH a backend.
//
// This page keeps nothing itself. It sends each new post, each like and each
// like taken back to the server (server.py), and every second it asks the
// server: "anything new?"
// Because every window asks the same server, every window sees every post.
//
// Posting and liking need a login. The page never says who you are: the
// server knows from the session cookie, which the browser sends by itself.
// The page cannot even read that cookie (it is HttpOnly), so it asks the
// server "who am I?" with GET /sessions.

// The same rules as the model in server.py, with the same names, so a rule
// changed on one side is easy to find on the other.
const MAX_TEXT = 280;
const MAX_AUTHOR = 40;
const MAX_DISPLAY_NAME = 50;
const MIN_PASSWORD = 8;
const MAX_PASSWORD = 200;
// The account name rule, the same as ACCOUNT_NAME in server.py.
const ACCOUNT_NAME = /^[A-Za-z0-9_]+$/;
// The characters a display name may not hold, the same as HIDDEN_CHARACTERS in server.py.
const HIDDEN_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]/;
const CANNOT_REACH = "Cannot reach the server. Trying again every second.";

const signedOutSection = document.getElementById("signed-out");
const signedInSection = document.getElementById("signed-in");
const loginForm = document.getElementById("login-form");
const loginNameBox = document.getElementById("login-name");
const loginPasswordBox = document.getElementById("login-password");
const signupForm = document.getElementById("signup-form");
const signupNameBox = document.getElementById("signup-name");
const signupDisplayNameBox = document.getElementById("signup-display-name");
const signupPasswordBox = document.getElementById("signup-password");
const whoDisplayName = document.getElementById("who-display-name");
const whoAccountName = document.getElementById("who-account-name");
const logoutButton = document.getElementById("logout");
const textBox = document.getElementById("text");
const countLine = document.getElementById("count");
const statusLine = document.getElementById("status");
const timeline = document.getElementById("timeline");
const postForm = document.getElementById("post-form");

// The key for the Colours choice in localStorage. The same key as the small
// script in index.html, which uses it before the page is drawn.
const THEME_KEY = "timeline-theme";
const themeSwitch = document.getElementById("theme");

// The id of the newest post this window has shown. 0 means "none yet".
let lastId = 0;

// Who is logged in in this window: { account_name, display_name }, or null.
let account = null;

// For each post on screen, its heart button and its count, kept by post id, so
// a new count from the server can be written straight into the right post.
const likeParts = {};

// Put one post at the top of the timeline, so the newest is always first.
function showPost(post) {
  // Skip a post this window already shows.
  if (post.id <= lastId) {
    return;
  }
  lastId = post.id;

  const item = document.createElement("li");
  item.className = "post";

  // The display name first (Aiko Tanaka), then the account name (@aiko).
  const author = document.createElement("span");
  author.className = "post-author";
  author.textContent = post.display_name;

  const handle = document.createElement("span");
  handle.className = "post-handle";
  handle.textContent = "@" + post.author;

  const time = document.createElement("span");
  time.className = "post-time";
  time.textContent = post.posted_at;

  const text = document.createElement("p");
  text.className = "post-text";
  text.textContent = post.text;

  // The heart, and how many people have pressed it. The button carries its own
  // post id, so one click handler on the timeline can serve every post.
  const likeRow = document.createElement("div");
  likeRow.className = "like-row";

  const likeButton = document.createElement("button");
  likeButton.type = "button";
  likeButton.className = "like";
  likeButton.dataset.postId = post.id;
  likeButton.setAttribute("aria-pressed", "false");
  likeButton.textContent = "\u2665";

  const likeCount = document.createElement("span");
  likeCount.className = "like-count";
  likeCount.textContent = post.like_count;

  likeRow.append(likeButton, likeCount);
  likeParts[post.id] = { button: likeButton, count: likeCount };

  // textContent, never innerHTML: a post is shown as words, so it cannot run code on the page.
  item.append(author, handle, time, text, likeRow);
  timeline.prepend(item);
}

// Show the heart as pressed, and write in the count. The server is the only
// place that knows both, so this is only ever told what they are.
function showLike(postId, count, liked) {
  const parts = likeParts[postId];
  if (parts === undefined) {
    return;
  }
  parts.count.textContent = count;
  parts.button.classList.toggle("liked", liked);
  parts.button.setAttribute("aria-pressed", liked ? "true" : "false");
  // What the button would do if it were pressed now, for a screen reader.
  parts.button.setAttribute("aria-label", liked ? "Unlike this post" : "Like this post");
}

function showStatus(words) {
  statusLine.textContent = words;
}

// Logged in: show who, and the post form. Hide the two account forms.
function showSignedIn(who) {
  account = who;
  whoDisplayName.textContent = who.display_name;
  whoAccountName.textContent = "@" + who.account_name;
  signedOutSection.hidden = true;
  signedInSection.hidden = false;
  showDraft(who);
}

// Not logged in: show the Log in and Sign up forms, and why, if there is a reason.
// The post box is emptied too, so the next person to log in on this computer
// does not see the last person's unsent words.
function showSignedOut(reason) {
  account = null;
  signedInSection.hidden = true;
  signedOutSection.hidden = false;
  hideDraft();
  showStatus(reason);
}

// The rules for a new account, the same as check_name, check_display_name and
// check_password in server.py. Returns the broken rule, or "" if none.
function accountProblem(name, displayName, password) {
  if (name === "") {
    return "The name must not be empty.";
  }
  if (name.length > MAX_AUTHOR) {
    return "The name must be " + MAX_AUTHOR + " characters or fewer.";
  }
  if (!ACCOUNT_NAME.test(name)) {
    return "The account name may use only letters, numbers and _.";
  }
  if (displayName.length > MAX_DISPLAY_NAME) {
    return "The display name must be " + MAX_DISPLAY_NAME + " characters or fewer.";
  }
  if (HIDDEN_CHARACTERS.test(displayName)) {
    return "The display name must not have hidden characters or line breaks.";
  }
  // A password is never trimmed: a space is part of it.
  if (password.length < MIN_PASSWORD) {
    return "The password must be at least " + MIN_PASSWORD + " characters.";
  }
  if (password.length > MAX_PASSWORD) {
    return "The password must be " + MAX_PASSWORD + " characters or fewer.";
  }
  return "";
}

// The rules for a post, the same as check_text in server.py.
function textProblem(text) {
  if (text === "") {
    return "The post must not be empty.";
  }
  if (text.length > MAX_TEXT) {
    return "The post must be " + MAX_TEXT + " characters or fewer.";
  }
  return "";
}

// The live count under the box: "x / 280".
function updateCount() {
  const length = textBox.value.length;
  countLine.textContent = length + " / " + MAX_TEXT;
  countLine.classList.toggle("too-long", length > MAX_TEXT);
}

// Drafts
//
// A half-written post is kept in this browser's localStorage, so it comes back
// after a reload, a closed tab or a restart. localStorage is a small store of
// text inside the browser, for this website only, that stays until it is
// removed. A draft never goes to the server.
//
// There is one draft for each account, under its own key, so two people on
// one computer never see each other's words. The draft is removed when the
// post is saved, or when the person logs out.
//
// Storage can be blocked (a browser set to refuse site data) or full. Then
// every use of it is caught, drafts quietly do nothing, and posting still works.

// The start of every draft key. The whole key is, for example, "timeline-draft:aiko".
const DRAFT_KEY_START = "timeline-draft:";

// The key for this account's draft. An account name holds only letters,
// numbers and _, and is unique without regard to capitals, so lower case is safe.
function draftKey(who) {
  return DRAFT_KEY_START + who.account_name.toLowerCase();
}

// This account's draft, or "" if there is none or storage is blocked.
function loadDraft(who) {
  try {
    return localStorage.getItem(draftKey(who)) || "";
  } catch (error) {
    return "";
  }
}

// Keep what is in the box now, for the person logged in. An empty box (or
// only spaces) removes the draft instead. A draft over the limit is still
// kept: the person may be cutting it down.
function saveDraft() {
  if (account === null) {
    return;
  }
  try {
    if (textBox.value.trim() === "") {
      localStorage.removeItem(draftKey(account));
    } else {
      localStorage.setItem(draftKey(account), textBox.value);
    }
  } catch (error) {
    // Storage is blocked or full. The draft is not kept; nothing else changes.
  }
}

// Remove the draft of the person logged in.
function forgetDraft() {
  if (account === null) {
    return;
  }
  try {
    localStorage.removeItem(draftKey(account));
  } catch (error) {
    // Storage is blocked, so there is no draft to remove.
  }
}

// Put this account's draft in the box, or empty the box if there is none.
function showDraft(who) {
  const draft = loadDraft(who);
  textBox.value = draft;
  updateCount();
  if (draft !== "") {
    showStatus("Your unsent post is back.");
  }
}

// Empty the box while nobody is logged in. The draft stays in storage.
function hideDraft() {
  textBox.value = "";
  updateCount();
}

// When the page opens, ask the server who is logged in in this window.
async function askWhoIAm() {
  try {
    const response = await fetch("/sessions");
    const answer = await response.json();
    if (response.ok) {
      showSignedIn(answer);
    } else {
      // 401: nobody. That is not a problem, so no reason is shown.
      showSignedOut("");
    }
  } catch (error) {
    showSignedOut(CANNOT_REACH);
  }
}

// Ask the server for every post newer than the last one we have.
async function checkForNewPosts() {
  try {
    const response = await fetch("/posts?after=" + lastId);
    const posts = await response.json();
    // The server sends them oldest first. Each one goes on top, so the newest ends up first.
    for (const post of posts) {
      showPost(post);
    }
    // A like changes no post, so `after` would never bring one. The counts are
    // asked for separately, and all of them come back each time. "mine" comes
    // from the cookie: it is empty when nobody is logged in.
    const likesAnswer = await fetch("/likes");
    const likes = await likesAnswer.json();
    for (const postId in likeParts) {
      showLike(postId, likes.counts[postId] || 0, likes.mine.includes(Number(postId)));
    }
    if (statusLine.textContent === CANNOT_REACH) {
      showStatus("");
    }
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// Ask, wait for the answer, wait one second, then ask again. Forever.
async function keepChecking() {
  await checkForNewPosts();
  setTimeout(keepChecking, 1000);
}

// After a login, a sign-up or a log-out, the hearts this window shows as
// pressed belong to someone else. Ask the server again straight away.
async function afterAccountChange() {
  loginPasswordBox.value = "";
  signupPasswordBox.value = "";
  await checkForNewPosts();
}

// Log in with an account name and password.
async function logIn(event) {
  event.preventDefault();
  const name = loginNameBox.value.trim();
  const password = loginPasswordBox.value;
  if (name === "" || password === "") {
    showStatus("Please type your account name and your password.");
    return;
  }
  try {
    const response = await fetch("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_name: name, password: password }),
    });
    const answer = await response.json();
    if (!response.ok) {
      // The same words for a wrong name and a wrong password: see WRONG_LOGIN in server.py.
      showSignedOut(answer.error);
      return;
    }
    showStatus("");
    showSignedIn(answer);
    await afterAccountChange();
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// Make a new account. The server logs it in at once.
async function signUp(event) {
  event.preventDefault();
  const name = signupNameBox.value.trim();
  const displayName = signupDisplayNameBox.value.trim();
  const password = signupPasswordBox.value;

  // A quick check on the page, so the person does not wait for an answer.
  // The server checks the same rules again. Never trust only the screen:
  // anyone can send a request without using this page at all.
  const problem = accountProblem(name, displayName, password);
  if (problem !== "") {
    showStatus(problem);
    return;
  }
  try {
    const response = await fetch("/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_name: name, display_name: displayName, password: password }),
    });
    const answer = await response.json();
    if (!response.ok) {
      // The server refused it. It says which rule was broken.
      showStatus(answer.error);
      return;
    }
    showStatus("");
    showSignedIn(answer);
    await afterAccountChange();
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// Log out. The server deletes this window's session and tells the browser
// to forget the cookie.
async function logOut() {
  try {
    await fetch("/sessions", { method: "DELETE" });
    forgetDraft();
    showSignedOut("");
    await afterAccountChange();
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// Send a new post to the server. It says only what the post says: who wrote
// it is the person logged in, and the server knows that from the cookie.
async function sendPost(event) {
  event.preventDefault();
  const text = textBox.value;

  // A quick check on the page, so the person does not wait for an answer.
  // The server checks the same rules again.
  const problem = textProblem(text.trim());
  if (problem !== "") {
    showStatus(problem);
    return;
  }

  try {
    const response = await fetch("/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      // The login has ended. Show the Log in form, and the server's reason.
      showSignedOut(answer.error);
      return;
    }
    if (!response.ok) {
      // The server refused the post. It says which rule was broken.
      showStatus(answer.error);
      return;
    }
    // Saved. Ask for new posts now, instead of waiting for the next second.
    // This also brings in any post from another window that came just before ours.
    showStatus("");
    textBox.value = "";
    forgetDraft();
    updateCount();
    await checkForNewPosts();
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// Press the heart: like the post, or take the like back if it is already
// pressed. The method says which: POST adds a like, DELETE removes one.
async function pressHeart(postId) {
  const parts = likeParts[postId];

  // Only a person who is logged in can like. The server checks this again.
  if (account === null) {
    showStatus("Please log in to like a post.");
    return;
  }

  // One press at a time. Two fast presses would both read the heart as it is
  // now, before the first answer arrives, and send the same request twice.
  if (parts.busy) {
    return;
  }
  parts.busy = true;

  const liked = parts.button.getAttribute("aria-pressed") === "true";
  try {
    const response = await fetch("/likes", {
      method: liked ? "DELETE" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_id: postId }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      // The login has ended. Show the Log in form, and the server's reason.
      showSignedOut(answer.error);
      await checkForNewPosts();
      return;
    }
    if (!response.ok) {
      // The server refused it, and says which rule was broken. This window had
      // the heart wrong, so ask the server what is true instead of guessing.
      showStatus(answer.error);
      await checkForNewPosts();
      return;
    }
    // Done. Show the new count now, instead of waiting for the next second.
    showStatus("");
    showLike(postId, answer.like_count, !liked);
  } catch (error) {
    showStatus(CANNOT_REACH);
  } finally {
    parts.busy = false;
  }
}

// The Colours choice saved in this browser: "light", "dark", or "auto" when
// there is none (or storage is blocked, or it holds something else).
function savedTheme() {
  try {
    const theme = localStorage.getItem(THEME_KEY);
    if (theme === "light" || theme === "dark") {
      return theme;
    }
  } catch (error) {
    // Storage is blocked: nothing was saved.
  }
  return "auto";
}

// Tell the CSS which colours to use. Auto is no data-theme at all.
function useTheme(theme) {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
  } else {
    delete document.documentElement.dataset.theme;
  }
}

// The Colours switch changed: use the new colours now, and remember them.
function chooseTheme() {
  const theme = themeSwitch.value;
  useTheme(theme);
  try {
    if (theme === "light" || theme === "dark") {
      localStorage.setItem(THEME_KEY, theme);
    } else {
      localStorage.removeItem(THEME_KEY);
    }
  } catch (error) {
    // Storage is blocked: the colours still change in this tab, but are not
    // remembered. Nothing to tell the person; it is not their mistake.
  }
}

// One handler for the whole timeline, so a post added later works too.
function clickOnTimeline(event) {
  const button = event.target.closest(".like");
  if (button !== null) {
    pressHeart(Number(button.dataset.postId));
  }
}

textBox.addEventListener("input", updateCount);
textBox.addEventListener("input", saveDraft);
timeline.addEventListener("click", clickOnTimeline);
postForm.addEventListener("submit", sendPost);
loginForm.addEventListener("submit", logIn);
signupForm.addEventListener("submit", signUp);
logoutButton.addEventListener("click", logOut);
themeSwitch.value = savedTheme();
themeSwitch.addEventListener("change", chooseTheme);
askWhoIAm();
keepChecking();
