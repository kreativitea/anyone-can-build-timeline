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
const MAX_PLACE = 40;
// pictures: the same as MAX_PICTURE_BYTES, MAX_PICTURE_MB, MAX_ALT_TEXT and
// PICTURE_TYPES in server.py.
const MAX_PICTURE_BYTES = 2097152;   // 2 MB: 2 x 1024 x 1024 bytes
const MAX_PICTURE_MB = 2;
const MAX_ALT_TEXT = 200;
const PICTURE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
// The account name rule, the same as ACCOUNT_NAME in server.py.
const ACCOUNT_NAME = /^[A-Za-z0-9_]+$/;
// links-and-tags: the same patterns as LINK, LINK_START, LINK_END and NAME in
// server.py, as exactly the same text (a test checks this; a regular
// expression here writes \/ for /). A #tag uses TAG, in the search part below.
// A web link: http:// or https://, then only the characters a web address may hold.
const LINK = /https?:\/\/[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+/;
// After its end is cut, a link must still have a letter or digit after ://.
const LINK_START = /^https?:\/\/[A-Za-z0-9]/;
// Cut from the end of a link, one at a time. ) and ] are cut by trimLinkEnd.
const LINK_END = ".,:;!?*'";
// An @name: @ and then 1 to MAX_AUTHOR of the ACCOUNT_NAME characters, not
// just after a letter, digit or _ (so aiko@mail.com is not a name).
const NAME = /(?<![A-Za-z0-9_])@[A-Za-z0-9_]{1,40}(?![A-Za-z0-9_])/;
// The characters a display name may not hold, the same as HIDDEN_CHARACTERS in server.py.
const HIDDEN_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u2028-\u202e\u2066-\u2069]/;

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
const placeBox = document.getElementById("place");
// replies: the "Replying to @aiko · Cancel" line above the post box.
const replyingToLine = document.getElementById("replying-to");
const replyingToWords = document.getElementById("replying-to-words");
const cancelReplyButton = document.getElementById("cancel-reply");

// The key for the Colours choice in localStorage. The same key as the small
// script in index.html, which uses it before the page is drawn.
const THEME_KEY = "timeline-theme";
const themeSwitch = document.getElementById("theme");
const languageButton = document.getElementById("language");

// ---- Words and languages ----
//
// Every word the page shows is in words.js (WORDS), by key, in each language.
// The page never writes a sentence of its own: it asks say("key"). The server
// never translates either: a refusal comes with a code, and the page shows the
// words for that code (showProblem). People's own words (posts, names) are
// never keys: they are shown exactly as they were written.

// The language now shown: "en" or "ja".
let language = "en";

// The key for the language choice in localStorage.
const LANGUAGE_KEY = "language";

// Values that words in index.html need. The sign-up form says
// "Password (8 characters or more)": the 8 is {min}.
const PAGE_VALUES = { min: MIN_PASSWORD, size: MAX_PICTURE_MB };

// What the status line says now, so it can be written again in another language.
let statusNow = { key: "", values: {}, fallback: "" };

// Does words.js have this language yet? (Japanese comes in japanese Part B.)
function hasWordsIn(lang) {
  return WORDS.app_name[lang] !== undefined;
}

// The language to start with: the one chosen on this browser before, if any.
// Otherwise the browser's own first language: Japanese if it starts with "ja",
// English for everything else.
function chooseLanguage() {
  try {
    const saved = localStorage.getItem(LANGUAGE_KEY);
    if ((saved === "en" || saved === "ja") && hasWordsIn(saved)) {
      return saved;
    }
  } catch (error) {
    // Storage is blocked: nothing was saved. Use the browser's language.
  }
  const first = (navigator.languages && navigator.languages[0]) || navigator.language || "";
  if (first.toLowerCase().startsWith("ja") && hasWordsIn("ja")) {
    return "ja";
  }
  return "en";
}

// Put each value into its {name} in the template. It only replaces: a value
// is never read as a template, so a value cannot add words of its own.
function fill(template, values) {
  return template.replace(/\{(\w+)\}/g, function (whole, name) {
    if (values && values[name] !== undefined) {
      return String(values[name]);
    }
    return whole;
  });
}

// "_one" or "_other": which of two keys fits this number, in the language
// now shown. The browser's own Intl.PluralRules decides. Japanese has no
// plural, so it always gives "_other".
function pluralEnding(n) {
  return new Intl.PluralRules(language).select(n) === "one" ? "_one" : "_other";
}

// The entry in words.js for this key. A key with a number may be written
// without its ending (a server code such as "post_too_fast"): then the value
// `count` picks key_one or key_other. undefined if there is none.
function wordsEntry(key, values) {
  if (WORDS[key] !== undefined) {
    return WORDS[key];
  }
  if (values && values.count !== undefined) {
    return WORDS[key + pluralEnding(values.count)];
  }
  return undefined;
}

// The words for this key, in the language now shown, with the values filled
// in. If there are no words in this language yet, the English.
function say(key, values) {
  const entry = wordsEntry(key, values);
  if (entry === undefined) {
    return key;   // a mistake in the code: test_server.py checks every key
  }
  const template = entry[language] !== undefined ? entry[language] : entry.en;
  return fill(template, values);
}

// Words with a number, such as "1 new post" and "3 new posts": two keys,
// key_one and key_other. The browser's own Intl.PluralRules picks one.
// Japanese has no plural, so it always picks key_other. The number is the
// value {count}. `values` (optional) are more values for the same sentence,
// for example names: "{first} and {count} others liked this".
function sayCount(key, n, values) {
  return say(key + pluralEnding(n), Object.assign({}, values, { count: n }));
}

// Write every word on the page in the language now shown: each element with
// data-words (its text), data-words-placeholder or data-words-aria-label (that
// attribute), then the status line.
function showWords() {
  for (const element of document.querySelectorAll("[data-words]")) {
    element.textContent = say(element.dataset.words, PAGE_VALUES);
  }
  for (const element of document.querySelectorAll("[data-words-placeholder]")) {
    element.placeholder = say(element.dataset.wordsPlaceholder, PAGE_VALUES);
  }
  for (const element of document.querySelectorAll("[data-words-aria-label]")) {
    element.setAttribute("aria-label", say(element.dataset.wordsAriaLabel, PAGE_VALUES));
  }
  for (const element of document.querySelectorAll("[data-words-title]")) {
    element.setAttribute("title", say(element.dataset.wordsTitle, PAGE_VALUES));
  }
  // A screen reader picks its voice by lang, and the browser picks the shape
  // of each kanji by it. The language button is always in the other language.
  document.documentElement.lang = language;
  languageButton.lang = language === "ja" ? "en" : "ja";
  showStatus(statusNow.key, statusNow.values, statusNow.fallback);
  // Words with values of their own (a time, a count, names) are written
  // again by the feature that made them.
  for (const redraw of WORDS_REDRAWN) {
    redraw();
  }
}

// Functions that write their own words again after a language change, for
// words that data-words cannot hold (they have values, such as a time or a
// count). A feature adds one with whenLanguageChanges(itsFunction).
const WORDS_REDRAWN = [];

function whenLanguageChanges(redraw) {
  WORDS_REDRAWN.push(redraw);
}

// Show the page in this language, and remember the choice in this browser.
function setLanguage(newLanguage) {
  try {
    localStorage.setItem(LANGUAGE_KEY, newLanguage);
  } catch (error) {
    // Storage is blocked: the words still change in this tab, but are not remembered.
  }
  language = newLanguage;
  showWords();
}

// Show the server's refusal. Its code names the rule, so the words come from
// words.js, in the reader's language. A code this page does not know (an older
// page, a newer server) shows the server's English instead, which is still true.
function showProblem(answer) {
  showStatus(answer.code, answer.values, answer.error);
}

// The id of the newest post this window has received, shown or still waiting
// behind the "new posts" button (timeline-flow). It must count the waiting ones
// too, or the same posts would come back every second. 0 means "none yet".
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
  // components.css), so the post looks the same as when the parts sat in it directly.
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
  menu.className = "post-menu menu";
  menu.hidden = true;
  const summary = document.createElement("summary");
  summary.dataset.wordsAriaLabel = "post_menu_label";
  summary.setAttribute("aria-label", say("post_menu_label"));
  summary.textContent = "\u22ef";
  const list = document.createElement("ul");
  menu.append(summary, list);
  return menu;
}

// Add one button to a post's "⋯" menu. `action` is a name in ACTIONS, and
// `key` names its words in words.js.
function addMenuItem(slots, action, key) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button-link";
  button.dataset.action = action;
  button.dataset.postId = slots.menu.closest(".post").dataset.postId;
  button.dataset.words = key;
  button.textContent = say(key);
  const row = document.createElement("li");
  row.append(button);
  slots.menu.querySelector("ul").append(row);
  slots.menu.hidden = false;
  return button;
}

