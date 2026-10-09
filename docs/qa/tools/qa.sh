# QA helpers for docs/qa/RUNBOOK.md. Load them into your shell first:
#
#   source docs/qa/tools/qa.sh
#
# Settings (change them before `source` if you need to):
#   QA_BASE   the server to test            (default http://localhost:8011)
#   QA_RUN    where this run's files go     (default docs/qa/runs/<today>)
#   QA_LOG    the file the server prints to (default $QA_RUN/server.log)
#
# Each person has their own cookie jar, like their own browser.
#   step G2 "Blocked posts leave the blocker's timeline"   start a check
#   as aiko POST /blocks '{"account_name":"dan"}'          one request as aiko ("anon" = nobody)
#   note "the count stays 3"                               a line in the transcript
#   card                                                   screenshot of this step's requests
#   page aiko / timeline                                   screenshot of the page as aiko
#   log_card emails 'EMAIL' 40                             screenshot of the server's terminal

QA_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QA_BASE="${QA_BASE:-http://localhost:8011}"
QA_RUN="${QA_RUN:-docs/qa/runs/$(date +%Y-%m-%d)}"
QA_LOG="${QA_LOG:-$QA_RUN/server.log}"
QA_JARS="${QA_JARS:-${TMPDIR:-/tmp}/qa-jars}"
mkdir -p "$QA_RUN" "$QA_JARS"
QA_STEP="${QA_STEP:-setup}"
QA_STEP_FILE="$QA_JARS/.step.txt"
: > "$QA_STEP_FILE"

step() {
  _block_open && done_step
  QA_STEP="$1"; QA_TITLE="$2"
  : > "$QA_STEP_FILE"
  printf '\n=== %s  %s ===\n' "$1" "$2"
  printf '\n### %s %s\n\n```\n' "$1" "$2" >> "$QA_RUN/transcript.md"
}

# Close the code block a step opened. Called by the next step, a card, or `done_step`.
done_step() { printf '```\n' >> "$QA_RUN/transcript.md"; }

# True when the transcript has an odd number of ``` lines: a step is still open.
_block_open() {
  local fences
  [ -f "$QA_RUN/transcript.md" ] || return 1
  fences=$(grep -c '^[`][`][`]' "$QA_RUN/transcript.md")
  [ $((fences % 2)) -eq 1 ]
}

