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
const MAX_TEXT = 560;
const MAX_AUTHOR = 40;
const MAX_DISPLAY_NAME = 50;
const MIN_PASSWORD = 8;
const MAX_PASSWORD = 200;
// The account name rule, the same as ACCOUNT_NAME in server.py.
const ACCOUNT_NAME = /^[A-Za-z0-9_]+$/;
// The characters a display name may not hold, the same as HIDDEN_CHARACTERS in server.py.
const HIDDEN_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]/;
const CANNOT_REACH = "Cannot reach the server. Trying again every second.";
// The words on the button under a long post (long-posts).
const SHOW_MORE = "Show more";
const SHOW_LESS = "Show less";

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
  const time = timeElement(post.posted_at, post.old_clock_time);
  slots.head.append(time);
});

// ---- timestamps: "5 minutes ago", and the full date on hover ----
// The server sends each time in UTC, like 2026-10-02T07:42:10Z. The page shows
// it in the reader's own time zone and language ("undefined" as the locale
// means "the browser's language"). The order of the timeline never uses the
// time, only the post id.

// How long ago `moment` was, seen from `now`. Both are Date values.
function timeAgo(moment, now) {
  const seconds = Math.floor((now - moment) / 1000);
  // Under a minute, or in the future: the reader's clock may be a little
  // ahead of or behind the server's, and a new post must never say "in 3 seconds".
  if (seconds < 60) {
    return "just now";
  }
  const words = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (seconds < 60 * 60) {
    return words.format(-Math.floor(seconds / 60), "minute");
  }
  if (seconds < 24 * 60 * 60) {
    return words.format(-Math.floor(seconds / (60 * 60)), "hour");
  }
  if (seconds < 7 * 24 * 60 * 60) {
    return words.format(-Math.floor(seconds / (24 * 60 * 60)), "day");
  }
  // A week or more: the date itself ("2 Oct"), with the year if it is not this year.
  const how = { day: "numeric", month: "short" };
  if (moment.getFullYear() !== now.getFullYear()) {
    how.year = "numeric";
  }
  return moment.toLocaleDateString(undefined, how);
}

// The full date and time, in the reader's time zone, for the tooltip.
function fullLocalTime(moment) {
  return moment.toLocaleString(undefined, { dateStyle: "full", timeStyle: "medium" });
}

// One time on the page. Other features reuse this: with a full time it makes
// <time datetime="..." title="..." data-relative>, and refreshTimes keeps its
// words up to date. A post from before Timeline kept dates has only its old
// clock time, so it says so instead of guessing a date.
function timeElement(postedAt, oldClockTime) {
  if (!postedAt) {
    const unknown = document.createElement("span");
    unknown.className = "post-time post-time-unknown";
    unknown.setAttribute("title", "Posted before Timeline kept dates");
    unknown.textContent = oldClockTime + " \u00b7 date unknown";
    return unknown;
  }
  const moment = new Date(postedAt);
  const time = document.createElement("time");
  time.className = "post-time";
  time.setAttribute("datetime", postedAt);
  time.setAttribute("title", fullLocalTime(moment));
  time.dataset.relative = "";
  time.textContent = timeAgo(moment, new Date());
  return time;
}

// Write every "… ago" again, so the words change as time passes.
function refreshTimes() {
  const now = new Date();
  for (const time of document.querySelectorAll("time[data-relative]")) {
    time.textContent = timeAgo(new Date(time.getAttribute("datetime")), now);
  }
}

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

  // The count is a button too: it opens the list of who liked the post (who-liked).
  const likeCount = document.createElement("button");
  likeCount.type = "button";
  likeCount.className = "like-count";
  likeCount.dataset.action = "likers";
  likeCount.dataset.postId = post.id;
  likeCount.setAttribute("aria-expanded", "false");
  likeCount.setAttribute("aria-controls", "likers-" + post.id);
  likeCount.setAttribute("aria-label", whoLikedSay("likers_show"));
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
  // who-liked: the line under the post is out of date when either one changed.
  if (parts.summaryFor !== count + ":" + liked) {
    parts.summaryFor = count + ":" + liked;
    wantSummary(postId);
  }
}

