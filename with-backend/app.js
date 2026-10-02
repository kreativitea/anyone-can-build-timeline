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

// For each post on the live timeline, kept by post id: its <li> ("item"), its
// slots, and what each part keeps. The heart part keeps likeButton and
// likeCount, so a new count from the server can be written straight into the
// right post. Search results and other lists are not kept here: only the live
// timeline is kept up to date.
const postParts = {};

// ---- A post is built from slots and parts ----
//
// A slot is a named place inside a post. In order: "head" (the names and the
// time), "body" (the text), "foot" (the heart), and "menu" (the "⋯" menu).
// A part is a function that fills slots: part(post, slots, item). The parts
// run in the order they were added. A feature adds its own part with one
// addPostPart(...) call, and never changes makePostItem.
const POST_SLOTS = ["head", "body", "foot"];
const POST_PARTS = [];

function addPostPart(part) {
  POST_PARTS.push(part);
}

// What a button inside a post does, by the name in its data-action. Every
// button in a post says what it does with data-action, and carries its post's
// id in data-post-id. The one click handler, clickOnTimeline, calls
// ACTIONS[name](postId, button). A feature adds ACTIONS.name = itsFunction.
const ACTIONS = {};

// Build one post, with its empty slots, then let every part fill them.
// Returns { item, slots, ...what the parts keep }. It does not put the post
// on the page: placePost does that.
function makePostItem(post) {
  const item = document.createElement("li");
  item.className = "post";
  item.dataset.postId = post.id;

  // The slots only group the parts. They take no room of their own (see
  // style.css), so the post looks the same as when the parts sat in it directly.
  const slots = {};
  for (const name of POST_SLOTS) {
    slots[name] = document.createElement("div");
    slots[name].className = "post-" + name;
    item.append(slots[name]);
  }
  slots.menu = makePostMenu();
  item.append(slots.menu);

  const parts = { item: item, slots: slots };
  for (const part of POST_PARTS) {
    // A part may return what it wants to keep, for example its button.
    Object.assign(parts, part(post, slots, item));
  }
  return parts;
}

// The "⋯" menu of a post: a <details> that opens a list of buttons. It stays
// hidden until addMenuItem puts something in it, so a post with an empty
// menu shows no "⋯" at all.
function makePostMenu() {
  const menu = document.createElement("details");
  menu.className = "post-menu";
  menu.hidden = true;
  const summary = document.createElement("summary");
  summary.setAttribute("aria-label", "More actions for this post");
  summary.textContent = "\u22ef";
  const list = document.createElement("ul");
  menu.append(summary, list);
  return menu;
}

// Add one button to a post's "⋯" menu. `action` is a name in ACTIONS.
function addMenuItem(slots, action, words) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "link-button";
  button.dataset.action = action;
  button.dataset.postId = slots.menu.closest(".post").dataset.postId;
  button.textContent = words;
  const row = document.createElement("li");
  row.append(button);
  slots.menu.querySelector("ul").append(row);
  slots.menu.hidden = false;
  return button;
}

// Put a built post on the page. "top": first in the timeline, so the newest
// is always first. "bottom": last in the timeline.
function placePost(item, post, where) {
  if (where === "top") {
    timeline.prepend(item);
  } else if (where === "bottom") {
    timeline.append(item);
  } else {
    throw new Error("placePost does not know where '" + where + "' is.");
  }
}

// Put one post at the top of the timeline, so the newest is always first.
function showPost(post) {
  // Skip a post this window already shows.
  if (post.id <= lastId) {
    return;
  }
  lastId = post.id;
  postParts[post.id] = makePostItem(post);
  placePost(postParts[post.id].item, post, "top");
}

// Take a post off the page, and stop keeping it up to date.
function removePost(postId) {
  const parts = postParts[postId];
  if (parts === undefined) {
    return;
  }
  parts.item.remove();
  delete postParts[postId];
}

// Build a post again from what the server now says, and swap it in, in the
// same place. The heart keeps how it looked until the next answer.
function redrawPost(post) {
  const old = postParts[post.id];
  if (old === undefined) {
    return;
  }
  const liked = old.likeButton.getAttribute("aria-pressed") === "true";
  postParts[post.id] = makePostItem(post);
  old.item.replaceWith(postParts[post.id].item);
  showLike(post.id, post.like_count, liked);
}

