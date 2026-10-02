// Every word the page shows, by key. Nothing else lives in this file.
//
// app.js never writes a word of its own: it asks for one with say("key").
// index.html names its words with data-words="key", and keeps the English
// inside the element, so the page reads well even before app.js runs.
//
// A key that is also a code in PROBLEMS (server.py) must have exactly the same
// English here: the server sends the code, and the page shows these words.
// {limit} is a value, filled in by say(); the name inside {…} is the same word
// as in Python.
//
// Every entry has this one shape, so test_server.py can read the file:
//
//   key: {
//     en: "English words.",
//   },
//
// Japanese comes later (japanese Part B): one `ja:` line under each `en:`.
// Until then, write `en:` only. A new feature adds its keys at the end, under
// a comment with its own name.
const WORDS = {
  // accounts: refusals, the same codes and English as PROBLEMS in server.py
  name_empty: {
    en: "The name must not be empty.",
  },
  name_too_long: {
    en: "The name must be {limit} characters or fewer.",
  },
  name_characters: {
    en: "The account name may use only letters, numbers and _.",
  },
  name_taken: {
    en: "That account name is taken.",
  },
  display_name_too_long: {
    en: "The display name must be {limit} characters or fewer.",
  },
  display_name_hidden: {
    en: "The display name must not have hidden characters or line breaks.",
  },
  password_too_short: {
    en: "The password must be at least {limit} characters.",
  },
  password_too_long: {
    en: "The password must be {limit} characters or fewer.",
  },
  text_empty: {
    en: "The post must not be empty.",
  },
  text_too_long: {
    en: "The post must be {limit} characters or fewer.",
  },
  like_post_id_missing: {
    en: "The like must say which post it is for.",
  },
  post_missing: {
    en: "That post does not exist.",
  },
  like_already: {
    en: "You have already liked that post.",
  },
  like_not_there: {
    en: "You have not liked that post.",
  },
  login_wrong: {
    en: "The account name or password is wrong.",
  },
  login_needed: {
    en: "Please log in first.",
  },
  login_ended: {
    en: "Your login has ended. Please log in again.",
  },
  // the controller's own refusals
  after_not_number: {
    en: "'after' must be a whole number.",
  },
  not_json: {
    en: "The request must be JSON.",
  },
  not_json_object: {
    en: "The request must be a JSON object.",
  },
  file_missing: {
    en: "The file {file} is missing.",
  },
  // groundwork: refusals
  nothing_here: {
    en: "There is nothing to {method} at {path}.",
  },
  request_too_big: {
    en: "The request is too big.",
  },
  // accounts: the words of the page
  app_name: {
    en: "Timeline",
  },
  log_in_heading: {
    en: "Log in",
  },
  log_in_button: {
    en: "Log in",
  },
  sign_up_heading: {
    en: "Sign up",
  },
  sign_up_button: {
    en: "Sign up",
  },
  account_name_label: {
    en: "Account name",
  },
  password_label: {
    en: "Password",
  },
  new_password_label: {
    en: "Password ({min} characters or more)",
  },
  display_name_label: {
    en: "Display name",
  },
  display_name_example: {
    en: "Aiko Tanaka",
  },
  signed_in_as: {
    en: "Signed in as",
  },
  log_out: {
    en: "Log out",
  },
  post_prompt: {
    en: "What is happening?",
  },
  post_button: {
    en: "Post",
  },
  timeline_label: {
    en: "Posts, newest first",
  },
  like_label: {
    en: "Like this post",
  },
  unlike_label: {
    en: "Unlike this post",
  },
  cannot_reach: {
    en: "Cannot reach the server. Trying again every second.",
  },
  login_fields_empty: {
    en: "Please type your account name and your password.",
  },
  login_to_like: {
    en: "Please log in to like a post.",
  },
  // groundwork: the words of the page
  views_label: {
    en: "Views",
  },
  view_timeline: {
    en: "Timeline",
  },
  post_menu_label: {
    en: "More actions for this post",
  },
  // dark-mode
  theme_label: {
    en: "Colours",
  },
  theme_auto: {
    en: "Auto (follow this computer)",
  },
  theme_light: {
    en: "Light",
  },
  theme_dark: {
    en: "Dark",
  },
  // drafts
  draft_back: {
    en: "Your unsent post is back.",
  },
  // japanese: the language button always shows the other language, in its own words
  switch_language: {
    en: "日本語",
  },
  // long-posts
  show_more: {
    en: "Show more",
  },
  show_less: {
    en: "Show less",
  },
  // who-liked: refusals
  post_ids_missing: {
    en: "The request must say which posts it is about.",
  },
  post_ids_too_many: {
    en: "One request may ask about at most {limit} posts.",
  },
  // who-liked: the line under a post, and the list
  liked_you: {
    en: "You",
  },
  liked_by_one: {
    en: "{first} liked this post",
  },
  liked_by_two: {
    en: "{first} and {second} liked this post",
  },
  liked_by_two_and_others_one: {
    en: "{first}, {second}, and {count} other liked this post",
  },
  liked_by_two_and_others_other: {
    en: "{first}, {second}, and {count} others liked this post",
  },
  liked_by_one_and_others_one: {
    en: "{first} and {count} other liked this post",
  },
  liked_by_one_and_others_other: {
    en: "{first} and {count} others liked this post",
  },
  liked_by_others_one: {
    en: "{count} person liked this post",
  },
  liked_by_others_other: {
    en: "{count} people liked this post",
  },
  likers_none: {
    en: "No likes yet.",
  },
  likers_more_one: {
    en: "and {count} more",
  },
  likers_more_other: {
    en: "and {count} more",
  },
  likers_show: {
    en: "Show who liked this post",
  },
  // timestamps
  time_just_now: {
    en: "just now",
  },
  time_date_unknown: {
    en: "{time} \u00b7 date unknown",
  },
  time_before_dates: {
    en: "Posted before Timeline kept dates",
  },
  // rate-limit: a word with a number is two keys, _one and _other
  post_too_fast_one: {
    en: "Too many posts. Please try again in {count} second.",
  },
  post_too_fast_other: {
    en: "Too many posts. Please try again in {count} seconds.",
  },
  like_too_fast_one: {
    en: "Too many likes. Please try again in {count} second.",
  },
  like_too_fast_other: {
    en: "Too many likes. Please try again in {count} seconds.",
  },
  login_too_fast_one: {
    en: "Too many wrong passwords for this account. Please try again in {count} second.",
  },
  login_too_fast_other: {
    en: "Too many wrong passwords for this account. Please try again in {count} seconds.",
  },
  signup_too_fast_one: {
    en: "Too many new accounts. Please try again in {count} second.",
  },
  signup_too_fast_other: {
    en: "Too many new accounts. Please try again in {count} seconds.",
  },
  // search: refusals
  search_empty: {
    en: "Type a word to search for.",
  },
  search_too_long: {
    en: "A search must be {limit} characters or fewer.",
  },
  search_too_many_words: {
    en: "A search may have at most {limit} words.",
  },
  // search: the words of the page
  search_label: {
    en: "Search posts",
  },
  search_placeholder: {
    en: "a word or #tag",
  },
  search_button: {
    en: "Search",
  },
  results_none: {
    en: "No posts with “{query}”.",
  },
  results_one: {
    en: "{count} post with “{query}”.",
  },
  results_other: {
    en: "{count} posts with “{query}”.",
  },
  results_more: {
    en: "Showing the newest {count} posts with “{query}”.",
  },
  results_start: {
    en: "Type a word or #tag in the search box above.",
  },
  results_view: {
    en: "Search results",
  },
  results_heart: {
    en: "Open the timeline to like",
  },
  results_back: {
    en: "Back to the timeline",
  },
  results_label: {
    en: "Search results, newest first",
  },
  // timeline-flow: refusals
  before_and_after: {
    en: "Ask for 'before' or 'after', not both.",
  },
  id_bound_not_number: {
    en: "'{name}' must be a whole number, 0 or more.",
  },
  // timeline-flow: the words of the page
  new_posts_one: {
    en: "{count} new post",
  },
  new_posts_other: {
    en: "{count} new posts",
  },
  show_older: {
    en: "Show older posts",
  },
  loading_older: {
    en: "Loading…",
  },
  no_older: {
    en: "No older posts.",
  },
  // bookmarks: refusals
  bookmark_post_id_missing: {
    en: "The bookmark must say which post it is for.",
  },
  bookmark_already: {
    en: "You have already bookmarked that post.",
  },
  bookmark_not_there: {
    en: "You have not bookmarked that post.",
  },
  // bookmarks: the words of the page
  bookmark_add: {
    en: "Bookmark this post",
  },
  bookmark_remove: {
    en: "Remove bookmark",
  },
  bookmark_log_in: {
    en: "Please log in to bookmark a post.",
  },
  bookmarks_view: {
    en: "My bookmarks",
  },
  bookmarks_list: {
    en: "Your bookmarks, newest post first",
  },
  bookmarks_empty: {
    en: "You have no bookmarks yet. Press ☆ on a post to save it.",
  },
  // place: refusals
  place_too_long: {
    en: "The place must be {limit} characters or fewer.",
  },
  place_hidden: {
    en: "The place must not have hidden characters or line breaks.",
  },
  // place: the words of the page
  place_label: {
    en: "Place (anyone can see this)",
  },
  place_example: {
    en: "Osaka",
  },
  post_place: {
    en: "\u00b7 {place}",
  },
  // pictures: refusals
  picture_wrong_kind: {
    en: "The picture must be a PNG, JPEG, GIF or WebP file.",
  },
  picture_too_big: {
    en: "The picture must be {limit} MB or smaller.",
  },
  picture_unreadable: {
    en: "The picture could not be read.",
  },
  picture_missing: {
    en: "Please choose a picture for this description.",
  },
  picture_alt_empty: {
    en: "Please describe the picture in a few words.",
  },
  picture_alt_too_long: {
    en: "The description must be {limit} characters or fewer.",
  },
  picture_alt_hidden: {
    en: "The description must not have hidden characters or line breaks.",
  },
  // pictures: the words of the page
  picture_label: {
    en: "Picture (optional): PNG, JPEG, GIF or WebP, up to {size} MB",
  },
  picture_alt_label: {
    en: "Describe the picture for people who cannot see it",
  },
  picture_hint: {
    en: "A JPEG photo is drawn again before it is sent, so the place where it was taken is not shared.",
  },
  // block: refusals
  account_missing: {
    en: "There is no account @{name}.",
  },
  block_self: {
    en: "You cannot block yourself.",
  },
  block_already: {
    en: "You have already blocked @{name}.",
  },
  block_not_there: {
    en: "You have not blocked @{name}.",
  },
  like_blocked: {
    en: "You cannot like this post.",
  },
  // block: the words of the page
  block_menu: {
    en: "Block @{name}",
  },
  block_confirm: {
    en: "Block @{name}? You will no longer see their posts.",
  },
  block_done: {
    en: "You blocked @{name}. Their posts are hidden.",
  },
  block_log_in: {
    en: "Please log in to block an account.",
  },
  blocked_accounts: {
    en: "Blocked accounts",
  },
  unblock_button: {
    en: "Unblock",
  },
  unblock_label: {
    en: "Unblock @{name}",
  },
  unblock_done: {
    en: "You unblocked @{name}.",
  },
  // replies: refusals
  reply_parent_id_missing: {
    en: "The reply must say which post it answers.",
  },
  reply_to_reply: {
    en: "You can only reply to a post, not to a reply.",
  },
  reply_blocked: {
    en: "You cannot reply to this post.",
  },
  // replies: the words of the page
  reply_button: {
    en: "Reply",
  },
  reply_button_label: {
    en: "Reply to @{name}",
  },
  replying_to: {
    en: "Replying to @{name}",
  },
  reply_cancel: {
    en: "Cancel",
  },
  reply_count_one: {
    en: "{count} reply",
  },
  reply_count_other: {
    en: "{count} replies",
  },
  replies_label: {
    en: "Replies to @{name}",
  },
  reply_log_in: {
    en: "Please log in to reply.",
  },
};