as() {
  local who="$1" method="$2" path="$3" body="$4" jar code
  if [ "$who" = anon ]; then jar=/dev/null; else jar="$QA_JARS/$who"; fi
  local args=(-s -o "$QA_JARS/.body" -w '%{http_code} %{content_type}' -b "$jar" -X "$method")
  [ "$who" != anon ] && args+=(-c "$jar")
  [ -n "$body" ] && args+=(-H 'Content-Type: application/json' --data "$body")
  code=$(curl "${args[@]}" "$QA_BASE$path")
  local kind="${code#* }"; code="${code%% *}"
  local line="[$who] $method $path${body:+ $(printf '%s' "$body" | head -c 200)}"
  local answer
  case "$kind" in
    application/json*|text/*|"") answer="  -> $code $(head -c 500 "$QA_JARS/.body" | LC_ALL=C tr -d '\000-\010\016-\037')" ;;
    *) answer="  -> $code <$kind, $(wc -c < "$QA_JARS/.body" | tr -d ' ') bytes>" ;;
  esac
  printf '%s\n%s\n' "$line" "$answer" | tee -a "$QA_STEP_FILE" >> "$QA_RUN/transcript.md"
  printf '%s\n%s\n' "$line" "$answer"
}

note() {
  printf '# %s\n' "$*" | tee -a "$QA_STEP_FILE" >> "$QA_RUN/transcript.md"
  printf '# %s\n' "$*"
}

# The session token in a person's cookie jar, or "-" for nobody.
token() {
  [ "$1" = anon ] && { echo -; return; }
  awk '$6 == "session" { t = $7 } END { print (t == "" ? "-" : t) }' "$QA_JARS/$1" 2>/dev/null
}

_html_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

_card_html() {   # title, body file, out html
  {
    printf '<!doctype html><meta charset="utf-8"><style>'
    printf 'body{margin:0;background:#0f172a;color:#e2e8f0;font:14px/1.5 ui-monospace,Menlo,monospace}'
    printf 'header{padding:12px 20px;background:#1e293b;font:600 15px system-ui}'
    printf 'header small{color:#94a3b8;font-weight:400;margin-left:12px}'
    printf 'pre{margin:0;padding:16px 20px;white-space:pre-wrap;word-break:break-all}'
    printf '.ok{color:#86efac}.bad{color:#fca5a5}.who{color:#93c5fd}.note{color:#fde68a}'
    printf '</style><header>%s<small>%s</small></header><pre>' \
      "$(printf '%s' "$1" | _html_escape)" "$(date '+%Y-%m-%d %H:%M:%S %Z')  $QA_BASE"
    _html_escape < "$2" | sed -E \
      -e 's/^(\[[a-z0-9_]+\])/<span class="who">\1<\/span>/' \
      -e 's/^(  -&gt; [23][0-9][0-9])/<span class="ok">\1<\/span>/' \
      -e 's/^(  -&gt; [45][0-9][0-9])/<span class="bad">\1<\/span>/' \
      -e 's/^(# .*)$/<span class="note">\1<\/span>/'
    printf '</pre>'
  } > "$3"
}

# A screenshot of every request and answer in this step so far.
card() {
  local name="${1:-requests}" html="$QA_JARS/.card.html"
  _card_html "$QA_STEP  $QA_TITLE" "$QA_STEP_FILE" "$html"
  node "$QA_HERE/shoot.mjs" file "$html" "$QA_RUN/$QA_STEP-$name.png" 1000 >/dev/null \
    && echo "screenshot: $QA_RUN/$QA_STEP-$name.png"
  printf '[screenshot %s-%s.png]\n' "$QA_STEP" "$name" >> "$QA_RUN/transcript.md"
}

# A screenshot of the page itself, as one person sees it.
page() {
  local who="$1" path="$2" name="${3:-page}" width="${4:-1280}"
  node "$QA_HERE/shoot.mjs" page "$QA_BASE$path" "$QA_RUN/$QA_STEP-$name.jpg" \
    "$(token "$who")" "$width" >/dev/null \
    && echo "screenshot: $QA_RUN/$QA_STEP-$name.jpg"
  printf '[screenshot %s-%s.jpg: the page as %s]\n' "$QA_STEP" "$name" "$who" >> "$QA_RUN/transcript.md"
}

# A screenshot of the last lines of the server's terminal (for emails and post lines).
log_card() {
  local name="${1:-terminal}" pattern="${2:-.}" lines="${3:-40}" body="$QA_JARS/.log.txt"
  grep -v '"GET \|"POST \|"DELETE \|"PATCH ' "$QA_LOG" | tail -n "$lines" > "$body"
  _card_html "$QA_STEP  server terminal ($pattern)" "$body" "$QA_JARS/.card.html"
  node "$QA_HERE/shoot.mjs" file "$QA_JARS/.card.html" "$QA_RUN/$QA_STEP-$name.png" 1000 >/dev/null \
    && echo "screenshot: $QA_RUN/$QA_STEP-$name.png"
  printf '[screenshot %s-%s.png: the server terminal]\n' "$QA_STEP" "$name" >> "$QA_RUN/transcript.md"
}

# The ids (and authors) of a list of posts, as one person sees it.
ids() {
  local jar="$QA_JARS/$1"; [ "$1" = anon ] && jar=/dev/null
  local got
  got=$(curl -s -b "$jar" "$QA_BASE$2" | python3 -c '
import json, sys
d = json.load(sys.stdin)
d = d.get("posts", d) if isinstance(d, dict) else d
print(" ".join("%s:%s%s" % (p["id"], p["author"], "(deleted)" if p.get("deleted") else "") for p in d) or "(none)")')
  note "$1 sees $2 -> $got"
}