// ---- who-liked: who liked a post ----
//
// Under every post with likes, one line: "You, Anika, and 10 others liked this
// post". The server decides who is named (the most popular people who liked
// it, and "You" first if you did); the page only puts it into words. The line
// is asked for only when a post's count, or whether you liked it, changes:
// showLike notices, and wantSummary collects every changed post of one second
// into one GET /likesummary. Clicking the line (or the number by the heart)
// opens everyone who liked the post, A to Z, from GET /likers.

// The same limit as MAX_SUMMARY_POSTS in server.py.
const MAX_SUMMARY_POSTS = 100;

// The words of this feature. One sentence is one template, never joined from
// pieces, because another language may put the names in another order. Names
// go in as {first} and {second}. (These move to words.js with the Japanese
// words table.)
const WHO_LIKED_WORDS = {
  liked_you: "You",
  liked_by_one: "{first} liked this post",
  liked_by_two: "{first} and {second} liked this post",
  liked_by_two_and_others_one: "{first}, {second}, and {count} other liked this post",
  liked_by_two_and_others_other: "{first}, {second}, and {count} others liked this post",
  liked_by_one_and_others_one: "{first} and {count} other liked this post",
  liked_by_one_and_others_other: "{first} and {count} others liked this post",
  liked_by_others_one: "{count} person liked this post",
  liked_by_others_other: "{count} people liked this post",
  likers_none: "No likes yet.",
  likers_more_one: "and {count} more",
  likers_more_other: "and {count} more",
  likers_show: "Show who liked this post",
};

// The words for this key, with each {name} replaced by values[name]. It only
// replaces, in one pass: a display name like "{count}" stays as it is typed.
function whoLikedSay(key, values) {
  return WHO_LIKED_WORDS[key].replace(/\{(\w+)\}/g, function (all, name) {
    return String(values[name]);
  });
}

// For words with a number: key_one for 1, key_other for every other number.
function whoLikedSayCount(key, count, values) {
  const form = new Intl.PluralRules("en").select(count) === "one" ? "_one" : "_other";
  return whoLikedSay(key + form, Object.assign({ count: count }, values));
}

// The line and the list, under the heart. Both start hidden.
addPostPart(function whoLikedPart(post, slots) {
  const summary = document.createElement("button");
  summary.type = "button";
  summary.className = "like-summary";
  summary.dataset.action = "likers";
  summary.dataset.postId = post.id;
  summary.setAttribute("aria-expanded", "false");
  summary.setAttribute("aria-controls", "likers-" + post.id);
  summary.hidden = true;

  const list = document.createElement("ul");
  list.className = "likers";
  list.id = "likers-" + post.id;
  list.hidden = true;

  slots.foot.append(summary, list);
  // summaryFor: the count and "liked" the line was last asked for; "" at first.
  return { summary: summary, likersList: list, summaryFor: "" };
});

// The posts whose line must be asked for again, and whether asking is under way.
const summariesWanted = new Set();
let summariesAsking = false;

// Ask for this post's line soon. Every showLike in one pass runs before the
// asking starts, so all the posts that changed in one second go in one request.
function wantSummary(postId) {
  summariesWanted.add(Number(postId));
  if (!summariesAsking) {
    summariesAsking = true;
    setTimeout(askForSummaries, 0);
  }
}