// ---- The parts that every post has ----

// The display name first (Aiko Tanaka), then the account name (@aiko).
// textContent, never innerHTML: a post is shown as words, so it cannot run code on the page.
addPostPart(function namesPart(post, slots) {
  const author = document.createElement("span");
  author.className = "post-author";
  author.textContent = post.display_name;

  const handle = document.createElement("span");
  handle.className = "post-handle";
  handle.textContent = "@" + post.author;

  slots.head.append(author, handle);
});

// When it was written.
addPostPart(function timePart(post, slots) {
  const time = document.createElement("span");
  time.className = "post-time";
  time.textContent = post.posted_at;
  slots.head.append(time);
});

// What it says.
addPostPart(function textPart(post, slots) {
  const text = document.createElement("p");
  text.className = "post-text";
  text.textContent = post.text;
  slots.body.append(text);
});

// The heart, and how many people have pressed it. The button says what it
// does (data-action="like") and carries its own post id, so one click handler
// on the timeline can serve every post.
addPostPart(function heartPart(post, slots) {
  const likeRow = document.createElement("div");
  likeRow.className = "like-row";

  const likeButton = document.createElement("button");
  likeButton.type = "button";
  likeButton.className = "like";
  likeButton.dataset.action = "like";
  likeButton.dataset.postId = post.id;
  likeButton.setAttribute("aria-pressed", "false");
  likeButton.textContent = "\u2665";

  const likeCount = document.createElement("span");
  likeCount.className = "like-count";
  likeCount.textContent = post.like_count;

  likeRow.append(likeButton, likeCount);
  slots.foot.append(likeRow);
  return { likeButton: likeButton, likeCount: likeCount };
});

// Show the heart as pressed, and write in the count. The server is the only
// place that knows both, so this is only ever told what they are.
function showLike(postId, count, liked) {
  const parts = postParts[postId];
  if (parts === undefined) {
    return;
  }
  parts.likeCount.textContent = count;
  parts.likeButton.classList.toggle("liked", liked);
  parts.likeButton.setAttribute("aria-pressed", liked ? "true" : "false");
  // What the button would do if it were pressed now, for a screen reader.
  parts.likeButton.setAttribute("aria-label", liked ? "Unlike this post" : "Like this post");
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
    for (const postId in postParts) {
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
  const parts = postParts[postId];
  if (parts === undefined) {
    return;
  }

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

  const liked = parts.likeButton.getAttribute("aria-pressed") === "true";
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

ACTIONS.like = pressHeart;

// One handler for the whole timeline, so a post added later works too. The
// button's data-action says which function in ACTIONS to call. Other lists of
// posts (search results, bookmarks) use this same handler.
function clickOnTimeline(event) {
  const button = event.target.closest("[data-action]");
  if (button === null) {
    return;
  }
  const action = ACTIONS[button.dataset.action];
  if (action !== undefined) {
    action(Number(button.dataset.postId), button);
  }
}

// ---- Views: one part of the page shown at a time ----
//
// A view is a <section data-view="name">. The buttons that switch between
// them are in <nav id="views">, which stays hidden while there is only one
// view. A feature adds its own view with addView(name, words).
const viewsNav = document.getElementById("views");

// Show this view, hide the others, and mark its button as the current one.
function showView(name) {
  for (const section of document.querySelectorAll("[data-view]")) {
    section.hidden = section.dataset.view !== name;
  }
  for (const button of viewsNav.querySelectorAll("button")) {
    if (button.dataset.showView === name) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  }
}

// Add a view: its button, and its section (made here, unless the page
// already has one). Returns the section, for the feature to fill.
function addView(name, words) {
  let section = document.querySelector('[data-view="' + name + '"]');
  if (section === null) {
    const views = document.querySelectorAll("[data-view]");
    section = document.createElement("section");
    section.dataset.view = name;
    section.hidden = true;
    views[views.length - 1].after(section);
  }
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.showView = name;
  button.textContent = words;
  button.addEventListener("click", function () {
    showView(name);
  });
  viewsNav.append(button);
  viewsNav.hidden = viewsNav.querySelectorAll("button").length < 2;
  return section;
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
addView("timeline", "Timeline");
showView("timeline");
askWhoIAm();
keepChecking();