// Put a built post on the page. "top": first in the timeline, so the newest
// is always first. "bottom": last in the timeline. "under-parent": a reply,
// under the post it answers (replies). A reply whose post is on the timeline
// always goes there, wherever it was asked to go.
function placePost(item, post, where) {
  if (hasParentOnTimeline(post)) {
    where = "under-parent";
  } else if (where === "under-parent") {
    where = "top";   // its post is not on this page: show it like a new post
  }
  if (where === "top") {
    timeline.prepend(item);
  } else if (where === "bottom") {
    timeline.append(item);
  } else if (where === "under-parent") {
    placeUnderParent(item, post);
  } else {
    throw new Error("placePost does not know where '" + where + "' is.");
  }
  adoptReplies(post);   // replies that arrived before their post move under it
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
  stopWatchingText(parts.item);       // edit-delete: long-posts stops watching its text
  parts.item.remove();
  removeReplyThread(postId, parts);   // replies: its replies go with it
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
  stopWatchingText(old.item);   // edit-delete: the old text leaves the page
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
// it in the reader's own time zone, in the language the page is shown in
// (`language`), with the browser's own Intl: never with words of its own.
// The order of the timeline never uses the time, only the post id.

// How long ago `moment` was, seen from `now`. Both are Date values.
function timeAgo(moment, now) {
  const seconds = Math.floor((now - moment) / 1000);
  // Under a minute, or in the future: the reader's clock may be a little
  // ahead of or behind the server's, and a new post must never say "in 3 seconds".
  if (seconds < 60) {
    return say("time_just_now");
  }
  const words = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
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
  return moment.toLocaleDateString(language, how);
}

// The full date and time, in the reader's time zone, for the tooltip.
function fullLocalTime(moment) {
  return moment.toLocaleString(language, { dateStyle: "full", timeStyle: "medium" });
}

// One time on the page. Other features reuse this: with a full time it makes
// <time datetime="..." title="..." data-relative>, and refreshTimes keeps its
// words up to date. A post from before Timeline kept dates has only its old
// clock time, so it says so instead of guessing a date.
function timeElement(postedAt, oldClockTime) {
  if (!postedAt) {
    const unknown = document.createElement("span");
    unknown.className = "post-time post-time-unknown";
    unknown.dataset.wordsTitle = "time_before_dates";
    unknown.setAttribute("title", say("time_before_dates"));
    unknown.dataset.clockTime = oldClockTime;
    unknown.textContent = say("time_date_unknown", { time: oldClockTime });
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

// After a language change: every time again, with its tooltip, and every
// "date unknown".
whenLanguageChanges(function redrawTimes() {
  refreshTimes();
  for (const time of document.querySelectorAll("time[data-relative]")) {
    time.setAttribute("title", fullLocalTime(new Date(time.getAttribute("datetime"))));
  }
  for (const unknown of document.querySelectorAll(".post-time-unknown")) {
    unknown.textContent = say("time_date_unknown", { time: unknown.dataset.clockTime });
  }
});

// What it says.
addPostPart(function textPart(post, slots) {
  const text = document.createElement("p");
  text.className = "post-text";
  showPostText(text, post.text);
  slots.body.append(text);
});

// ---- links-and-tags: web links, #tags and @names you can click ----
//
// A post's text is cut into pieces: plain words, links, tags and names. Each
// piece is built by hand: words as a text node, the others as an <a> element.
// Never innerHTML: a post is always shown as words, so it cannot run code.
// postTextPieces and trimLinkEnd are twins of post_text_pieces and
// trim_link_end in server.py, line for line; the tests check those with a
// table of examples (EXAMPLES in test_server.py). Change both, or neither.

// Put a post's text into an element, with its links, tags and names clickable.
function showPostText(element, text) {
  for (const piece of postTextPieces(text)) {
    element.append(pieceElement(piece));
  }
}

// The link without the punctuation at its end. A ) is cut only if the link
// has more ) than (, so .../wiki/Kyoto_(city) keeps its ). The same for ].
function trimLinkEnd(link) {
  while (link !== "") {
    const last = link[link.length - 1];
    if (LINK_END.includes(last)) {
      link = link.slice(0, -1);
    } else if (last === ")" && countOf(link, ")") > countOf(link, "(")) {
      link = link.slice(0, -1);
    } else if (last === "]" && countOf(link, "]") > countOf(link, "[")) {
      link = link.slice(0, -1);
    } else {
      break;
    }
  }
  return link;
}

// How many times one character is in a text.
function countOf(text, character) {
  return text.split(character).length - 1;
}

// A post's text, cut into pieces: [{kind, text}, ...]. kind is "text",
// "link", "tag" or "name". Joined together, the pieces are the whole text.
function postTextPieces(text) {
  const pieces = [];
  function add(kind, words) {
    if (words === "") {
      return;
    }
    if (kind === "text" && pieces.length > 0 && pieces[pieces.length - 1].kind === "text") {
      pieces[pieces.length - 1].text += words;
    } else {
      pieces.push({ kind: kind, text: words });
    }
  }
  // All three patterns, tried together, left to right. A new RegExp each
  // time, because a "g" pattern remembers where it stopped.
  const piece = new RegExp(
    "(?:" + LINK.source + ")|(?:" + TAG.source + ")|(?:" + NAME.source + ")", "g");
  let at = 0;
  for (const found of text.matchAll(piece)) {
    let words = found[0];
    let tail = "";
    let kind;
    if (words.startsWith("#")) {
      kind = "tag";
    } else if (words.startsWith("@")) {
      kind = "name";
    } else {
      kind = "link";
      const link = trimLinkEnd(words);
      tail = words.slice(link.length);
      words = link;
      if (!LINK_START.test(words)) {
        kind = "text";   // nothing left that can be a link: it stays words
      }
    }
    add("text", text.slice(at, found.index));
    add(kind, words);
    add("text", tail);
    at = found.index + found[0].length;
  }
  add("text", text.slice(at));
  return pieces;
}

// One piece, as something to put on the page.
function pieceElement(piece) {
  if (piece.kind === "link") {
    return linkElement(piece.text);
  }
  if (piece.kind === "tag") {
    return searchElement(piece.text, "post-tag");
  }
  if (piece.kind === "name") {
    return searchElement(piece.text, "post-name");
  }
  return document.createTextNode(piece.text);
}

// A web link that opens in a new tab. Only http: and https: ever become a
// link: the pattern already says so, and new URL checks it a second time.
// noopener: the other website cannot control this tab. noreferrer: it does
// not learn the address it came from. The words are the address as typed.
function linkElement(address) {
  let url;
  try {
    url = new URL(address);
  } catch (error) {
    return document.createTextNode(address);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return document.createTextNode(address);
  }
  const link = document.createElement("a");
  link.className = "post-link";
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = address;
  return link;
}

// A #tag or an @name: a link to a search for it, /?q=%23kyoto. A plain click
// searches in this tab without loading the page again (searchFor). A click
// with Ctrl, Cmd, Shift or the middle button is left to the browser, so the
// search opens in a new tab, where searchFromAddress runs it.
function searchElement(words, className) {
  const link = document.createElement("a");
  link.className = className;
  link.href = searchAddress(words);
  link.textContent = words;
  link.addEventListener("click", function (event) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    searchFor(words);
  });
  return link;
}

// The heart, and how many people have pressed it. The button says what it
// does (data-action="like") and carries its own post id, so one click handler
// on the timeline can serve every post.
addPostPart(function heartPart(post, slots) {
  const likeRow = document.createElement("div");
  likeRow.className = "like-row";

  const likeButton = document.createElement("button");
  likeButton.type = "button";
  likeButton.className = "like button-pill";
  likeButton.dataset.action = "like";
  likeButton.dataset.postId = post.id;
  likeButton.setAttribute("aria-pressed", "false");
  likeButton.textContent = "\u2665";

  // The count is a button too: it opens the list of who liked the post (who-liked).
  const likeCount = document.createElement("button");
  likeCount.type = "button";
  likeCount.className = "like-count button-quiet";
  likeCount.dataset.action = "likers";
  likeCount.dataset.postId = post.id;
  likeCount.setAttribute("aria-expanded", "false");
  likeCount.setAttribute("aria-controls", "likers-" + post.id);
  likeCount.dataset.wordsAriaLabel = "likers_show";
  likeCount.setAttribute("aria-label", say("likers_show"));
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
  // data-words-aria-label lets showWords write it again in another language.
  parts.likeButton.dataset.wordsAriaLabel = liked ? "unlike_label" : "like_label";
  parts.likeButton.setAttribute("aria-label", say(parts.likeButton.dataset.wordsAriaLabel));
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

// The words of this feature are in words.js (liked_..., likers_...). One
// sentence is one key, never joined from pieces, because another language may
// put the names in another order. Names go in as {first} and {second}; say()
// fills them in one pass, so a display name like "{count}" stays as it is typed.

// The line and the list, under the heart. Both start hidden.
addPostPart(function whoLikedPart(post, slots) {
  const summary = document.createElement("button");
  summary.type = "button";
  summary.className = "like-summary button-quiet";
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
        throw new Error(answer.code);
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
  parts.lastSummary = summary;   // kept, to write it again after a language change
  const names = [];
  if (summary.you) {
    names.push(say("liked_you"));
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
    words = sayCount("liked_by_others", others, values);
  } else if (names.length === 1) {
    words = others === 0 ? say("liked_by_one", values)
      : sayCount("liked_by_one_and_others", others, values);
  } else {
    words = others === 0 ? say("liked_by_two", values)
      : sayCount("liked_by_two_and_others", others, values);
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
      // The server refused, and its code says why (for example, the post is gone).
      showProblem(answer);
      return;
    }
    buildLikers(list, answer);
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// One line for each person: display name, then @account name, A to Z. If
// there are more than the server sends, a last line says how many more.
function buildLikers(list, answer) {
  list.replaceChildren();
  if (answer.likers.length === 0) {
    const row = document.createElement("li");
    row.dataset.words = "likers_none";
    row.textContent = say("likers_none");
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
    row.textContent = sayCount("likers_more", answer.like_count - answer.likers.length);
    list.append(row);
  }
}

ACTIONS.likers = toggleLikers;

// After a language change: every line again, and every open list.
whenLanguageChanges(function redrawWhoLiked() {
  for (const postId in postParts) {
    const parts = postParts[postId];
    if (parts.lastSummary !== undefined) {
      showSummary(parts, parts.lastSummary);
    }
    if (!parts.likersList.hidden) {
      showLikers(parts.likersList, Number(postId));
    }
  }
});

// Write one message in the status line: the words for `key`, with `values`
// filled in. `fallback` is used only if words.js has no such key (the server's
// own English, from showProblem). showStatus("") empties the line.
function showStatus(key, values, fallback) {
  statusNow = { key: key, values: values || {}, fallback: fallback || "" };
  if (wordsEntry(key, values) !== undefined) {
    statusLine.textContent = say(key, values);
  } else {
    statusLine.textContent = fallback || "";
  }
}

// Logged in: show who, and the post form. Hide the two account forms.
function showSignedIn(who) {
  account = who;
  whoDisplayName.textContent = who.display_name;
  whoAccountName.textContent = "@" + who.account_name;
  signedOutSection.hidden = true;
  signedInSection.hidden = false;
  showDraft(who);
  loadBookmarks();
  loadBlocked();
  askEmailSettings();   // reply-email
}

// Not logged in: show the Log in and Sign up forms, and why, if there is a
// reason (a key in words.js, or "" for none).
// The post box is emptied too, so the next person to log in on this computer
// does not see the last person's unsent words.
function showSignedOut(reason) {
  account = null;
  signedInSection.hidden = true;
  signedOutSection.hidden = false;
  hideDraft();
  clearBookmarks();
  clearPictureBoxes();
  showBlocked([]);
  showEmailSettings(null);   // reply-email: never show the last person's address
  showStatus(reason);
}

// The rules for a new account, the same as check_name, check_display_name and
// check_password in server.py, with the same codes as the server.
// Returns the broken rule as { key, values }, or null if none.
function accountProblem(name, displayName, password) {
  if (name === "") {
    return { key: "name_empty", values: {} };
  }
  if (name.length > MAX_AUTHOR) {
    return { key: "name_too_long", values: { limit: MAX_AUTHOR } };
  }
  if (!ACCOUNT_NAME.test(name)) {
    return { key: "name_characters", values: {} };
  }
  if (displayName.length > MAX_DISPLAY_NAME) {
    return { key: "display_name_too_long", values: { limit: MAX_DISPLAY_NAME } };
  }
  if (HIDDEN_CHARACTERS.test(displayName)) {
    return { key: "display_name_hidden", values: {} };
  }
  // A password is never trimmed: a space is part of it.
  if (password.length < MIN_PASSWORD) {
    return { key: "password_too_short", values: { limit: MIN_PASSWORD } };
  }
  if (password.length > MAX_PASSWORD) {
    return { key: "password_too_long", values: { limit: MAX_PASSWORD } };
  }
  return null;
}

// The rules for a post, the same as check_text in server.py, with the same codes.
// Returns the broken rule as { key, values }, or null if none.
function textProblem(text) {
  if (text === "") {
    return { key: "text_empty", values: {} };
  }
  if (characterCount(text) > MAX_TEXT) {
    return { key: "text_too_long", values: { limit: MAX_TEXT } };
  }
  return null;
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

// This account's draft, as { text, replyTo }. text is "" and replyTo is null
// if there is none, or storage is blocked.
function loadDraft(who) {
  let kept = "";
  try {
    kept = localStorage.getItem(draftKey(who)) || "";
  } catch (error) {
    kept = "";
  }
  return readDraft(kept);
}

// replies: a draft also remembers the post it answers. It is kept as JSON
// text: {"v": 2, "text": "...", "reply_to": {"id": 7, "author": "aiko"}}
// (reply_to is null for a normal post). A draft kept before replies is just
// the words themselves, so anything else is read as plain words.
function readDraft(kept) {
  try {
    const found = JSON.parse(kept);
    if (found !== null && typeof found === "object" && found.v === 2
        && typeof found.text === "string") {
      const to = found.reply_to;
      const replyTo = to && Number.isInteger(to.id) && typeof to.author === "string"
        ? { id: to.id, author: to.author } : null;
      return { text: found.text, replyTo: replyTo };
    }
  } catch (error) {
    // Not JSON: a draft from before replies.
  }
  return { text: kept, replyTo: null };
}

// Keep what is in the box now, and the post it answers, for the person
// logged in. An empty box (or only spaces) that is not a reply removes the
// draft instead. A draft over the limit is still kept: the person may be
// cutting it down.
function saveDraft() {
  if (account === null) {
    return;
  }
  try {
    if (textBox.value.trim() === "" && replyingTo === null) {
      localStorage.removeItem(draftKey(account));
    } else {
      const kept = { v: 2, text: textBox.value, reply_to: replyingTo };
      localStorage.setItem(draftKey(account), JSON.stringify(kept));
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
  textBox.value = draft.text;
  updateCount();
  // replies: "Replying to @aiko" comes back too.
  if (draft.replyTo !== null) {
    showReplyingTo(draft.replyTo);
  } else {
    stopReplying();
  }
  if (draft.text !== "" || draft.replyTo !== null) {
    showStatus("draft_back");
  }
}

// Empty the box while nobody is logged in. The draft stays in storage.
function hideDraft() {
  textBox.value = "";
  stopReplying();
  updateCount();
}

// ---- Place: where a post was written, typed by the writer ----
//
// Optional. The writer types any short words ("Osaka", "home") or nothing.
// The browser never looks up where the device is. Everyone can see a place,
// so the box's label says so.
//
// The last place typed is kept in this browser's localStorage, under one key,
// so it is not typed again for every post. It never goes to the server until
// it is part of a post, and it is forgotten on Log out, so the next person on
// a shared computer does not see it. Storage can be blocked: then every use
// of it is caught, and the page simply does not remember.

const PLACE_KEY = "timeline-place";

// The rules for a place, the same as check_place in server.py, with the same
// codes. An empty place is fine: it means "no place".
// Returns the broken rule as { key, values }, or null if none.
function placeProblem(place) {
  if (characterCount(place) > MAX_PLACE) {
    return { key: "place_too_long", values: { limit: MAX_PLACE } };
  }
  if (HIDDEN_CHARACTERS.test(place)) {
    return { key: "place_hidden", values: {} };
  }
  return null;
}

// The place after the time: "· Osaka". A post with no place shows nothing.
// textContent, never innerHTML: a place is shown as words, so it cannot run code.
addPostPart(function placePart(post, slots) {
  if (!post.place) {
    return;
  }
  const place = document.createElement("span");
  place.className = "post-place";
  // The place itself is what a person wrote, so it is never a key: only the
  // "· {place}" around it is. It is kept, to be written again in another language.
  place.dataset.place = post.place;
  place.textContent = say("post_place", { place: post.place });
  slots.head.append(place);
});

// After a language change: every "· Osaka" again.
whenLanguageChanges(function redrawPlaces() {
  for (const place of document.querySelectorAll(".post-place")) {
    place.textContent = say("post_place", { place: place.dataset.place });
  }
});

// Keep the place, for the next post. An empty place removes the key.
function rememberPlace(place) {
  try {
    if (place === "") {
      localStorage.removeItem(PLACE_KEY);
    } else {
      localStorage.setItem(PLACE_KEY, place);
    }
  } catch (error) {
    // Storage is blocked or full. The place is not kept; nothing else changes.
  }
}

// The last place kept in this browser, or "" if there is none or storage is blocked.
function rememberedPlace() {
  try {
    return localStorage.getItem(PLACE_KEY) || "";
  } catch (error) {
    return "";
  }
}

// Forget the place, and empty the box (on Log out).
function forgetPlace() {
  placeBox.value = "";
  try {
    localStorage.removeItem(PLACE_KEY);
  } catch (error) {
    // Storage is blocked, so there is no place to remove.
  }
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
  button.className = "show-more button-link";
  button.dataset.action = "expand";
  button.dataset.postId = postId;
  button.setAttribute("aria-controls", textElement.id);
  button.setAttribute("aria-expanded", "false");
  button.dataset.words = "show_more";
  button.textContent = say("show_more");
  button.hidden = true;
  textElement.after(button);

  textSizeWatcher.observe(textElement);
  return button;
}

// A post leaves the page (removePost) or is built again (redrawPost): stop
// watching the size of its old text, so the watcher does not keep it forever.
function stopWatchingText(item) {
  for (const watched of item.querySelectorAll(".post-text")) {
    textSizeWatcher.unobserve(watched);
  }
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
  button.dataset.words = folded ? "show_more" : "show_less";
  button.textContent = say(button.dataset.words);
}

// The part, added after the text part, so the text is already filled in.
// links-and-tags builds the text with showPostText; it still has class post-text.
addPostPart(function expandablePart(post, slots) {
  const textElement = slots.body.querySelector(".post-text");
  if (textElement !== null) {
    makeExpandable(textElement, post.id);
  }
});

ACTIONS.expand = toggleExpanded;

// ---- replies: a post that answers another post ----
//
// A reply is a post with a parent_id: the id of the post it answers. Only one
// level: only a post that is not a reply has a Reply button. A reply sits
// under its post, oldest reply first, so it reads like a conversation. It
// says "Replying to @aiko", and has a heart like any post.
//
// The replies of a post are kept in their own <li class="reply-thread"> just
// after the post, not inside it. So when a post is built again (redrawPost),
// its replies stay where they are. When a post is taken off the page
// (removePost), its thread goes too.
//
// Older pages come newest first (timeline-flow), so a reply can arrive before
// its post. It is shown on its own until its post arrives, then moves under
// it (adoptReplies).
//
// The number of replies comes from the server (reply_count), counted from
// the rows the reader may see, like the like count. The server also says
// which was the newest reply it counted (newest_reply_id). A reply that
// arrives later, with a larger id, was not counted yet, so the page adds one
// for it. The page never counts the replies it shows: some may not be loaded.
//
// You write a reply in the main post box. Reply puts "Replying to @aiko ·
// Cancel" above the box. The words are in words.js (reply_..., replying_to,
// replies_label).

// The post this window is writing a reply to: { id, author }, or null.
let replyingTo = null;

// For each post on the timeline whose replies are shown: the <ol> they are in.
const replyLists = {};

// Is this post a reply?
function isReply(post) {
  return post.parent_id !== null && post.parent_id !== undefined;
}

// Is this post a reply whose post is on the live timeline?
function hasParentOnTimeline(post) {
  return isReply(post) && postParts[post.parent_id] !== undefined;
}

// A reply says which post it answers: "Replying to @aiko", above its text.
// A post that is not a reply gets a Reply button and its reply count, beside the heart.
addPostPart(function replyPart(post, slots) {
  if (isReply(post)) {
    const line = document.createElement("p");
    line.className = "replying-to";
    line.dataset.parentAuthor = post.parent_author;
    line.textContent = say("replying_to", { name: post.parent_author });
    slots.body.prepend(line);
    return { parentId: post.parent_id };
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button-link reply-button";
  button.dataset.action = "reply";
  button.dataset.postId = post.id;
  button.dataset.author = post.author;
  button.dataset.words = "reply_button";
  button.textContent = say("reply_button");
  button.setAttribute("aria-label", say("reply_button_label", { name: post.author }));

  const count = document.createElement("span");
  count.className = "reply-count count";
  writeReplyCount(count, post.reply_count || 0);

  // Beside the heart, if there is one.
  const row = slots.foot.querySelector(".like-row") || slots.foot;
  row.append(button, count);
  return {
    replyCount: count,
    replyTotal: post.reply_count || 0,
    newestReplyId: post.newest_reply_id || 0,
  };
});

// Write "2 replies" into the count. Nothing is shown for 0.
function writeReplyCount(element, count) {
  element.dataset.count = count;
  element.textContent = count > 0 ? sayCount("reply_count", count) : "";
  element.hidden = count === 0;
}

// Show a post's reply count as it is now.
function showReplyCount(postId) {
  const parts = postParts[postId];
  if (parts === undefined || parts.replyCount === undefined) {
    return;
  }
  writeReplyCount(parts.replyCount, parts.replyTotal);
}

// Put a reply under its post, among the replies already there, oldest first.
// The list of replies is made the first time it is needed, just after the post.
function placeUnderParent(item, post) {
  const parent = postParts[post.parent_id];
  let list = replyLists[post.parent_id];
  if (list === undefined || !list.isConnected) {
    const thread = document.createElement("li");
    thread.className = "reply-thread";
    list = document.createElement("ol");
    list.className = "replies";
    list.dataset.parentAuthor = post.parent_author;
    list.setAttribute("aria-label", say("replies_label", { name: post.parent_author }));
    thread.append(list);
    parent.item.after(thread);
    replyLists[post.parent_id] = list;
  }
  // Before the first reply with a larger id, so the oldest stays first.
  const later = Array.from(list.children).find(function (other) {
    return Number(other.dataset.postId) > post.id;
  });
  list.insertBefore(item, later || null);
  // A reply newer than the newest one the server counted is new: add one.
  if (parent.newestReplyId !== undefined && post.id > parent.newestReplyId) {
    parent.newestReplyId = post.id;
    parent.replyTotal = parent.replyTotal + 1;
    showReplyCount(post.parent_id);
  }
}

// A post was just put on the page. Any of its replies already shown on their
// own (they came in an older page first) move under it. They are already in
// its reply count, so nothing is added.
function adoptReplies(post) {
  if (isReply(post)) {
    return;
  }
  for (const id of Object.keys(postParts)) {
    const parts = postParts[id];
    if (parts.parentId === post.id && !parts.item.parentElement.classList.contains("replies")) {
      placeUnderParent(parts.item, {
        id: Number(id), parent_id: post.id, parent_author: post.author,
      });
    }
  }
}

// removePost took a post off the page. If it had replies under it, they go
// too. If it was the last reply in a list, the empty list goes.
function removeReplyThread(postId, parts) {
  const list = replyLists[postId];
  if (list !== undefined) {
    for (const item of list.querySelectorAll("li.post")) {
      delete postParts[item.dataset.postId];
    }
    list.closest(".reply-thread").remove();
    delete replyLists[postId];
  }
  const parentList = replyLists[parts.parentId];
  if (parentList !== undefined && parentList.children.length === 0) {
    parentList.closest(".reply-thread").remove();
    delete replyLists[parts.parentId];
  }
}

// Does this waiting post count in "3 new posts"? Not a reply that will go
// under a post already on the page, or under a post that is waiting too.
function countsAsNewPost(post) {
  if (!isReply(post)) {
    return true;
  }
  return !hasParentOnTimeline(post)
    && !waitingPosts.some(function (other) { return other.id === post.parent_id; });
}

// Show "Replying to @aiko · Cancel" above the box, and remember which post.
function showReplyingTo(target) {
  replyingTo = { id: target.id, author: target.author };
  replyingToWords.textContent = say("replying_to", { name: target.author });
  replyingToLine.hidden = false;
}

// Stop writing a reply: the next post is a normal post again.
function stopReplying() {
  replyingTo = null;
  replyingToWords.textContent = "";
  replyingToLine.hidden = true;
}

// Reply was pressed. The server checks again that this post may be answered.
function startReply(postId, button) {
  if (account === null) {
    showStatus("reply_log_in");
    return;
  }
  showReplyingTo({ id: postId, author: button.dataset.author });
  saveDraft();   // the draft remembers which post it answers
  textBox.scrollIntoView({ block: "center" });
  textBox.focus();
}

// Cancel was pressed: keep the words, but they are no longer a reply.
function cancelReply() {
  stopReplying();
  saveDraft();
  textBox.focus();
}

ACTIONS.reply = startReply;

// The words with values of their own, again in the language now shown.
whenLanguageChanges(function redrawReplyWords() {
  for (const line of document.querySelectorAll(".replying-to")) {
    line.textContent = say("replying_to", { name: line.dataset.parentAuthor });
  }
  for (const button of document.querySelectorAll(".reply-button")) {
    button.setAttribute("aria-label", say("reply_button_label", { name: button.dataset.author }));
  }
  for (const count of document.querySelectorAll(".reply-count")) {
    writeReplyCount(count, Number(count.dataset.count));
  }
  for (const list of document.querySelectorAll(".replies")) {
    list.setAttribute("aria-label", say("replies_label", { name: list.dataset.parentAuthor }));
  }
  if (replyingTo !== null) {
    showReplyingTo(replyingTo);
  }
});

// ---- pictures: one picture on a post, with a description ----
//
// A post may carry one PNG, JPEG, GIF or WebP picture, up to 2 MB, and a
// description of it for people who cannot see it (the "alt text" a screen
// reader says instead of the picture). The picture travels inside the JSON of
// POST /posts, written as base64 (plain letters that stand for any bytes).
//
// A JPEG photo is drawn again on a <canvas> before it is sent. The new file
// has only the picture: the hidden notes inside a photo (EXIF), which can hold
// the place where it was taken, are left behind. The browser turns the photo
// the right way up when it draws it, so that is kept. A big photo is made
// smaller until it fits. A GIF is never drawn again, so it still moves.
// The server checks every picture again, whatever the page did.

// A redrawn JPEG is at most this many pixels wide or tall, and this good
// (0 to 1). If it is still too big, it is drawn again at 3/4 of the size.
const MAX_REDRAWN_SIDE = 4096;
const REDRAWN_QUALITY = 0.9;

const pictureBox = document.getElementById("picture");
const pictureAltBox = document.getElementById("picture-alt");

// The rules for a picture and its description, the same as check_picture and
// check_alt_text in server.py, with the same codes, as far as a page can check
// them. `file` is the chosen file, or null. Returns { key, values }, or null
// if no rule is broken. The type the browser gives is only a quick hint: the
// server reads the file's first bytes. A JPEG's size is checked after it is
// drawn again (see redrawJpeg).
function pictureProblem(file, altText) {
  if (file === null) {
    return altText === "" ? null : { key: "picture_missing", values: {} };
  }
  if (!PICTURE_TYPES.includes(file.type)) {
    return { key: "picture_wrong_kind", values: {} };
  }
  if (file.type !== "image/jpeg" && file.size > MAX_PICTURE_BYTES) {
    return { key: "picture_too_big", values: { limit: MAX_PICTURE_MB } };
  }
  if (altText === "") {
    return { key: "picture_alt_empty", values: {} };
  }
  if (characterCount(altText) > MAX_ALT_TEXT) {
    return { key: "picture_alt_too_long", values: { limit: MAX_ALT_TEXT } };
  }
  if (HIDDEN_CHARACTERS.test(altText)) {
    return { key: "picture_alt_hidden", values: {} };
  }
  return null;
}

// Draw a JPEG again on a canvas, and return the new JPEG (a Blob: bytes in the
// browser), or null if it will not get small enough. Only the picture is
// drawn, so EXIF and the place go. "from-image" asks the browser to turn the
// photo the way its notes say, before drawing. Throws if it cannot be opened.
async function redrawJpeg(file) {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    let scale = Math.min(1, MAX_REDRAWN_SIDE / Math.max(bitmap.width, bitmap.height));
    for (let tries = 0; tries < 8; tries = tries + 1) {
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(function (done) {
        canvas.toBlob(done, "image/jpeg", REDRAWN_QUALITY);
      });
      if (blob === null) {
        throw new Error("The canvas could not make a JPEG.");   // for the console only
      }
      if (blob.size <= MAX_PICTURE_BYTES) {
        return blob;
      }
      scale = scale * 0.75;
    }
  } finally {
    bitmap.close();
  }
  return null;
}

// Read a file (or Blob) as base64 text. readAsDataURL gives
// "data:image/png;base64,iVBOR...": only the part after the comma is sent.
function readPictureAsBase64(blob) {
  return new Promise(function (done, failed) {
    const reader = new FileReader();
    reader.onload = function () {
      done(reader.result.slice(reader.result.indexOf(",") + 1));
    };
    reader.onerror = function () {
      failed(reader.error);
    };
    reader.readAsDataURL(blob);
  });
}

// The chosen picture, ready to send as base64: a JPEG drawn again, any other
// kind as it is. null if a JPEG will not get under the limit. Throws if the
// file cannot be read.
async function preparePicture(file) {
  if (file.type !== "image/jpeg") {
    return readPictureAsBase64(file);
  }
  const blob = await redrawJpeg(file);
  if (blob === null) {
    return null;
  }
  return readPictureAsBase64(blob);
}

// Empty both picture boxes: after a post is saved, and when nobody is logged in.
function clearPictureBoxes() {
  pictureBox.value = "";
  pictureAltBox.value = "";
}

// One picture on the page. The address comes from the server (post.picture.url),
// and the description is set as a property, never as HTML. The description is
// what the writer typed, so it is never a key in words.js.
function pictureElement(picture) {
  const image = document.createElement("img");
  image.className = "post-picture";
  image.loading = "lazy";      // load it only when it is about to be seen
  image.decoding = "async";
  image.src = picture.url;
  image.alt = picture.alt;
  return image;
}

// The part, added after the text and its Show more button, so the picture
// sits under the words. A post with no picture has "picture": null.
addPostPart(function picturePart(post, slots) {
  if (post.picture) {
    slots.body.append(pictureElement(post.picture));
  }
});

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

// ---- timeline-flow: new posts wait while you read; older posts load on scroll ----
//
// The page loads only the newest PAGE_SIZE posts when it opens
// (GET /posts?before=0), and the next older page (before=<oldest shown id>)
// when the bottom of the list comes near, or when "Show older posts" is
// pressed. New posts that arrive while you read lower down do not push the
// list down: they wait behind a "3 new posts" button at the top. If the top of
// the list is on screen, they appear at once.

// The same as PAGE_SIZE in server.py. The page only uses it to know when it
// has reached the end: a page shorter than this is the last one.
const PAGE_SIZE = 20;

// The words of this feature are in words.js: new_posts_one/_other,
// show_older, loading_older, no_older.

const newPostsButton = document.getElementById("new-posts");
const olderPosts = document.getElementById("older-posts");
const loadOlderButton = document.getElementById("load-older");

let oldestId = 0;                // the oldest post on screen; 0 means none yet
let firstPageLoaded = false;     // has the newest page come in?
let loadingOlder = false;        // one page at a time
let noOlderPosts = false;        // the server has no posts older than oldestId
const waitingPosts = [];         // new posts not shown yet, oldest first
let olderObserver = null;        // watches the bottom of the list (watchTheBottom)

// Put one post on the timeline, at "top" or "bottom", unless this window
// already shows it. showPost is not used here: it skips every post with an id
// at or below lastId, and an older post always has a smaller id.
function putPost(post, where) {
  if (postParts[post.id] !== undefined) {
    return;
  }
  postParts[post.id] = makePostItem(post);
  placePost(postParts[post.id].item, post, where);
}

// True when the top of the list is not above the screen, so adding a post
// there cannot move what the person is reading. A page position can be a
// part of a pixel (-0.16 right after "3 new posts" is pressed), so up to one
// pixel above still counts as the top.
function readerIsAtTop() {
  return timeline.getBoundingClientRect().top >= -1;
}

// New posts from GET /posts?after=, oldest first. Keep them waiting, then show
// them at once if the reader can see the top; otherwise update the button.
function receiveNewPosts(posts) {
  for (const post of posts) {
    // Two checks that ran at the same moment can both bring the same post.
    if (post.id <= lastId) {
      continue;
    }
    lastId = post.id;
    // replies: a reply to a post already on the timeline goes under it at once.
    if (hasParentOnTimeline(post)) {
      putPost(post, "under-parent");
      continue;
    }
    waitingPosts.push(post);
  }
  if (readerIsAtTop()) {
    showWaitingPosts();
  } else {
    updateNewPostsButton();
  }
}

// Show every waiting post, oldest first, so the newest ends up on top.
function showWaitingPosts() {
  for (const post of waitingPosts) {
    putPost(post, "top");
  }
  waitingPosts.length = 0;
  updateNewPostsButton();
}

// Hidden when nothing waits; otherwise "1 new post" or "3 new posts".
function updateNewPostsButton() {
  // replies: a reply that will go under a post is not a new post.
  const count = waitingPosts.filter(countsAsNewPost).length;
  newPostsButton.hidden = count === 0;
  if (count > 0) {
    newPostsButton.textContent = sayCount("new_posts", count);
  }
}

// "3 new posts" was pressed: show them, go to the top of the list, and move
// keyboard focus there, so a screen-reader user hears where they are instead
// of staying on a button that has just been hidden.
function pressNewPosts() {
  showWaitingPosts();
  timeline.scrollIntoView();
  timeline.focus({ preventScroll: true });
}

// Ask for the next page of older posts, and put them at the bottom. The first
// time (oldestId 0) this is the newest page.
async function loadOlderPosts() {
  if (loadingOlder || noOlderPosts) {
    return;
  }
  loadingOlder = true;
  loadOlderButton.dataset.words = "loading_older";
  loadOlderButton.textContent = say("loading_older");
  let loaded = false;
  try {
    const response = await fetch("/posts?before=" + oldestId);
    const posts = await response.json();
    if (!response.ok) {
      throw new Error(posts.code);
    }
    // The server sends them newest first: each goes at the bottom, in order.
    for (const post of posts) {
      putPost(post, "bottom");
    }
    if (posts.length > 0) {
      oldestId = posts[posts.length - 1].id;
      if (!firstPageLoaded) {
        // New posts are asked for from the newest one in the first page.
        lastId = Math.max(lastId, posts[0].id);
      }
    }
    firstPageLoaded = true;
    loaded = true;
    if (posts.length < PAGE_SIZE) {
      noOlderPosts = true;
      // Nothing at all if the timeline is empty: there is nothing older than nothing.
      if (oldestId === 0) {
        olderPosts.textContent = "";
      } else {
        olderPosts.dataset.words = "no_older";
        olderPosts.textContent = say("no_older");
      }
    }
    if (statusNow.key === "cannot_reach") {
      showStatus("");
    }
  } catch (error) {
    // The button stays, so the person can try again.
    showStatus("cannot_reach");
  } finally {
    loadingOlder = false;
    if (!noOlderPosts) {
      loadOlderButton.dataset.words = "show_older";
      loadOlderButton.textContent = say("show_older");
    }
  }
  if (olderObserver !== null) {
    if (noOlderPosts) {
      olderObserver.disconnect();
    } else if (loaded) {
      // Watch the bottom again. An observer only speaks when something
      // changes, so on a tall screen where the bottom is still in view after
      // a page, nothing would ever load the next one. Watching again makes it
      // look once more. (Not after an error, or it would ask again and again.)
      olderObserver.unobserve(olderPosts);
      olderObserver.observe(olderPosts);
    }
  }
}

// Load the next page when the bottom of the list is on screen or within 400
// pixels of it, so it is usually there before the person reaches the end.
// IntersectionObserver is a browser feature that tells the page when an
// element comes on screen. Without it, the button still works.
function watchTheBottom() {
  if (typeof IntersectionObserver === "undefined") {
    return;
  }
  olderObserver = new IntersectionObserver(function (entries) {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        loadOlderPosts();
      }
    }
  }, { rootMargin: "400px" });
  olderObserver.observe(olderPosts);
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
    showSignedOut("cannot_reach");
  }
}

// Ask the server for every post newer than the last one we have.
async function checkForNewPosts() {
  try {
    // timeline-flow (1 of 3): first the newest page, not every post ever.
    // If the server did not answer, the next second tries again.
    // edit-delete: changes first, then posts. A post changed between the two
    // questions is still right: it is not on the page yet, so its change is
    // skipped, and the post then comes in as it is now.
    await checkForChanges();
    if (!firstPageLoaded) {
      await loadOlderPosts();
      if (!firstPageLoaded) {
        return;
      }
    }
    const response = await fetch("/posts?after=" + lastId);
    const posts = await response.json();
    // timeline-flow (2 of 3): the server sends them oldest first. They wait
    // behind the "new posts" button, or appear at once at the top.
    receiveNewPosts(posts);
    // A like changes no post, so `after` would never bring one. The counts are
    // asked for separately, and all of them come back each time. "mine" comes
    // from the cookie: it is empty when nobody is logged in.
    // timeline-flow (3 of 3): only the posts from the oldest one on screen up.
    const likesAnswer = await fetch("/likes?from=" + oldestId);
    const likes = await likesAnswer.json();
    for (const postId in postParts) {
      showLike(postId, likes.counts[postId] || 0, likes.mine.includes(Number(postId)));
    }
    if (statusNow.key === "cannot_reach") {
      showStatus("");
    }
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Ask, wait for the answer, wait one second, then ask again. Forever.
async function keepChecking() {
  await checkForNewPosts();
  setTimeout(keepChecking, 1000);
}

// After a login, a sign-up or a log-out, the hearts this window shows as
// pressed belong to someone else, and so do the posts (block: each person
// sees no posts by the people they blocked) and the Block items in the
// menus. Draw the whole timeline again.
async function afterAccountChange() {
  loginPasswordBox.value = "";
  signupPasswordBox.value = "";
  await reloadTimeline();
  await askForReports();   // report: who is asking changed
}

// Log in with an account name and password.
async function logIn(event) {
  event.preventDefault();
  const name = loginNameBox.value.trim();
  const password = loginPasswordBox.value;
  if (name === "" || password === "") {
    showStatus("login_fields_empty");
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
      // The same code for a wrong name and a wrong password: see WRONG_LOGIN in server.py.
      showSignedOut("");
      showProblem(answer);
      if (response.status === 429) holdForm(loginForm, answer.retry_after);
      return;
    }
    showStatus("");
    showSignedIn(answer);
    await afterAccountChange();
  } catch (error) {
    showStatus("cannot_reach");
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
  if (problem !== null) {
    showStatus(problem.key, problem.values);
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
      // The server refused it. Its code says which rule was broken.
      showProblem(answer);
      if (response.status === 429) holdForm(signupForm, answer.retry_after);
      return;
    }
    showStatus("");
    showSignedIn(answer);
    await afterAccountChange();
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Log out. The server deletes this window's session and tells the browser
// to forget the cookie.
async function logOut() {
  try {
    await fetch("/sessions", { method: "DELETE" });
    forgetDraft();
    forgetPlace();
    showSignedOut("");
    await afterAccountChange();
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Send a new post to the server. It says only what the post says: who wrote
// it is the person logged in, and the server knows that from the cookie.
async function sendPost(event) {
  event.preventDefault();
  const text = textBox.value;

  // A quick check on the page, so the person does not wait for an answer.
  // The server checks the same rules again.
  const problem = textProblem(text.trim()) || placeProblem(placeBox.value.trim());
  if (problem !== null) {
    showStatus(problem.key, problem.values);
    return;
  }
  const place = placeBox.value;

  // pictures: a chosen file, and its description, go with the post. With no
  // file, both stay undefined, and JSON.stringify leaves them out.
  const file = pictureBox.files.length > 0 ? pictureBox.files[0] : null;
  const pictureTrouble = pictureProblem(file, pictureAltBox.value.trim());
  if (pictureTrouble !== null) {
    showStatus(pictureTrouble.key, pictureTrouble.values);
    return;
  }
  let picture;
  let pictureAlt;
  if (file !== null) {
    try {
      picture = await preparePicture(file);
    } catch (error) {
      showStatus("picture_unreadable");
      return;
    }
    if (picture === null) {
      showStatus("picture_too_big", { limit: MAX_PICTURE_MB });
      return;
    }
    pictureAlt = pictureAltBox.value;
  }

  try {
    const response = await fetch("/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // replies: parent_id is the post this answers, or null for a normal post.
      body: JSON.stringify({ text: text, place: place, picture: picture, picture_alt: pictureAlt,
        parent_id: replyingTo === null ? null : replyingTo.id }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      // The login has ended. Show the Log in form, and the server's reason.
      showSignedOut("");
      showProblem(answer);
      return;
    }
    if (!response.ok) {
      // The server refused the post. Its code says which rule was broken.
      showProblem(answer);
      if (response.status === 429) holdForm(postForm, answer.retry_after);
      return;
    }
    // Saved. Ask for new posts now, instead of waiting for the next second.
    // This also brings in any post from another window that came just before ours.
    showStatus("");
    textBox.value = "";
    clearPictureBoxes();
    stopReplying();
    forgetDraft();
    updateCount();
    // The place box is not emptied: the same place is likely next time.
    rememberPlace(place.trim());
    await checkForNewPosts();
    // timeline-flow: you expect to see your own post, so show every waiting one.
    showWaitingPosts();
  } catch (error) {
    showStatus("cannot_reach");
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
    showStatus("login_to_like");
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
      showSignedOut("");
      showProblem(answer);
      await checkForNewPosts();
      return;
    }
    if (!response.ok) {
      // The server refused it, and says which rule was broken. This window had
      // the heart wrong, so ask the server what is true instead of guessing.
      showProblem(answer);
      await checkForNewPosts();
      return;
    }
    // Done. Show the new count now, instead of waiting for the next second.
    showStatus("");
    showLike(postId, answer.like_count, !liked);
  } catch (error) {
    showStatus("cannot_reach");
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
// already has one). `key` names the button's words in words.js. Returns the
// section, for the feature to fill.
function addView(name, key) {
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
  button.dataset.words = key;
  button.textContent = say(key);
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

// The words of this feature are in words.js (search_..., results_...). One
// sentence is one key, never joined from pieces.

const searchForm = document.getElementById("search-form");
const searchBox = document.getElementById("search-box");
const resultsTitle = document.getElementById("results-title");
const resultsList = document.getElementById("results-list");
const backToTimelineButton = document.getElementById("back-to-timeline");

// The search the results now show ("" if none), and a number for each search,
// so an older answer that arrives late never covers a newer one.
let shownQuery = "";
let shownAnswer = null;   // the server's answer the results now show, or null
let searchNumber = 0;

// The rules of check_query in server.py, with the same codes.
// Returns the broken rule as { key, values }, or null if none.
// Words are split at spaces, a Japanese full-width space too, as Python does.
function queryProblem(query) {
  const trimmed = query.trim();
  if (trimmed === "") {
    return { key: "search_empty", values: {} };
  }
  if (characterCount(trimmed) > MAX_QUERY) {
    return { key: "search_too_long", values: { limit: MAX_QUERY } };
  }
  if (trimmed.split(/\s+/).length > MAX_QUERY_WORDS) {
    return { key: "search_too_many_words", values: { limit: MAX_QUERY_WORDS } };
  }
  return null;
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
  if (problem !== null) {
    showStatus(problem.key, problem.values);
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
      // The server refused the search. Its code says which rule was broken.
      showProblem(answer);
      return;
    }
    showStatus("");
    showResults(query, answer);
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Fill the results view with the posts the server found, and show it. Each
// post is built by makePostItem, so it looks the same as on the timeline. The
// results are not kept in postParts: only the live timeline is kept up to date.
function showResults(query, answer) {
  shownQuery = query;
  shownAnswer = answer;
  resultsList.replaceChildren();
  for (const post of answer.posts) {
    const parts = makePostItem(post);
    // Liking is done on the timeline, where each heart is kept up to date.
    parts.likeButton.disabled = true;
    parts.likeButton.dataset.wordsAriaLabel = "results_heart";
    parts.likeButton.dataset.wordsTitle = "results_heart";
    parts.likeButton.setAttribute("aria-label", say("results_heart"));
    parts.likeButton.setAttribute("title", say("results_heart"));
    resultsList.append(parts.item);
  }
  showResultsTitle();
  showView("search");
}

// The line above the results: how many posts have the words. Written again
// after a language change.
function showResultsTitle() {
  if (shownAnswer === null) {
    resultsTitle.textContent = say("results_start");
    return;
  }
  const count = shownAnswer.posts.length;
  const values = { count: count, query: shownQuery };
  let words;
  if (count === 0) {
    words = say("results_none", values);
  } else if (shownAnswer.more) {
    words = say("results_more", values);
  } else {
    words = sayCount("results", count, { query: shownQuery });
  }
  // textContent, never innerHTML: the search is text the person typed.
  resultsTitle.textContent = words;
}

whenLanguageChanges(showResultsTitle);

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

// ---- bookmarks: save a post only you can see ----
//
// A ☆ under every post saves it for you; a ★ means it is saved, and pressing it
// takes the bookmark back. "My bookmarks" shows only the posts you saved. A
// bookmark is private: the server shows it only to the person who made it, and
// there is no count. The page never says who you are: the server knows from
// the cookie. Bookmarks are not asked for every second: they change only when
// you press a ☆, and the answer to that press says what is now true.

// The words of this feature are in words.js (bookmark_..., bookmarks_...).

// The ids of the posts this person has bookmarked. Empty when signed out.
const bookmarked = new Set();
// The posts whose ☆ is being sent now: one press at a time for each post.
const bookmarksBusy = new Set();
// The list of bookmarked posts and its "none yet" line, made by setUpBookmarks.
let bookmarkList = null;
let bookmarksEmpty = null;
let bookmarksViewButton = null;

// The ☆ in the foot of every post. It starts as the set says, so a post that
// arrives later already shows the right star.
addPostPart(function bookmarkPart(post, slots) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "bookmark button-pill";
  button.dataset.action = "bookmark";
  button.dataset.postId = post.id;
  drawBookmarkButton(button, bookmarked.has(post.id));
  // Next to the heart, on the same row, if the heart is there.
  const likeRow = slots.foot.querySelector(".like-row");
  (likeRow || slots.foot).append(button);
});

// One ☆ or ★, with what pressing it would do, for a screen reader.
function drawBookmarkButton(button, on) {
  button.textContent = on ? "★" : "☆";
  button.classList.toggle("bookmarked", on);
  button.setAttribute("aria-pressed", on ? "true" : "false");
  button.dataset.wordsAriaLabel = on ? "bookmark_remove" : "bookmark_add";
  button.setAttribute("aria-label", say(button.dataset.wordsAriaLabel));
}

// This post is now bookmarked (on) or not. Every ☆ of this post changes: the
// one on the timeline, and the one in My bookmarks.
function showBookmark(postId, on) {
  if (on) {
    bookmarked.add(postId);
  } else {
    bookmarked.delete(postId);
  }
  for (const button of document.querySelectorAll('.bookmark[data-post-id="' + postId + '"]')) {
    drawBookmarkButton(button, on);
  }
}

// Ask the server which posts this person bookmarked, and show them. Asked
// when someone logs in, when My bookmarks opens, and after a refused press.
async function loadBookmarks() {
  try {
    const response = await fetch("/bookmarks");
    const answer = await response.json();
    if (response.status === 401) {
      clearBookmarks();
      return;
    }
    if (!response.ok) {
      showProblem(answer);
      return;
    }
    bookmarked.clear();
    for (const post of answer) {
      bookmarked.add(post.id);
    }
    for (const button of document.querySelectorAll(".bookmark")) {
      drawBookmarkButton(button, bookmarked.has(Number(button.dataset.postId)));
    }
    showBookmarkList(answer);
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Logged out: forget every bookmark and empty the list, so nothing private
// stays on a shared computer's screen. The timeline is shown again.
function clearBookmarks() {
  bookmarked.clear();
  for (const button of document.querySelectorAll(".bookmark")) {
    drawBookmarkButton(button, false);
  }
  if (bookmarkList !== null) {
    bookmarkList.replaceChildren();
    bookmarksEmpty.hidden = true;
    bookmarksViewButton.hidden = true;
    if (!bookmarkList.closest("[data-view]").hidden) {
      showView("timeline");
    }
    showViewsNavIfNeeded();
  }
}

// Draw My bookmarks: each post built the same way as on the timeline.
function showBookmarkList(posts) {
  bookmarkList.replaceChildren();
  for (const post of posts) {
    bookmarkList.append(makePostItem(post).item);
  }
  bookmarksEmpty.hidden = posts.length > 0;
  bookmarksViewButton.hidden = false;
  showViewsNavIfNeeded();
}

// The views nav is shown only when two or more of its buttons can be used.
function showViewsNavIfNeeded() {
  const shown = Array.from(viewsNav.querySelectorAll("button")).filter(function (button) {
    return !button.hidden;
  });
  viewsNav.hidden = shown.length < 2;
}

// Press the ☆: bookmark the post, or take the bookmark back if it is a ★.
// The method says which: POST adds, DELETE removes. Only the post id is sent.
async function pressBookmark(postId) {
  // Only a person who is logged in can bookmark. The server checks this again.
  if (account === null) {
    showStatus("bookmark_log_in");
    return;
  }
  if (bookmarksBusy.has(postId)) {
    return;
  }
  bookmarksBusy.add(postId);
  const on = bookmarked.has(postId);
  try {
    const response = await fetch("/bookmarks", {
      method: on ? "DELETE" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_id: postId }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      showSignedOut("");
      showProblem(answer);
      return;
    }
    if (!response.ok) {
      // This window had the star wrong (perhaps another tab changed it), so
      // ask the server what is true instead of guessing.
      showProblem(answer);
      await loadBookmarks();
      return;
    }
    showStatus("");
    showBookmark(postId, answer.bookmarked);
    // A post taken out of My bookmarks leaves the list at once.
    if (!answer.bookmarked) {
      for (const item of bookmarkList.querySelectorAll('.post[data-post-id="' + postId + '"]')) {
        item.remove();
      }
      bookmarksEmpty.hidden = bookmarkList.children.length > 0;
    }
  } catch (error) {
    showStatus("cannot_reach");
  } finally {
    bookmarksBusy.delete(postId);
  }
}

ACTIONS.bookmark = pressBookmark;

// Add the My bookmarks view: its list, its "none yet" line, and its button,
// which stays hidden until someone is logged in. Opening it asks the server again.
function setUpBookmarks() {
  const section = addView("bookmarks", "bookmarks_view");
  bookmarkList = document.createElement("ol");
  bookmarkList.id = "bookmark-list";
  bookmarkList.className = "timeline card";
  bookmarkList.dataset.wordsAriaLabel = "bookmarks_list";
  bookmarkList.setAttribute("aria-label", say("bookmarks_list"));
  bookmarksEmpty = document.createElement("p");
  bookmarksEmpty.id = "bookmarks-empty";
  bookmarksEmpty.className = "bookmarks-empty";
  bookmarksEmpty.dataset.words = "bookmarks_empty";
  bookmarksEmpty.textContent = say("bookmarks_empty");
  bookmarksEmpty.hidden = true;
  section.append(bookmarkList, bookmarksEmpty);
  bookmarkList.addEventListener("click", clickOnTimeline);
  bookmarksViewButton = viewsNav.querySelector('[data-show-view="bookmarks"]');
  bookmarksViewButton.hidden = true;
  bookmarksViewButton.addEventListener("click", loadBookmarks);
  showViewsNavIfNeeded();
}

// ---- block: block an account, and see who you blocked ----
//
// "Block @ben" is in the "⋯" menu of every post by someone else, when you are
// logged in. The server then leaves Ben's posts out of everything it sends
// you (the timeline, older posts, search, bookmarks), so the page only takes
// away the posts it already shows. Unblocking is in the "Blocked accounts"
// list under "Signed in as", because the blocked person's posts are no
// longer there to press anything on.
//
// Another window of yours keeps Ben's older posts until it is reloaded. His
// new posts never arrive there: the server already leaves them out.
//
// The words of this feature are in words.js (block_..., unblock_..., blocked_...).

const blockedSection = document.getElementById("blocked-section");
const blockedList = document.getElementById("blocked-list");

// The accounts this person has blocked, as the server last said.
let blockedNow = [];

// One block or unblock at a time, so a fast second press does not send it twice.
let blockBusy = false;

// Two account names are the same account if they differ only in capitals,
// as in the server (name = ? COLLATE NOCASE).
function sameAccount(one, other) {
  return one.toLowerCase() === other.toLowerCase();
}

// Every post remembers its author, so hidePostsBy can find it. Then, only for
// someone logged in, and only on another person's post (the page's copy of
// the rule block_self), a "Block @name" item in the "⋯" menu.
addPostPart(function blockPart(post, slots, item) {
  item.dataset.author = post.author;
  if (account === null || sameAccount(post.author, account.account_name)) {
    return;
  }
  const button = addMenuItem(slots, "block", "block_menu");
  button.dataset.author = post.author;
  drawBlockMenuItem(button);
});

// "Block @ben": words with a value, so not data-words. Written again by
// redrawBlockWords when the language changes.
function drawBlockMenuItem(button) {
  delete button.dataset.words;
  button.textContent = say("block_menu", { name: button.dataset.author });
}

// "Block @ben" was pressed. Ask first, because the posts disappear at once.
async function pressBlock(postId, button) {
  const name = button.dataset.author;
  if (account === null) {
    showStatus("block_log_in");
    return;
  }
  if (blockBusy || !confirm(say("block_confirm", { name: name }))) {
    return;
  }
  blockBusy = true;
  try {
    const response = await fetch("/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_name: name }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      // The login has ended. Show the Log in form, and the server's reason.
      showSignedOut("");
      showProblem(answer);
      await reloadTimeline();
      return;
    }
    if (!response.ok) {
      // The server refused it, and says which rule was broken.
      showProblem(answer);
      return;
    }
    hidePostsBy(answer.account_name);
    showStatus("block_done", { name: answer.account_name });
    await loadBlocked();
  } catch (error) {
    showStatus("cannot_reach");
  } finally {
    blockBusy = false;
  }
}

ACTIONS.block = pressBlock;

// Take every post by this account off the page: the live timeline (with
// removePost), the posts waiting behind "new posts", and any other list of
// posts (search results, My bookmarks). The line under each post that is left
// is asked for again, so the blocked person's name leaves it too (who-liked).
function hidePostsBy(name) {
  for (const postId of Object.keys(postParts)) {
    // A reply may already be gone with its post (replies: removePost).
    if (postParts[postId] !== undefined
        && sameAccount(postParts[postId].item.dataset.author, name)) {
      removePost(postId);
    }
  }
  for (let i = waitingPosts.length - 1; i >= 0; i--) {
    if (sameAccount(waitingPosts[i].author, name)) {
      waitingPosts.splice(i, 1);
    }
  }
  updateNewPostsButton();
  for (const item of document.querySelectorAll("li.post")) {
    if (item.dataset.author !== undefined && sameAccount(item.dataset.author, name)) {
      item.remove();
    }
  }
  for (const postId of Object.keys(postParts)) {
    postParts[postId].summaryFor = "";
  }
}

// Ask the server who this person has blocked, and show the list.
async function loadBlocked() {
  try {
    const response = await fetch("/blocks");
    const answer = await response.json();
    if (response.ok) {
      showBlocked(answer.blocked);
    }
    // 401: nobody is logged in, so there is no list to show.
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// One line for each blocked account: display name, @name, and an Unblock
// button. The whole list is hidden while it is empty.
function showBlocked(blocked) {
  blockedNow = blocked;
  blockedList.replaceChildren();
  for (const person of blocked) {
    const author = document.createElement("span");
    author.className = "post-author";
    author.textContent = person.display_name;
    const handle = document.createElement("span");
    handle.className = "post-handle";
    handle.textContent = "@" + person.account_name;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button-link unblock";
    button.dataset.unblock = person.account_name;
    button.dataset.words = "unblock_button";
    button.textContent = say("unblock_button");
    button.setAttribute("aria-label", say("unblock_label", { name: person.account_name }));
    const row = document.createElement("li");
    row.append(author, handle, button);
    blockedList.append(row);
  }
  blockedSection.hidden = blocked.length === 0;
}

// The words with values of their own, again in the language now shown.
whenLanguageChanges(function redrawBlockWords() {
  for (const button of document.querySelectorAll('[data-action="block"]')) {
    drawBlockMenuItem(button);
  }
  showBlocked(blockedNow);
});

// Unblock was pressed. The posts that come back are older than the newest one
// shown, and "after" would never bring them, so the timeline is drawn again.
async function unblock(name) {
  if (blockBusy) {
    return;
  }
  blockBusy = true;
  try {
    const response = await fetch("/blocks", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_name: name }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      showSignedOut("");
      showProblem(answer);
      await reloadTimeline();
      return;
    }
    if (!response.ok) {
      showProblem(answer);
      await loadBlocked();
      return;
    }
    showStatus("unblock_done", { name: answer.account_name });
    await loadBlocked();
    await reloadTimeline();
  } catch (error) {
    showStatus("cannot_reach");
  } finally {
    blockBusy = false;
  }
}

function clickOnBlockedList(event) {
  const button = event.target.closest("[data-unblock]");
  if (button !== null) {
    unblock(button.dataset.unblock);
  }
}

// Draw the whole timeline again, from the newest page, as when the page
// opens. Used when the posts this window may see have changed: after a login
// or a log-out, and after an unblock. Every mark timeline-flow keeps starts
// again, and "Show older posts" comes back.
async function reloadTimeline() {
  for (const postId of Object.keys(postParts)) {
    removePost(postId);
  }
  timeline.replaceChildren();
  waitingPosts.length = 0;
  updateNewPostsButton();
  lastId = 0;
  oldestId = 0;
  firstPageLoaded = false;
  noOlderPosts = false;
  delete olderPosts.dataset.words;
  olderPosts.replaceChildren(loadOlderButton);
  loadOlderButton.dataset.words = "show_older";
  loadOlderButton.textContent = say("show_older");
  if (olderObserver !== null) {
    olderObserver.disconnect();
    olderObserver.observe(olderPosts);
  }
  // The newest page first, then the hearts and their counts.
  await checkForNewPosts();
}

// ---- edit-delete: change or delete your own post ----
//
// On your own posts, the "⋯" menu has Edit and Delete, and "Show old
// versions" once the post has been edited. They are made only when you are
// logged in and the post is yours (like Block, they are made again when the
// timeline is drawn again after a login or a log-out). The server checks
// again: only the author may change a post (own_post in server.py).
//
// An edited post says "· edited" after its time. Anyone can press it to see
// the earlier words, oldest first. A deleted post that has replies stays, as
// "This post was deleted", with its replies under it; it has no heart, no
// Reply and no ☆.
//
// THE CHANGES FEED. Every second, before asking for new posts, the page asks
// GET /changes for every change since the last one it saw. A change brings
// the post as the server now shows it to this window: a post means "draw it
// again", null means "take it away". The page never looks at the kind. Every
// copy of the post is changed: on the timeline, waiting behind "new posts",
// in the search results and in My bookmarks.
//
// The words of this feature are in words.js (edit_..., delete_..., versions_...,
// edited_..., deleted_post).

// The newest change this window has seen. null: "not asked yet".
let lastChangeId = null;

// Each post on the page, and the post (from the server) it was drawn from,
// so Cancel can draw it again. A WeakMap forgets an item when it is gone.
const postOfItem = new WeakMap();

// "· edited" after the time, and the list of earlier versions it opens. A
// post deleted but kept for its replies says so instead of its words, and
// has no heart, no Reply and no ☆ (it can be neither liked, answered nor saved).
// This part runs after the others, so their buttons are already there.
addPostPart(function editedPart(post, slots, item) {
  postOfItem.set(item, post);
  if (post.deleted) {
    const text = slots.body.querySelector(".post-text");
    if (text !== null) {
      text.dataset.words = "deleted_post";
      text.textContent = say("deleted_post");
      text.classList.add("post-deleted");
    }
    for (const gone of slots.foot.querySelectorAll(
      ".like, .like-count, .like-summary, .likers, .reply-button, .bookmark")) {
      gone.hidden = true;
    }
    return;
  }
  const list = document.createElement("ol");
  list.className = "versions";
  list.dataset.wordsAriaLabel = "versions_label";
  list.setAttribute("aria-label", say("versions_label"));
  list.hidden = true;
  slots.body.append(list);
  if (post.edited) {
    const mark = document.createElement("button");
    mark.type = "button";
    mark.className = "button-link edited";
    mark.dataset.action = "versions";
    mark.dataset.postId = post.id;
    mark.setAttribute("aria-expanded", "false");
    mark.dataset.words = "edited_mark";
    mark.textContent = say("edited_mark");
    mark.dataset.wordsAriaLabel = "edited_label";
    mark.setAttribute("aria-label", say("edited_label"));
    slots.head.append(mark);
  }
});

// Edit, Delete and Show old versions, in the "⋯" menu: only on your own post,
// and never on a deleted one.
addPostPart(function ownerToolsPart(post, slots) {
  if (post.deleted || account === null || !sameAccount(post.author, account.account_name)) {
    return;
  }
  addMenuItem(slots, "edit", "edit_menu");
  addMenuItem(slots, "delete", "delete_menu");
  if (post.edited) {
    addMenuItem(slots, "versions", "versions_menu");
  }
});

// ---- report: three reports hide a post from everyone but its author ----
//
// "Report" is an item in the "⋯" menu of other people's posts, only for
// someone logged in (made again when the timeline is drawn again after a
// login or a log-out, like Block). Pressing it asks for an optional reason
// with the browser's own prompt() box, then sends POST /reports. Pressing it
// again ("Take back my report") sends DELETE /reports.
//
// When three people have reported a post, the server stops sending it to
// everyone but its author. The author still sees it, faded, with a note
// (post.hidden_by_reports). An open window hears that a post was hidden or
// shown again from the changes feed, like an edit: nothing here asks every
// second. GET /reports is asked only when the page opens, after a login or a
// log-out, and after a press, for "which did I report" and "which of mine are
// hidden".
//
// The words of this feature are in words.js (report_...).

// The same limit as MAX_REASON in server.py.
const MAX_REASON = 200;

// The posts this person has reported, as the server last said.
let reportedNow = new Set();

// One report or take-back at a time, so a fast second press does not send it twice.
let reportBusy = false;

// The note for a hidden post (shown only to its author), and, only for someone
// logged in and only on another person's post (the page's copy of the rule
// report_own_post), a Report item in the "⋯" menu.
addPostPart(function reportPart(post, slots, item) {
  const note = document.createElement("p");
  note.className = "hidden-note";
  note.dataset.words = "report_hidden_note";
  note.textContent = say("report_hidden_note");
  slots.body.prepend(note);
  item.dataset.hiddenByReports = post.hidden_by_reports ? "true" : "false";
  if (!post.deleted && account !== null && !sameAccount(post.author, account.account_name)) {
    addMenuItem(slots, "report", "report_menu");
  }
  drawReportState(item);
});

// Draw one copy of a post as the report state says: the menu item's words,
// and the faded look with its note.
function drawReportState(item) {
  const button = item.querySelector('[data-action="report"]');
  if (button !== null) {
    const reported = reportedNow.has(Number(item.dataset.postId));
    button.dataset.words = reported ? "report_take_back_menu" : "report_menu";
    button.textContent = say(button.dataset.words);
    button.setAttribute("aria-pressed", reported ? "true" : "false");
  }
  const hidden = item.dataset.hiddenByReports === "true";
  item.classList.toggle("hidden-by-reports", hidden);
  item.querySelector(".hidden-note").hidden = !hidden;
}

// The server's answer to GET /reports. A post hidden from this person is
// taken away everywhere (the same as a change with no post); every other copy
// is drawn again.
function showReports(answer) {
  reportedNow = new Set(answer.reported);
  for (const postId of answer.hidden) {
    applyChange({ post_id: postId, post: null });
  }
  for (const item of document.querySelectorAll("li.post[data-post-id]")) {
    item.dataset.hiddenByReports = answer.mine_hidden.includes(Number(item.dataset.postId))
      ? "true" : "false";
    drawReportState(item);
  }
}

// Ask the server which posts are hidden and which this person reported.
async function askForReports() {
  try {
    const response = await fetch("/reports");
    const answer = await response.json();
    if (response.ok) {
      showReports(answer);
    }
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Report was pressed: report the post, or take the report back if this
// person already did. The method says which: POST adds, DELETE takes away.
async function pressReport(postId, button) {
  // The server checks all of these again.
  if (account === null) {
    showStatus("report_log_in");
    return;
  }
  if (reportBusy) {
    return;
  }
  const reported = button.getAttribute("aria-pressed") === "true";
  // A report taken back has no reason: null.
  let reason = null;
  if (!reported) {
    // Cancel gives null: then nothing is sent. An empty answer means "no reason".
    reason = prompt(say("report_ask_reason"));
    if (reason === null) {
      return;
    }
    if (characterCount(reason.trim()) > MAX_REASON) {
      showStatus("report_reason_too_long", { limit: MAX_REASON });
      return;
    }
  }
  // The rule "you must have posted before it" (report_too_early) is checked
  // only by the server: this window may not have every older post on screen.
  reportBusy = true;
  button.closest(".post-menu").open = false;
  try {
    const response = await fetch("/reports", {
      method: reported ? "DELETE" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_id: postId, reason: reason }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      // The login has ended. Show the Log in form, and the server's reason.
      showSignedOut("");
      showProblem(answer);
      await reloadTimeline();
    } else if (!response.ok) {
      // The server refused it, and says which rule was broken.
      showProblem(answer);
    } else {
      showStatus(reported ? "report_taken_back" : "report_sent");
    }
    // Whatever happened, ask the server what is true now.
    await askForReports();
  } catch (error) {
    showStatus("cannot_reach");
  } finally {
    reportBusy = false;
  }
}

ACTIONS.report = pressReport;

// Ask the server what changed since the last change this window saw.
// Errors go up to checkForNewPosts, which says the server cannot be reached.
async function checkForChanges() {
  const response = await fetch("/changes" + (lastChangeId === null ? "" : "?after=" + lastChangeId));
  const answer = await response.json();
  if (!response.ok) {
    throw new Error(answer.code);
  }
  for (const change of answer.changes) {
    applyChange(change);
  }
  lastChangeId = answer.latest;
}

// One change: `post` is the post as the server now shows it, or null.
// Every copy of the post on this page follows it. A copy being edited keeps
// its edit box; the newest post is kept for Cancel.
function applyChange(change) {
  const postId = change.post_id;
  const post = change.post;
  // timeline-flow: a post still waiting behind "new posts" is changed there.
  const waiting = waitingPosts.findIndex(function (other) { return other.id === postId; });
  if (waiting !== -1) {
    if (post === null) {
      waitingPosts.splice(waiting, 1);
    } else {
      waitingPosts[waiting] = post;
    }
    updateNewPostsButton();
  }
  const copies = document.querySelectorAll('li.post[data-post-id="' + postId + '"]');
  for (const item of Array.from(copies)) {
    if (!item.isConnected) {
      continue;   // already gone with the post it answered (replies)
    }
    if (item.dataset.editing === "true" && post !== null && !post.deleted) {
      postOfItem.set(item, post);
    } else {
      showChangedPost(item, postId, post);
    }
  }
  // bookmarks: the server deleted the bookmarks of a deleted post.
  if ((post === null || post.deleted) && bookmarked.has(postId)) {
    bookmarked.delete(postId);
    bookmarksEmpty.hidden = bookmarkList.children.length > 0;
  }
}

// Draw one copy of a post again (post), or take it away (null). On the live
// timeline through removePost and redrawPost; in the other lists in place.
// The search never finds a deleted post, and My bookmarks has lost it, so
// there a deleted post is taken away too. In the other lists the old heart is
// kept as it was (in the search results it is turned off).
function showChangedPost(item, postId, post) {
  const parts = postParts[postId];
  if (parts !== undefined && parts.item === item) {
    if (post === null) {
      removePost(postId);
    } else {
      redrawPost(post);
    }
    return;
  }
  stopWatchingText(item);
  if (post === null || post.deleted) {
    item.remove();
    return;
  }
  const fresh = makePostItem(post);
  const oldHeart = item.querySelector(".like");
  if (oldHeart !== null) {
    fresh.likeButton.replaceWith(oldHeart);
  }
  item.replaceWith(fresh.item);
}

// Edit was pressed: swap the words for a box holding them, with Save and
// Cancel. Only one edit is open at a time.
function startEdit(postId, button) {
  const item = button.closest(".post");
  if (item.dataset.editing === "true") {
    return;
  }
  for (const other of document.querySelectorAll('li.post[data-editing="true"]')) {
    cancelEdit(Number(other.dataset.postId), other);
  }
  const menu = item.querySelector(".post-menu");
  if (menu !== null) {
    menu.open = false;
  }
  item.dataset.editing = "true";
  const body = item.querySelector(".post-body");
  for (const child of body.children) {
    child.hidden = true;
  }

  const box = document.createElement("div");
  box.className = "edit-box";
  const words = document.createElement("textarea");
  words.rows = 3;
  words.value = postOfItem.get(item).text;
  words.dataset.wordsAriaLabel = "edit_box_label";
  words.setAttribute("aria-label", say("edit_box_label"));
  const count = document.createElement("span");
  count.className = "count";
  const showCount = function () {
    const length = characterCount(words.value);
    count.textContent = length + " / " + MAX_TEXT;
    count.classList.toggle("too-long", length > MAX_TEXT);
  };
  words.addEventListener("input", showCount);
  showCount();

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "button-link";
  cancel.dataset.action = "cancelEdit";
  cancel.dataset.postId = postId;
  cancel.dataset.words = "edit_cancel";
  cancel.textContent = say("edit_cancel");
  const save = document.createElement("button");
  save.type = "button";
  save.dataset.action = "saveEdit";
  save.dataset.postId = postId;
  save.dataset.words = "edit_save";
  save.textContent = say("edit_save");

  const row = document.createElement("div");
  row.className = "edit-row";
  row.append(count, cancel, save);
  box.append(words, row);
  body.append(box);
  words.focus();
}

// Cancel was pressed: draw the post again, as the server last showed it.
// `button` may be the post's <li> itself (startEdit closes another edit so).
function cancelEdit(postId, button) {
  const item = button.closest(".post");
  delete item.dataset.editing;
  showChangedPost(item, postId, postOfItem.get(item));
}

// Save was pressed: send the new words. The same rules as a new post
// (textProblem), checked here first and again by the server.
async function sendEdit(postId, button) {
  const item = button.closest(".post");
  if (item.dataset.busy === "true") {
    return;
  }
  const text = item.querySelector(".edit-box textarea").value;
  const problem = textProblem(text.trim());
  if (problem !== null) {
    showStatus(problem.key, problem.values);
    return;
  }
  // One save at a time, so two fast clicks send one request.
  item.dataset.busy = "true";
  try {
    const response = await fetch("/posts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_id: postId, text: text }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      showSignedOut("");
      showProblem(answer);
      await afterAccountChange();
      return;
    }
    if (!response.ok) {
      // 400 a broken rule, 403 not yours. The code says which.
      showProblem(answer);
      return;
    }
    showStatus("");
    delete item.dataset.editing;
    applyChange({ post_id: postId, post: answer });
  } catch (error) {
    showStatus("cannot_reach");
  } finally {
    delete item.dataset.busy;
  }
}

// Delete was pressed: ask once, then delete. The answer is the post as the
// server now shows it: null when it is gone, or "This post was deleted" when
// it is kept for its replies.
async function deletePost(postId, button) {
  const item = button.closest(".post");
  if (item.dataset.busy === "true" || !confirm(say("delete_confirm"))) {
    return;
  }
  item.dataset.busy = "true";
  try {
    const response = await fetch("/posts", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ post_id: postId }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      showSignedOut("");
      showProblem(answer);
      await afterAccountChange();
      return;
    }
    if (!response.ok) {
      showProblem(answer);
      return;
    }
    showStatus("");
    delete item.dataset.editing;
    applyChange({ post_id: answer.post_id, post: answer.post });
  } catch (error) {
    showStatus("cannot_reach");
  } finally {
    delete item.dataset.busy;
  }
}

// "· edited" or "Show old versions" was pressed: open or close the earlier
// words of the post. The list is found from the button, so this works in any
// list of posts.
async function toggleVersions(postId, button) {
  const item = button.closest(".post");
  const list = item.querySelector(".versions");
  if (list === null) {
    return;
  }
  const open = list.hidden;
  list.hidden = !open;
  for (const opener of item.querySelectorAll('[data-action="versions"]')) {
    opener.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (!open) {
    return;
  }
  const menu = item.querySelector(".post-menu");
  if (menu !== null) {
    menu.open = false;
  }
  try {
    const response = await fetch("/versions?post_id=" + postId);
    const answer = await response.json();
    if (!response.ok) {
      showProblem(answer);
      return;
    }
    buildVersions(list, answer);
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// One row for each earlier version, oldest first: its words, and when they
// were replaced (timeElement: "5 minutes ago", with the full date on hover).
function buildVersions(list, versions) {
  list.replaceChildren();
  if (versions.length === 0) {
    const row = document.createElement("li");
    row.dataset.words = "versions_none";
    row.textContent = say("versions_none");
    list.append(row);
    return;
  }
  for (const version of versions) {
    const words = document.createElement("p");
    words.className = "version-text";
    showPostText(words, version.text);   // what a person wrote: never a key
    const row = document.createElement("li");
    row.append(words, timeElement(version.replaced_at, null));
    list.append(row);
  }
}

ACTIONS.edit = startEdit;
ACTIONS.saveEdit = sendEdit;
ACTIONS.cancelEdit = cancelEdit;
ACTIONS.delete = deletePost;
ACTIONS.versions = toggleVersions;

// ---- reply-email: your email address, and emails when someone replies ----
//
// In the "Email" box (shown only when signed in) a person saves an address.
// The server prints a confirm email in its terminal, with a link:
// http://localhost:8009/#confirm-email=<token>. Opening that link here sends
// the token to the server, which confirms the address from the token alone (no
// login needed). Once it is confirmed, the server makes an email each time
// someone replies to this person's post, unless the switch is off.
//
// The address is what a person wrote, so it is never a key in words.js.
// The words of this feature are in words.js (email_..., reply_emails_...).

// The same as MAX_EMAIL and EMAIL in server.py, with the same codes.
const MAX_EMAIL = 254;
const EMAIL = /^[^@\s,;:<>()\[\]\\"]+@[^@\s,;:<>()\[\]\\"]+\.[^@\s,;:<>()\[\]\\"]+$/;

const emailForm = document.getElementById("email-form");
const emailBox = document.getElementById("email");
const emailStateLine = document.getElementById("email-state");
const emailRemoveButton = document.getElementById("email-remove");
const replyEmailsRow = document.getElementById("reply-emails-row");
const replyEmailsBox = document.getElementById("reply-emails");

// The start of the address of a confirm link. The token is after the #, so
// it never reaches the server's request log.
const CONFIRM_START = "#confirm-email=";

// The settings as the server last said ({ email, confirmed, reply_emails }),
// or null when nobody is logged in.
let emailNow = null;

// Each ask is numbered, so an older answer that comes late never covers a newer one.
let emailAsks = 0;

// The rules for an address, the same as check_email in server.py, with the
// same codes. Returns the broken rule as { key, values }, or null if none.
function emailProblem(address) {
  if (address === "") {
    return { key: "email_empty", values: {} };
  }
  if (characterCount(address) > MAX_EMAIL) {
    return { key: "email_too_long", values: { limit: MAX_EMAIL } };
  }
  if (HIDDEN_CHARACTERS.test(address)) {
    return { key: "email_hidden", values: {} };
  }
  if (!EMAIL.test(address)) {
    return { key: "email_not_valid", values: {} };
  }
  return null;
}

// Ask the server for this person's address and switch.
async function askEmailSettings() {
  const mine = ++emailAsks;
  try {
    const response = await fetch("/email");
    const answer = await response.json();
    if (response.ok && mine === emailAsks) {
      showEmailSettings(answer);
    }
    // 401: nobody is logged in, so there is nothing to show.
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Show the settings: the box, the line that says how things are, Remove, and
// the switch (only once the address is confirmed). null: nothing saved.
function showEmailSettings(settings) {
  emailNow = settings;
  emailBox.value = settings !== null && settings.email !== null ? settings.email : "";
  drawEmailState();
}

// The line under the box. Words with a value of their own (the address), so
// not data-words: written again by whenLanguageChanges below.
function drawEmailState() {
  const settings = emailNow;
  const saved = settings !== null && settings.email !== null;
  if (!saved) {
    emailStateLine.textContent = say("email_state_none");
  } else if (!settings.confirmed) {
    emailStateLine.textContent = say("email_state_unconfirmed", { email: settings.email });
  } else {
    emailStateLine.textContent = say("email_state_confirmed", { email: settings.email });
  }
  emailRemoveButton.hidden = !saved;
  replyEmailsRow.hidden = !(saved && settings.confirmed);
  replyEmailsBox.checked = saved && settings.reply_emails;
}

whenLanguageChanges(drawEmailState);

// The login has ended: show the Log in form, and the server's reason.
async function emailLoginEnded(answer) {
  showSignedOut("");
  showProblem(answer);
  await reloadTimeline();
}

// Save was pressed: send the address. The server saves it unconfirmed, and
// prints a confirm email in its terminal.
async function saveEmail(event) {
  event.preventDefault();
  const address = emailBox.value.trim();
  // A quick check on the page. The server checks the same rules again.
  const problem = emailProblem(address);
  if (problem !== null) {
    showStatus(problem.key, problem.values);
    return;
  }
  try {
    const response = await fetch("/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: address }),
    });
    const answer = await response.json();
    if (response.status === 401) {
      await emailLoginEnded(answer);
      return;
    }
    if (!response.ok) {
      // The server refused it, and says which rule was broken. One confirm
      // email per 5 minutes: on 429, Save is turned off for the seconds it says.
      showProblem(answer);
      if (response.status === 429) holdForm(emailForm, answer.retry_after);
      return;
    }
    showEmailSettings(answer);
    showStatus("email_saved");
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// Remove was pressed: the server forgets the address.
async function removeEmail() {
  try {
    const response = await fetch("/email", { method: "DELETE" });
    const answer = await response.json();
    if (response.status === 401) {
      await emailLoginEnded(answer);
      return;
    }
    if (!response.ok) {
      showProblem(answer);
      await askEmailSettings();
      return;
    }
    showEmailSettings(answer);
    showStatus("email_removed");
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// The switch was pressed. As with the heart, the method says what happens:
// POST turns reply emails on, DELETE turns them off. The page never sends true or false.
async function switchReplyEmails() {
  const on = replyEmailsBox.checked;
  try {
    const response = await fetch("/reply-emails", {
      method: on ? "POST" : "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const answer = await response.json();
    if (response.status === 401) {
      await emailLoginEnded(answer);
      return;
    }
    if (!response.ok) {
      showProblem(answer);
      drawEmailState();   // the switch goes back to how the server last said
      return;
    }
    showEmailSettings(answer);
    if (answer.reply_emails) {
      showStatus("reply_emails_on");
    } else {
      showStatus("reply_emails_off");
    }
  } catch (error) {
    showStatus("cannot_reach");
    drawEmailState();
  }
}

// The page was opened from a confirm link (#confirm-email=<token>): send the
// token to the server. It works whether or not this window is logged in,
// because the token alone proves the person can read the email.
async function confirmEmailFromLink() {
  if (!location.hash.startsWith(CONFIRM_START)) {
    return;
  }
  const token = location.hash.slice(CONFIRM_START.length);
  // Take the token out of the address bar at once, so it is not kept in the
  // browser's history or copied with the address. A link works only once anyway.
  history.replaceState(null, "", location.pathname + location.search);
  try {
    const response = await fetch("/email-confirmations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token }),
    });
    const answer = await response.json();
    if (!response.ok) {
      showProblem(answer);
      return;
    }
    showStatus("email_confirmed");
    // The answer is about the link's owner. Show this window's own settings,
    // asked with its own login, which may be someone else's.
    if (account !== null) {
      await askEmailSettings();
    }
  } catch (error) {
    showStatus("cannot_reach");
  }
}

// ---- classic-style: a coloured circle with a letter on the left of each post ----
//
// There are no pictures of people, so each post shows a circle with the first
// letter of the display name. The circle is only a picture: it has no words
// of its own (so nothing for words.js), and a screen reader skips it, because
// the name is read just after it. components.css places it and gives it its colour.

// Which of the six circle colours (1 to 6) this account has. It adds up the
// character codes of the account name, so the same name always gets the same
// colour, in every window and every browser. Capitals are ignored, because
// @Aiko and @aiko are the same account.
function avatarColour(accountName) {
  let total = 0;
  for (const character of accountName.toLowerCase()) {
    total = total + character.codePointAt(0);
  }
  return (total % 6) + 1;
}

// The circle, first in the head slot. The post gets the class "with-avatar",
// so components.css makes room for the circle only on a post that has one.
addPostPart(function avatarPart(post, slots, item) {
  const avatar = document.createElement("span");
  avatar.className = "avatar avatar-colour-" + avatarColour(post.author);
  avatar.setAttribute("aria-hidden", "true");
  // Array.from keeps an emoji or a rare character in one piece.
  const letter = Array.from(post.display_name || post.author)[0] || "";
  avatar.textContent = letter.toUpperCase();   // a letter of a name: never a key
  slots.head.prepend(avatar);
  item.classList.add("with-avatar");
});

textBox.addEventListener("input", updateCount);
textBox.addEventListener("input", saveDraft);
timeline.addEventListener("click", clickOnTimeline);
blockedList.addEventListener("click", clickOnBlockedList);
postForm.addEventListener("submit", sendPost);
cancelReplyButton.addEventListener("click", cancelReply);
loginForm.addEventListener("submit", logIn);
signupForm.addEventListener("submit", signUp);
logoutButton.addEventListener("click", logOut);
emailForm.addEventListener("submit", saveEmail);             // reply-email
emailRemoveButton.addEventListener("click", removeEmail);
replyEmailsBox.addEventListener("change", switchReplyEmails);
// A confirm link pasted into a tab that already shows Timeline changes only the
// part after #, and the page is not loaded again: so listen for that too.
window.addEventListener("hashchange", confirmEmailFromLink);
themeSwitch.value = savedTheme();
placeBox.value = rememberedPlace();
themeSwitch.addEventListener("change", chooseTheme);
languageButton.addEventListener("click", function () {
  setLanguage(language === "ja" ? "en" : "ja");
});
language = chooseLanguage();
addView("timeline", "view_timeline");
setUpBookmarks();
showView("timeline");
// search: its own view, and its own listeners. The results list uses the
// same click handler as the timeline, so who-liked and Show more work there.
addView("search", "results_view");
showResultsTitle();
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
showWords();
newPostsButton.addEventListener("click", pressNewPosts);
loadOlderButton.addEventListener("click", loadOlderPosts);
// Who is logged in first, then the posts: so the first posts are drawn with
// the right Block items in their menus (block).
askWhoIAm().then(function () {
  askForReports();   // report
  confirmEmailFromLink();   // reply-email: after who is logged in, so its words stay
  watchTheBottom();
  keepChecking();
});
setInterval(refreshTimes, 30000);   // every 30 seconds: the smallest step shown is a minute