// Ask for every wanted line, at most MAX_SUMMARY_POSTS posts per request, one
// request after the other, so an older answer never arrives after a newer one.
async function askForSummaries() {
  while (summariesWanted.size > 0) {
    const ids = Array.from(summariesWanted).slice(0, MAX_SUMMARY_POSTS);
    for (const id of ids) {
      summariesWanted.delete(id);
    }
    try {
      const response = await fetch("/likesummary?post_ids=" + ids.join(","));
      const answer = await response.json();
      if (!response.ok) {
        throw new Error(answer.error);
      }
      for (const id of ids) {
        const parts = postParts[id];
        if (parts === undefined || answer.summaries[id] === undefined) {
          continue;
        }
        showSummary(parts, answer.summaries[id]);
        // An open list is out of date too: ask for it again.
        if (!parts.likersList.hidden) {
          showLikers(parts.likersList, id);
        }
      }
    } catch (error) {
      // Not answered: forget what was asked, so the next second asks again.
      for (const id of ids) {
        if (postParts[id] !== undefined) {
          postParts[id].summaryFor = "";
        }
      }
    }
  }
  summariesAsking = false;
}

// Write the line: "You, Anika, and 10 others liked this post". The server has
// already chosen the names; here they are only put into one sentence.
function showSummary(parts, summary) {
  const names = [];
  if (summary.you) {
    names.push(whoLikedSay("liked_you"));
  }
  for (const leader of summary.leaders) {
    names.push(leader.display_name);
  }
  const others = Math.max(0, summary.like_count - names.length);
  if (summary.like_count === 0) {
    parts.summary.hidden = true;
    parts.summary.textContent = "";
    return;
  }
  const values = { first: names[0], second: names[1] };
  let words;
  if (names.length === 0) {
    words = whoLikedSayCount("liked_by_others", others, values);
  } else if (names.length === 1) {
    words = others === 0 ? whoLikedSay("liked_by_one", values)
      : whoLikedSayCount("liked_by_one_and_others", others, values);
  } else {
    words = others === 0 ? whoLikedSay("liked_by_two", values)
      : whoLikedSayCount("liked_by_two_and_others", others, values);
  }
  // textContent, never innerHTML: a display name is text a stranger typed.
  parts.summary.textContent = words;
  parts.summary.hidden = false;
}

