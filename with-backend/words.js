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
  // rate-limit
  post_too_fast: {
    en: "Too many posts. Please try again in {seconds} seconds.",
  },
  like_too_fast: {
    en: "Too many likes. Please try again in {seconds} seconds.",
  },
  login_too_fast: {
    en: "Too many wrong passwords for this account. Please try again in {seconds} seconds.",
  },
  signup_too_fast: {
    en: "Too many new accounts. Please try again in {seconds} seconds.",
  },
};
