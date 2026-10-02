// Timeline, the version WITH a backend.
//
// This page keeps nothing itself. It sends each new post, each like and each
// like taken back to the server (server.py), and every second it asks the
// server: "anything new?"
// Because every window asks the same server, every window sees every post.

const MAX_TEXT = 280;
const CANNOT_REACH = "Cannot reach the server. Trying again every second.";

const authorBox = document.getElementById("author");
const textBox = document.getElementById("text");
const countLine = document.getElementById("count");
const statusLine = document.getElementById("status");
const timeline = document.getElementById("timeline");
const postForm = document.getElementById("post-form");

// The id of the newest post this window has shown. 0 means "none yet".
let lastId = 0;

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

  const author = document.createElement("span");
  author.className = "post-author";
  author.textContent = post.author;

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
  item.append(author, time, text, likeRow);
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

// The live count under the box: "x / 280".
function updateCount() {
  const length = textBox.value.length;
  countLine.textContent = length + " / " + MAX_TEXT;
  countLine.classList.toggle("too-long", length > MAX_TEXT);
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
    // asked for separately, and all of them come back each time.
    const likesAnswer = await fetch("/likes?author=" + encodeURIComponent(authorBox.value));
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

// Send a new post to the server.
async function sendPost(event) {
  event.preventDefault();
  const author = authorBox.value;
  const text = textBox.value;

  // A quick check on the page, so the person does not wait for an answer.
  // The server checks the same rules again. Never trust only the screen:
  // anyone can send a request without using this page at all.
  if (text.trim() === "") {
    showStatus("The post must not be empty.");
    return;
  }

  try {
    const response = await fetch("/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author: author, text: text }),
    });
    const answer = await response.json();
    if (!response.ok) {
      // The server refused the post. It says which rule was broken.
      showStatus(answer.error);
      return;
    }
    // Saved. Ask for new posts now, instead of waiting for the next second.
    // This also brings in any post from another window that came just before ours.
    showStatus("");
    textBox.value = "";
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
  const author = authorBox.value;

  // A quick check on the page, so the person does not wait for an answer. The
  // server checks the same rule again: anyone can send a request without using
  // this page at all.
  if (author.trim() === "") {
    showStatus("The name must not be empty.");
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
      body: JSON.stringify({ author: author, post_id: postId }),
    });
    const answer = await response.json();
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

// One handler for the whole timeline, so a post added later works too.
function clickOnTimeline(event) {
  const button = event.target.closest(".like");
  if (button !== null) {
    pressHeart(Number(button.dataset.postId));
  }
}

textBox.addEventListener("input", updateCount);
timeline.addEventListener("click", clickOnTimeline);
postForm.addEventListener("submit", sendPost);
keepChecking();