// Open or close the list of who liked a post. The list is found from the
// button itself, so this works in any list of posts, not only the timeline.
function toggleLikers(postId, button) {
  const post = button.closest(".post");
  const list = post.querySelector(".likers");
  const open = list.hidden;
  list.hidden = !open;
  for (const opener of post.querySelectorAll('[data-action="likers"]')) {
    opener.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (open) {
    showLikers(list, postId);
  }
}

// Ask the server who liked this post, and show them.
async function showLikers(list, postId) {
  try {
    const response = await fetch("/likers?post_id=" + postId);
    const answer = await response.json();
    if (!response.ok) {
      // The server refused, and says why (for example, the post is gone).
      showStatus(answer.error);
      return;
    }
    buildLikers(list, answer);
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// One line for each person: display name, then @account name, A to Z. If
// there are more than the server sends, a last line says how many more.
function buildLikers(list, answer) {
  list.replaceChildren();
  if (answer.likers.length === 0) {
    const row = document.createElement("li");
    row.textContent = whoLikedSay("likers_none");
    list.append(row);
    return;
  }
  for (const liker of answer.likers) {
    const author = document.createElement("span");
    author.className = "post-author";
    author.textContent = liker.display_name;
    const handle = document.createElement("span");
    handle.className = "post-handle";
    handle.textContent = "@" + liker.account_name;
    const row = document.createElement("li");
    row.append(author, handle);
    list.append(row);
  }
  if (answer.like_count > answer.likers.length) {
    const row = document.createElement("li");
    row.className = "likers-more";
    row.textContent = whoLikedSayCount("likers_more", answer.like_count - answer.likers.length);
    list.append(row);
  }
}

ACTIONS.likers = toggleLikers;

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
  if (characterCount(text) > MAX_TEXT) {
    return "The post must be " + MAX_TEXT + " characters or fewer.";
  }
  return "";
}

// How many characters, counted the way the server counts them.
// "😀".length is 2 in JavaScript, but [..."😀"].length is 1, as in Python.
function characterCount(text) {
  return [...text].length;
}

// The live count under the box: "x / MAX_TEXT".
function updateCount() {
  const length = characterCount(textBox.value);
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

// ---- Long posts: Show more / Show less ----
//
// A post taller than 6 lines shows only its first 6 lines (the CSS class
// "collapsed" does this), with a Show more button under them. It is measured
// by height on the page, not by counting characters, because a line break
// starts a new line and a narrow screen fits fewer words on a line.
//
// A height can be measured only when the post is on the page. makePostItem
// builds a post before it is placed, so the text part cannot measure it
// itself. Instead a ResizeObserver (something the browser offers that calls a
// function whenever an element's size changes) watches every post's text. It
// calls checkOverflow when the post first appears on the page, when the
// window is resized, and when a hidden view is shown again.
const textSizeWatcher = new ResizeObserver(function (entries) {
  for (const entry of entries) {
    checkOverflow(entry.target);
  }
});

// Each text gets its own id, so its button can say which text it opens. The
// same post can be in two lists (for example the timeline and search), so the
// id is a counter, not the post id.
let expandableCount = 0;

// Fold this post's text, and put a Show more button right after it. The
// button stays hidden until checkOverflow sees that the text is too tall.
function makeExpandable(textElement, postId) {
  expandableCount = expandableCount + 1;
  textElement.id = "post-text-" + expandableCount;
  textElement.classList.add("collapsed");

  const button = document.createElement("button");
  button.type = "button";
  button.className = "show-more";
  button.dataset.action = "expand";
  button.dataset.postId = postId;
  button.setAttribute("aria-controls", textElement.id);
  button.setAttribute("aria-expanded", "false");
  button.textContent = SHOW_MORE;
  button.hidden = true;
  textElement.after(button);

  textSizeWatcher.observe(textElement);
  return button;
}

// While the text is folded, show its button only if the text really goes on
// past 6 lines (the + 1 allows for rounding). An open post keeps its
// Show less button until the reader closes it.
function checkOverflow(textElement) {
  const button = textElement.nextElementSibling;
  if (button === null || !button.classList.contains("show-more")) {
    return;
  }
  if (textElement.classList.contains("collapsed")) {
    button.hidden = !(textElement.scrollHeight > textElement.clientHeight + 1);
  }
}

// Show more or Show less was pressed: open or fold the text it controls.
function toggleExpanded(postId, button) {
  const textElement = document.getElementById(button.getAttribute("aria-controls"));
  if (textElement === null) {
    return;
  }
  const folded = textElement.classList.toggle("collapsed");
  button.setAttribute("aria-expanded", folded ? "false" : "true");
  button.textContent = folded ? SHOW_MORE : SHOW_LESS;
}

// The part, added after the text part, so the text is already filled in.
// links-and-tags may build the text differently; it still has class post-text.
addPostPart(function expandablePart(post, slots) {
  const textElement = slots.body.querySelector(".post-text");
  if (textElement !== null) {
    makeExpandable(textElement, post.id);
  }
});

ACTIONS.expand = toggleExpanded;

// The server answered 429: too many, too quickly. Turn off the form's button
// for the seconds the server names, then turn it on again. The page does not
// count by itself: it cannot see other windows, so it obeys the server.
function holdForm(form, seconds) {
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  setTimeout(() => {
    button.disabled = false;
  }, seconds * 1000);
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
      if (response.status === 429) holdForm(loginForm, answer.retry_after);
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
      if (response.status === 429) holdForm(signupForm, answer.retry_after);
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
      if (response.status === 429) holdForm(postForm, answer.retry_after);
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

// ---- search: find every post with a word or a #tag ----
//
// The search box is at the top, for everyone, signed in or not. The results
// are shown in their own view, "Search results", newest first, at most
// SEARCH_LIMIT of them. They are a snapshot: they do not update by themselves,
// while the timeline underneath keeps updating every second.
//
// A search has its own address, /?q=… (for example /?q=%23cat), so the
// browser's Back and Forward buttons work, and a link to a search can be
// opened in a new tab.
//
// The contract for links-and-tags: a #tag in a post is a link to
// "/?q=" + encodeURIComponent("#" + tag). A click on it calls
// event.preventDefault() and then searchFor("#" + tag). Which characters make
// a tag is TAG, below; links-and-tags uses it and never makes its own.

// The same rules as the model in server.py, with the same names.
const MAX_QUERY = 100;
const MAX_QUERY_WORDS = 5;
const SEARCH_LIMIT = 50;
// A tag: # and then letters, digits or _, with Japanese counted as letters.
// Exactly the same text as TAG in server.py (a test checks this). It has no
// "g" flag, so it keeps no state between uses; to find every tag in a text,
// make new RegExp(TAG.source, "g").
const TAG = /#([0-9A-Za-z_々぀-ヿ㐀-鿿ｦ-ﾟ]+)/;

// The words of this feature. One sentence is one template, never joined from
// pieces. (These move to words.js with the Japanese words table.)
const SEARCH_WORDS = {
  search_empty: "Type a word to search for.",
  search_too_long: "A search must be {max} characters or fewer.",
  search_too_many_words: "A search may have at most {max} words.",
  results_none: "No posts with “{query}”.",
  results_one: "{count} post with “{query}”.",
  results_other: "{count} posts with “{query}”.",
  results_more: "Showing the newest {count} posts with “{query}”.",
  results_start: "Type a word or #tag in the search box above.",
  results_view: "Search results",
  results_heart: "Open the timeline to like",
};

// The words for this key, with each {name} replaced by values[name], in one pass.
function searchSay(key, values) {
  return SEARCH_WORDS[key].replace(/\{(\w+)\}/g, function (all, name) {
    return String(values[name]);
  });
}

const searchForm = document.getElementById("search-form");
const searchBox = document.getElementById("search-box");
const resultsTitle = document.getElementById("results-title");
const resultsList = document.getElementById("results-list");
const backToTimelineButton = document.getElementById("back-to-timeline");

// The search the results now show ("" if none), and a number for each search,
// so an older answer that arrives late never covers a newer one.
let shownQuery = "";
let searchNumber = 0;

// The rules of check_query in server.py. Returns the broken rule, or "".
// Words are split at spaces, a Japanese full-width space too, as Python does.
function queryProblem(query) {
  const trimmed = query.trim();
  if (trimmed === "") {
    return searchSay("search_empty", {});
  }
  if (characterCount(trimmed) > MAX_QUERY) {
    return searchSay("search_too_long", { max: MAX_QUERY });
  }
  if (trimmed.split(/\s+/).length > MAX_QUERY_WORDS) {
    return searchSay("search_too_many_words", { max: MAX_QUERY_WORDS });
  }
  return "";
}

// The address of a search: /?q=… The # of a tag must be written %23, or the
// browser would read it as the start of a #fragment.
function searchAddress(query) {
  return "/?q=" + encodeURIComponent(query);
}

// Search, and show the results. THE CONTRACT for links-and-tags: call
// searchFor("#cat") to show every post with #cat. It puts the search in the
// box, so the person sees what was searched, and gives it its own address.
function searchFor(query) {
  runSearch(query, true);
}

// Do one search. `remember` is true when the address should change to this
// search (a new entry for the Back button); false when the address already
// says it (the page was opened at /?q=…, or Back or Forward was pressed).
async function runSearch(query, remember) {
  query = query.trim();
  searchBox.value = query;
  // A quick check on the page. The server checks the same rules again.
  const problem = queryProblem(query);
  if (problem !== "") {
    showStatus(problem);
    return;
  }
  if (remember) {
    // The same search again only refreshes it; it is not a second Back step.
    if (location.pathname + location.search === searchAddress(query)) {
      history.replaceState(null, "", searchAddress(query));
    } else {
      history.pushState(null, "", searchAddress(query));
    }
  }
  searchNumber = searchNumber + 1;
  const thisSearch = searchNumber;
  try {
    const response = await fetch("/search?q=" + encodeURIComponent(query));
    const answer = await response.json();
    if (thisSearch !== searchNumber) {
      return;   // a newer search was started while this one was asked
    }
    if (!response.ok) {
      // The server refused the search. It says which rule was broken.
      showStatus(answer.error);
      return;
    }
    showStatus("");
    showResults(query, answer);
  } catch (error) {
    showStatus(CANNOT_REACH);
  }
}

// Fill the results view with the posts the server found, and show it. Each
// post is built by makePostItem, so it looks the same as on the timeline. The
// results are not kept in postParts: only the live timeline is kept up to date.
function showResults(query, answer) {
  shownQuery = query;
  resultsList.replaceChildren();
  for (const post of answer.posts) {
    const parts = makePostItem(post);
    // Liking is done on the timeline, where each heart is kept up to date.
    parts.likeButton.disabled = true;
    parts.likeButton.setAttribute("aria-label", searchSay("results_heart", {}));
    parts.likeButton.setAttribute("title", searchSay("results_heart", {}));
    resultsList.append(parts.item);
  }
  const values = { count: answer.posts.length, query: query };
  let words;
  if (answer.posts.length === 0) {
    words = searchSay("results_none", values);
  } else if (answer.more) {
    words = searchSay("results_more", values);
  } else {
    const form = new Intl.PluralRules("en").select(answer.posts.length) === "one" ? "one" : "other";
    words = searchSay("results_" + form, values);
  }
  // textContent, never innerHTML: the search is text the person typed.
  resultsTitle.textContent = words;
  showView("search");
}

// Back to the timeline: hide the results, empty the search box, and set the
// address back to /. `remember` is false when the address already says /.
function showTimeline(remember) {
  searchBox.value = "";
  showView("timeline");
  if (remember && location.search !== "") {
    history.pushState(null, "", "/");
  }
}

// When the page opens, and when Back or Forward is pressed: do what the
// address says. /?q=cat searches for cat; any other address shows the timeline.
function searchFromAddress() {
  const query = new URLSearchParams(location.search).get("q");
  if (query !== null && query.trim() !== "") {
    runSearch(query, false);
  } else {
    showTimeline(false);
  }
}

// A view button was pressed (in <nav id="views">): keep the address in step.
// The results view has the address of the search it shows; every other view is /.
function viewChosen(event) {
  const button = event.target.closest("[data-show-view]");
  if (button === null) {
    return;
  }
  if (button.dataset.showView === "search" && shownQuery !== "") {
    if (location.pathname + location.search !== searchAddress(shownQuery)) {
      history.pushState(null, "", searchAddress(shownQuery));
    }
    searchBox.value = shownQuery;
  } else if (button.dataset.showView !== "search") {
    showTimeline(true);
    showView(button.dataset.showView);
  }
}

// The search form was sent.
function searchSubmitted(event) {
  event.preventDefault();
  searchFor(searchBox.value);
}

// Escape in the search box goes back to the timeline, when results are shown.
function searchBoxKey(event) {
  if (event.key === "Escape" && location.search !== "") {
    showTimeline(true);
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
addView("timeline", "Timeline");
showView("timeline");
// search: its own view, and its own listeners. The results list uses the
// same click handler as the timeline, so who-liked and Show more work there.
addView("search", searchSay("results_view", {}));
resultsTitle.textContent = searchSay("results_start", {});
resultsList.addEventListener("click", clickOnTimeline);
searchForm.addEventListener("submit", searchSubmitted);
searchBox.addEventListener("keydown", searchBoxKey);
backToTimelineButton.addEventListener("click", function () {
  showTimeline(true);
});
viewsNav.addEventListener("click", viewChosen);
window.addEventListener("popstate", searchFromAddress);
searchFromAddress();
updateCount();
askWhoIAm();
keepChecking();
setInterval(refreshTimes, 30000);   // every 30 seconds: the smallest step shown is a minute
