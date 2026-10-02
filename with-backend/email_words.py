"""Timeline: the words of every email, in English and in Japanese.

The page has words.js for its words. An email is written by the server, but the
server never holds Japanese in server.py, so the words of an email live here.

Every email has both languages, English first, then Japanese, because the
server does not know which language the reader reads. Every reader gets the
same email. Each entry has `en` and `ja`, with the same {names} in both: a
{name} is a value filled in when the email is written (see both_languages in
server.py). A test checks that both are there, and have the same {names}.

The Japanese is written in plain, very casual Japanese (タメ口), as the page's
Japanese will be. NATIVE-SPEAKER CHECK: japanese Part B's check by hand reads
every `ja` line in this file too, not only words.js.
"""

EMAIL_WORDS = {
    # reply-email: someone replied to your post
    "reply_subject": {
        "en": "{display_name} (@{account_name}) replied to your post",
        "ja": "{display_name} (@{account_name}) から返信きたよ",
    },
    "reply_body": {
        "en": ("{display_name} (@{account_name}) replied to your post.\n"
               "\n"
               "Their reply:\n"
               "{reply}\n"
               "\n"
               "Your post:\n"
               "{post}\n"
               "\n"
               "See it: {link}\n"
               "\n"
               "To stop these emails, turn off \"Email me when someone replies\" on Timeline."),
        "ja": ("{display_name} (@{account_name}) があなたの投稿に返信したよ。\n"
               "\n"
               "返信:\n"
               "{reply}\n"
               "\n"
               "あなたの投稿:\n"
               "{post}\n"
               "\n"
               "見てみて: {link}\n"
               "\n"
               "このメールがいらなかったら、Timeline で返信メールをオフにしてね。"),
    },
    # reply-email: confirm that this address is yours
    "confirm_subject": {
        "en": "Confirm your email address for Timeline",
        "ja": "Timeline のメアド確認してね",
    },
    "confirm_body": {
        "en": ("To confirm this address, copy this link into your browser:\n"
               "{link}\n"
               "\n"
               "The link works once, for {hours} hours. "
               "If you did not ask for this, ignore this email."),
        "ja": ("このアドレスを確認するなら、このリンクをブラウザにコピーしてね:\n"
               "{link}\n"
               "\n"
               "リンクは1回だけ、{hours}時間使えるよ。"
               "心当たりがなかったら、このメールは無視してOK！"),
    },
}
