#!/bin/bash
# safe_commit.sh - the only way a session should commit to the vault.
#
# WHY IT EXISTS. People run several Claude sessions against one folder at once, often
# with subagents. Two things then go wrong that plain git does not protect you from.
#
#   THE PUSH RACE. Another session pushed while this one was working, so the push is
#   rejected. This script rebases onto whatever is on the remote, refuses to proceed
#   over conflict markers, runs the gates, and retries the push.
#
#   THE STAGING RACE. `git add -A` stages the entire working tree, so a session
#   commits files it never opened: one session's work lands inside another's commit,
#   the gates run over a mixed changeset and bless pages nobody read, and a
#   half-written page gets published by a session with no idea it was mid-edit. So:
#   NAME THE FILES YOU TOUCHED. A session always knows. `--all` still exists for a
#   genuine sweep, and it prints exactly what it is about to take, so a sweep is a
#   decision instead of an accident.
#
# The lock serializes the commit-and-push window so two sessions cannot interleave.
# It is advisory and self-healing: a lock older than LOCK_STALE_MIN is assumed to
# belong to a session that died and is broken. It lives in the COMMON git directory,
# so the main folder and every linked worktree queue against one lock.
#
# The push sends HEAD to main, which is what makes this work from a worktree too. Off
# main the script refuses if the branch already carries commits the remote lacks,
# because those would be published alongside yours.
#
# NO REMOTE. A repository with no `origin` is a valid setup (a local-only brain). The script
# then skips the pull, the fetch and the push, commits locally, and says the push was skipped.
#
# THE GATE TRAVELS WITH THE REPOSITORY. hooks/pre-commit is tracked, because git does not
# clone anything under .git/hooks. Before a commit this script asks git where it will look for
# the hook (`git rev-parse --git-path hooks/pre-commit`, which honours core.hooksPath and
# worktrees) and installs the tracked copy there when nothing executable is present. A clone
# that already has a hook is never overwritten; a hook whose checks differ from the tracked
# one is named in a single line. If the gate can be neither installed nor run, the commit is
# refused loudly: a commit nothing checked must never look like a gated one.
#
# THE ESCAPE HATCH, WITH ITS RECEIPT. `--no-verify="<why>"` skips the pre-commit gate for a
# lint.py or connect.py finding you have READ and decided to accept, never for one nobody has
# looked at. Everything on that path keeps the two apart:
#   - the reason is attached to the flag, so it cannot be swapped with the commit message;
#   - an empty reason is refused, and so is one under REASON_MIN_CHARS characters;
#   - --no-verify together with --all is refused: a whole-tree sweep that also skips the gate
#     is the two riskiest things this script can do, at once;
#   - the record is MECHANICAL: the script runs lint.py and connect.py itself, against the
#     index the skipped gate would have seen, and appends their actual finding lines to
#     wiki/log.md, staged into the SAME commit as the thing it excuses;
#   - if that record cannot be written, nothing is committed.
# A tally of the finding kinds is printed, rarest first, split into the tags that would have
# BLOCKED and ADVISORY_TAGS that never stop a commit. An unknown tag counts as blocking, so a
# stale list costs a spurious warning, never a silent miss.
#
# THE LEDGER MERGE DRIVER. wiki/_reminders.md is written by several sessions at once. The
# driver in tools/ledger_merge.py merges two sides that each only ADD rows (see .gitattributes).
# Git never copies a driver with the repository, so this script registers it in the clone on
# every run. Idempotent; a clone without it gets git's normal merge.
#
# USAGE (run the copy in the checkout you edited):
#   ./tools/safe_commit.sh "message" wiki/people/sam-rivera.md wiki/log.md
#   ./tools/safe_commit.sh --all "message"      # a deliberate whole-tree sweep
#   ./tools/safe_commit.sh --no-verify="<why the finding is accepted>" "message" <files>
#   ./tools/safe_commit.sh --commit-before-pull "message" <files>   # gate first, then publish
set -e

# Where the caller is standing, read before the cd below moves to this script's own
# checkout. The two differ when a session in one checkout runs another's copy.
if CALLER_TREE=$(git rev-parse --show-toplevel 2>/dev/null); then
  CALLER_COMMON=$(cd "$CALLER_TREE" && cd "$(git rev-parse --git-common-dir)" && pwd -P) || CALLER_COMMON=""
  CALLER_TREE=$(cd "$CALLER_TREE" && pwd -P)
else
  CALLER_TREE=""
  CALLER_COMMON=""
fi

cd "$(dirname "$0")/.."
THIS_TREE=$(pwd -P)

GIT_COMMON_DIR=$(git rev-parse --git-common-dir) || exit 1
GIT_COMMON_DIR=$(cd "$GIT_COMMON_DIR" && pwd -P)
LOCK_DIR="$GIT_COMMON_DIR/second-brain-commit.lock"
LOCK_STALE_MIN=10
LOCK_WAIT_MAX_S=120
LOCK_TOKEN="$$.$RANDOM.$(date +%s)"

COMMIT_FIRST=${SECOND_BRAIN_COMMIT_BEFORE_PULL:-0}
STAGE_ALL=0
NO_VERIFY=0
NO_VERIFY_REASON=""
REASON_MIN_CHARS=30
LOG_FILE="wiki/log.md"

usage() {
  echo "usage: safe_commit.sh \"message\" <file> [file...]"
  echo "       safe_commit.sh --commit-before-pull \"message\" <file> [file...]"
  echo "       safe_commit.sh --all \"message\"    # deliberate whole-tree sweep"
  echo "       safe_commit.sh --no-verify=\"<why this finding is accepted>\" \"message\" <file> [file...]"
  echo ""
  echo "  --no-verify=\"<reason>\" skips the pre-commit gate for a lint.py or connect.py finding"
  echo "  this session has READ and decided to accept - never for one nobody has looked at."
  echo "  The reason and the exact lines lint.py and connect.py print are written into"
  echo "  $LOG_FILE and committed with your files; if that record cannot be written, nothing"
  echo "  is committed. The reason must be at least $REASON_MIN_CHARS characters, and it cannot"
  echo "  be combined with --all."
  echo "  --commit-before-pull commits (gated) before it takes in the remote's changes, so no"
  echo "  autostash ever touches your edits; the push then replays the commit onto the remote."
}

while [ $# -gt 0 ]; do
  case "$1" in
    --commit-before-pull)
      COMMIT_FIRST=1
      shift ;;
    --all)
      STAGE_ALL=1
      shift ;;
    --no-verify=*)
      NO_VERIFY=1
      NO_VERIFY_REASON="${1#--no-verify=}"
      shift ;;
    --no-verify)
      echo "x --no-verify needs its reason attached to the flag, like this:"
      echo "      ./tools/safe_commit.sh --no-verify=\"<why you are accepting it>\" \"<message>\" <files>"
      echo "  Taking the reason as the next argument would make it swappable with the commit"
      echo "  message, and nothing could tell the two apart afterwards. Nothing was staged,"
      echo "  committed or pushed."
      exit 1 ;;
    *)
      break ;;
  esac
done

MSG="$1"
shift || true
FILES=("$@")

if [ -z "$MSG" ]; then
  usage
  exit 1
fi

# Trimmed at both ends before it is measured, so a reason of spaces is an empty reason.
NO_VERIFY_REASON=$(printf '%s' "$NO_VERIFY_REASON" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

if [ "$NO_VERIFY" -eq 1 ]; then
  if [ "$STAGE_ALL" -eq 1 ]; then
    echo "x --no-verify cannot be combined with --all."
    echo "  A whole-tree sweep stages files this session never opened; skipping the gate means"
    echo "  nothing checks them. Name the files you actually edited."
    echo "  Nothing was staged, committed or pushed."
    exit 1
  fi
  if [ -z "$NO_VERIFY_REASON" ]; then
    echo "x --no-verify was given with no reason."
    echo "      --no-verify=\"<why this finding is acceptable>\""
    echo "  The reason is what a future session reads to judge whether the override was"
    echo "  honest. Nothing was staged, committed or pushed."
    exit 1
  fi
  if [ ${#NO_VERIFY_REASON} -lt "$REASON_MIN_CHARS" ]; then
    echo "x --no-verify reason is too short (${#NO_VERIFY_REASON} characters; at least $REASON_MIN_CHARS are needed)."
    echo "      given: $NO_VERIFY_REASON"
    echo "  Say which finding you read and why it is acceptable to commit over it. \"fixing later\""
    echo "  is not a reason anybody can check. Nothing was staged, committed or pushed."
    exit 1
  fi
  if [ "$NO_VERIFY_REASON" = "$MSG" ]; then
    echo "! the reason and the commit message are identical - check you have not passed the same"
    echo "  string twice. The reason should say why the gate finding is acceptable, not what the"
    echo "  commit does. Continuing, because both are recorded either way."
  fi
  echo "================================================================================"
  echo "!  --no-verify - THE PRE-COMMIT GATE WILL BE SKIPPED FOR THIS COMMIT"
  echo "   Reason given: $NO_VERIFY_REASON"
  echo "   lint.py and connect.py will be run anyway and what they print will be written"
  echo "   into $LOG_FILE and committed with your files. If that cannot be written,"
  echo "   nothing is committed."
  echo "================================================================================"
fi

if [ "$STAGE_ALL" -eq 0 ] && [ ${#FILES[@]} -eq 0 ]; then
  echo "x No files named, and --all not given."
  echo "  Name the files this session actually edited, so another session's"
  echo "  in-progress work is not swept into your commit. Currently dirty:"
  git status --short | sed 's/^/    /'
  exit 1
fi

# ---------- which checkout, which branch ----------
BRANCH=$(git symbolic-ref -q --short HEAD || true)
# No `origin`: a local-only repository. Pull, fetch and push are all skipped below.
if git remote get-url origin >/dev/null 2>&1; then HAS_REMOTE=1; else HAS_REMOTE=0; fi
MAIN_TREE=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
if [ -n "$MAIN_TREE" ]; then
  MAIN_TREE=$(cd "$MAIN_TREE" 2>/dev/null && pwd -P) || MAIN_TREE=""
fi

# The wrong copy for where the caller stands: another checkout of this same vault,
# holding edits to the very files named. File names are read in the script's own
# checkout, so this run would commit THAT checkout's versions of them and tell you it
# worked.
if [ -n "$CALLER_TREE" ] && [ "$CALLER_TREE" != "$THIS_TREE" ] \
   && [ "$CALLER_COMMON" = "$GIT_COMMON_DIR" ] && [ ${#FILES[@]} -gt 0 ]; then
  CALLER_EDITS=$(git --no-optional-locks -C "$CALLER_TREE" status --porcelain -- "${FILES[@]}" 2>/dev/null || true)
  if [ -n "$CALLER_EDITS" ]; then
    echo "x WRONG COPY of safe_commit.sh for where you are standing."
    echo "  This copy commits in:  $THIS_TREE"
    echo "  You are in:            $CALLER_TREE (another checkout of the same vault)"
    echo "  and that is where the named files have edits:"
    echo "$CALLER_EDITS" | sed 's/^/      /'
    echo "  Nothing was staged, committed or pushed. Run the copy in your own checkout:"
    echo "      cd \"$CALLER_TREE\" && ./tools/safe_commit.sh \"<message>\" <the same files>"
    exit 1
  fi
fi

# ---------- the lock ----------
lock_age_min() {
  # Minutes since the lock was taken: from its stamp, or, when the holder has not
  # written the stamp yet, from the lock directory itself. A lock taken a moment ago
  # must never read as ancient and get broken.
  local then_s
  then_s=$(cat "$LOCK_DIR/stamp" 2>/dev/null || true)
  case "$then_s" in
    ''|*[!0-9]*) then_s=$(stat -c %Y "$LOCK_DIR" 2>/dev/null || stat -f %m "$LOCK_DIR" 2>/dev/null || true) ;;
  esac
  case "$then_s" in
    ''|*[!0-9]*) ;;
    *) echo $(( ($(date +%s) - then_s) / 60 )) ;;
  esac
}

acquire_lock() {
  local waited=0 age err
  while :; do
    if err=$(mkdir "$LOCK_DIR" 2>&1); then
      break
    fi
    if [ ! -d "$LOCK_DIR" ]; then
      # mkdir failed and there is no lock to wait for. One more try covers a holder
      # that released in between; past that, mkdir cannot work at this path, and
      # reading that as a stale lock is how a wait loop spins forever.
      if err=$(mkdir "$LOCK_DIR" 2>&1); then
        break
      fi
      if [ ! -d "$LOCK_DIR" ]; then
        echo "x cannot create the commit lock: ${err:-mkdir failed and gave no reason}"
        echo "  Lock path: $LOCK_DIR"
        echo "  Refusing instead of retrying. Nothing was staged, committed or pushed."
        exit 1
      fi
    fi
    age=$(lock_age_min)
    if [ -n "$age" ] && [ "$age" -ge "$LOCK_STALE_MIN" ]; then
      echo "! breaking a stale commit lock (${age}m old, the owner probably died)"
      echo "  Owner was: $(cat "$LOCK_DIR/owner" 2>/dev/null || echo unknown)"
      rm -rf "$LOCK_DIR"
      if [ -d "$LOCK_DIR" ]; then
        echo "x could not remove the stale lock at $LOCK_DIR; remove it by hand."
        exit 1
      fi
      continue
    fi
    if [ "$waited" -ge "$LOCK_WAIT_MAX_S" ]; then
      echo "x another session has held the commit lock for $((LOCK_WAIT_MAX_S / 60)) minutes."
      echo "  Owner: $(cat "$LOCK_DIR/owner" 2>/dev/null || echo unknown)"
      echo "  Wait for it to finish, or remove $LOCK_DIR if you know it is dead."
      exit 1
    fi
    [ "$waited" -eq 0 ] && echo "... another session is committing; waiting for the lock"
    sleep 3
    waited=$((waited + 3))
  done
  echo "$LOCK_TOKEN" > "$LOCK_DIR/token"
  date +%s > "$LOCK_DIR/stamp"
  echo "pid $$ - $THIS_TREE - $(date '+%F %T')" > "$LOCK_DIR/owner"
}

# Only a lock THIS run took. Removing the lock on every exit means a run that gave up
# waiting deletes the live lock of the session it was waiting for.
release_lock() {
  if [ "$(cat "$LOCK_DIR/token" 2>/dev/null)" = "$LOCK_TOKEN" ]; then
    rm -rf "$LOCK_DIR"
  fi
}
trap release_lock EXIT

acquire_lock

# One definition of "the tree has markers", used before the pull and after it, so the
# files listed in a refusal are exactly the files that triggered it.
#
# THE SCOPE IS GIT'S OWN PROJECT SET: tracked, plus untracked and not ignored. An
# extension filter here is a trap - a conflicted restore can leave markers in a cache
# file or a data file, and a guard that only reads markdown announces a clean tree and
# lets the commit go out over the corruption. A file git ignores is deliberately left
# out: no git command could clear it, so blocking on one would jam every commit in the
# vault with no way through.
#
# -z out of git and -0 into xargs, so a filename with a space survives whole. -I so
# grep skips binaries instead of reading a large PDF to the end; nothing is lost,
# because a conflicted merge on a binary writes no markers at all. /dev/null as a
# permanent extra operand, so grep always has a file argument and never falls back to
# reading stdin when the list is empty.
#
# The predicate is deliberately strict: EITHER half of a marker pair refuses here.
# This is the last gate before a commit, and half a marker is still an unfinished merge.
marker_files() {
  git ls-files -c -o --exclude-standard -z 2>/dev/null \
    | xargs -0 grep -I -l -e '^<<<<<<< ' -e '^>>>>>>> ' /dev/null 2>/dev/null \
    | sort -u || true
}

# ---------- 0. off main, the branch must carry nothing the remote lacks ----------
# The push sends HEAD to main, so every commit already on this branch would go out
# with this one. Checked BEFORE the pull, so a refused branch is not rebased, stashed
# or staged either.
if [ "$HAS_REMOTE" -eq 1 ] && [ "$BRANCH" != "main" ]; then
  if ! git fetch -q origin main; then
    echo "x could not fetch origin main, so ${BRANCH:-this detached HEAD} cannot be checked against it."
    echo "  Nothing was staged, committed or pushed."
    exit 1
  fi
  EARLIER=$(git log --no-merges --cherry-pick --right-only --format='%h %s' FETCH_HEAD...HEAD)
  if [ -n "$EARLIER" ]; then
    FORK_POINT=$(git merge-base FETCH_HEAD HEAD 2>/dev/null || true)
    echo "x ${BRANCH:-this detached HEAD} already has commits that are not on main:"
    echo "$EARLIER" | sed 's/^/      /'
    echo "  This script publishes HEAD to main, so they would go out with this commit."
    echo "  Nothing was staged, committed or pushed, and the branch was not touched."
    if [ -n "$FORK_POINT" ]; then
      echo "  - If they are this session's own, turn them back into uncommitted edits,"
      echo "    then re-run this script naming every file you want published:"
      echo "        git reset --soft $(git rev-parse --short "$FORK_POINT")"
      echo "    That is where this branch left main. Every edit stays in its file; only"
      echo "    the commits go. Never reset to main itself: that keeps this branch's OLD"
      echo "    copy of every file, and committing one quietly reverts what landed since."
    fi
    echo "  - If they are anyone else's, do not publish them from here. Merging a branch"
    echo "    into main is its own, deliberate step."
    exit 1
  fi
fi

# ---------- 1. sync with whatever other sessions pushed ----------
# Register the ledger's row-aware merge driver in this clone (.gitattributes,
# tools/ledger_merge.py). Without it two writers adding rows to wiki/_reminders.md at the same
# spot jam the autostash pop below. Idempotent; a clone without it gets git's normal merge.
git config merge.ledger-rows.name "ledger rows: both sides only added rows" 2>/dev/null || true
git config merge.ledger-rows.driver "python3 tools/ledger_merge.py %O %A %B" 2>/dev/null || true
STASH_BEFORE=$(git rev-parse -q --verify refs/stash || true)
MARKERS_BEFORE=$(marker_files)

if [ "$HAS_REMOTE" -eq 0 ]; then
  echo "no remote named origin - skipping the pull; this run commits locally only"
elif [ "$COMMIT_FIRST" -eq 1 ]; then
  # Own edits become a gated commit before any operation can autostash them. The push loop
  # below fetches and replays the commit without touching the tree.
  git fetch -q origin main || echo "! fetch failed - committing locally before retrying publication"
else
  git pull --rebase --autostash origin main || {
    echo "x REBASE FAILED - another session's changes conflict with this one."
    echo "  Resolve by hand (git status), and never commit the markers. Aborting."
    git rebase --abort 2>/dev/null || true
    exit 1
  }
fi

# Did THIS pull leave a stash entry behind? `git pull --rebase --autostash` exits 0
# when the rebase succeeds and only the POP conflicts - the rebase did finish - so the
# failure branch above never fires and the markers look like they came from nowhere.
# Compared by sha rather than by counting, because a pre-existing entry must never be
# reported as this run's work.
NEW_STASH=""
NEW_STASH_DESC=""
STASH_AFTER=$(git rev-parse -q --verify refs/stash || true)
if [ -n "$STASH_AFTER" ] && [ "$STASH_AFTER" != "$STASH_BEFORE" ]; then
  STASH_LINE=$(git stash list --format='%gd %H %h %gs' | awk -v s="$STASH_AFTER" '$2 == s {print; exit}')
  if [ -n "$STASH_LINE" ]; then
    NEW_STASH=$(echo "$STASH_LINE" | cut -d' ' -f1)
    NEW_STASH_DESC="$(echo "$STASH_LINE" | cut -d' ' -f3) $(echo "$STASH_LINE" | cut -d' ' -f4-)"
  else
    NEW_STASH="stash@{0}"
    NEW_STASH_DESC="$(git rev-parse --short "$STASH_AFTER") autostash"
  fi
fi

# ---------- 2. refuse conflict markers ----------
MARKERS_NOW=$(marker_files)
if [ -n "$MARKERS_NOW" ]; then
  if [ -n "$NEW_STASH" ] && [ -z "$MARKERS_BEFORE" ]; then
    echo "x AUTOSTASH POP CONFLICTED - the rebase itself SUCCEEDED."
    echo "  git took the other sessions' commits cleanly, then could not put YOUR"
    echo "  uncommitted changes back on top of them. The markers below came from that"
    echo "  restore, not from the rebase, which is why nothing above says it failed:"
    echo "$MARKERS_NOW" | sed 's/^/      /'
    echo "  Your work is not lost. Git kept a copy of it:"
    echo "      $NEW_STASH - $NEW_STASH_DESC, created by this run"
    echo "  and the same work is in the tree above, in conflicted form. The tree is what"
    echo "  you fix; that entry is the backup, and dropping it is the LAST step."
    echo "  In order:"
    echo "    1. resolve the markers in the file(s) above, keeping what belongs;"
    echo "    2. git add <those files> - this marks them resolved. Skip it and the next"
    echo "       run dies at the pull with 'unmerged files' and blames the rebase again;"
    echo "    3. re-run this script with the same file list, and let the push land;"
    echo "    4. ONLY THEN: git stash drop $NEW_STASH"
    echo "       Check 'git stash list' first - that index shifts if anything else"
    echo "       autostashes in between. The entry you want is $NEW_STASH_DESC."
    echo "  Do not skip step 4. An autostash nobody drops sits in the stash list forever,"
    echo "  unlabelled, and no later session can tell whose work it holds."
  else
    echo "x CONFLICT MARKERS present in the tree - fix them first:"
    echo "$MARKERS_NOW"
    [ -n "$NEW_STASH" ] && echo "  (this pull also left $NEW_STASH - $NEW_STASH_DESC - holding your own work; drop it only after the commit lands)"
  fi
  exit 1
fi

if [ -n "$NEW_STASH" ]; then
  # A pop that failed without leaving markers anywhere the scan can see them: a
  # conflict git wrote no markers into (a binary, where git keeps one side whole and
  # marks only the index unmerged), or a pop that refused to start. The run is not
  # blocked, but the entry is named, because the silence is the whole bug.
  echo "! AUTOSTASH NOT POPPED - the rebase succeeded, but git could not restore your"
  echo "  uncommitted changes and kept them in $NEW_STASH ($NEW_STASH_DESC)."
  echo "  No conflict markers turned up in any file git tracks or would add, so this run"
  echo "  goes on - but that scan skips files git ignores and cannot read a binary one."
  echo "  Run 'git status' and look for an unmerged file before trusting what this"
  echo "  stages, and drop that entry only after the commit lands:"
  echo "      git stash drop $NEW_STASH"
fi

# ---------- 3. stage ----------
git reset -q            # start from a clean index; never inherit a foreign stage
if [ "$STAGE_ALL" -eq 1 ]; then
  echo "! --all: sweeping the whole working tree. Taking:"
  git status --short | sed 's/^/    /'
  git add -A
else
  for f in "${FILES[@]}"; do
    if [ ! -e "$f" ] && ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
      echo "x not a file in this repo: $f"
      exit 1
    fi
    git add -- "$f"
  done
fi

NOTHING_STAGED=0
if git diff --cached --quiet; then
  NOTHING_STAGED=1
else
  echo "staging:"
  git diff --cached --name-only | sed 's/^/    /'
  # Leave everything else exactly as it was, and say so, so a session can see at a
  # glance whether it is walking away from work another session still has open.
  LEFT=$(git status --short | grep -v '^[MARCD]' | wc -l | tr -d ' ')
  [ "$LEFT" != "0" ] && echo "leaving $LEFT other dirty path(s) untouched (another session's, probably)"
fi

# ---------- 3b. the --no-verify record ----------
# Only on the override path, only when there is something to commit, and only HERE - after
# staging and before the commit - so connect.py reads exactly the index the skipped gate would
# have read, and the block naming what it found is staged with it.

# One line, no wikilink syntax, no pipe. A `[[target]]` copied out of a broken-link finding and
# written into log.md as prose would be a brand new broken link: the gate red again tomorrow
# over the sentence that explains why it was red today. Everything captured is also reproduced
# verbatim further down inside a fence, which lint.py and connect.py strip before they scan.
prose_safe() {
  printf '%s' "$1" | tr '\n\t' '  ' | tr -d '[]|`' | sed -e 's/  */ /g' -e 's/^ //' -e 's/ $//'
}
# For the lines INSIDE the block's fences, where [[target]] may stay as the tool printed it.
# Only backticks come out: a run of three inside a commit message would close the fence early.
fence_safe() {
  tr -d '`'
}
heading_safe() {
  prose_safe "$1" | cut -c1-110
}

# The findings, capped: the actual lines, never a count, but not five hundred of them either.
cap_lines() {
  local text="$1" max="$2" n
  n=$(printf '%s\n' "$text" | grep -c '[^[:space:]]' || true)
  if [ "$n" -eq 0 ]; then
    echo "(this tool printed no findings of its own)"
    return 0
  fi
  printf '%s\n' "$text" | grep '[^[:space:]]' | head -n "$max"
  if [ "$n" -gt "$max" ]; then
    echo "... and $((n - max)) more line(s) of the same - run the tool for the full list"
  fi
}

# The banner tally. Set by record_the_override from the very lines the block quotes, and read
# again by the closing GATE SKIPPED banner; empty on every other path.
OVERRIDE_TALLY=""         # the BLOCKING kinds: "CONFLICT x1  BROKEN x29"
OVERRIDE_ADVISORY=""      # the kinds that never block: "FM x1  STRANDED x2"
OVERRIDE_TAG_COUNT=0      # how many DISTINCT BLOCKING tags that is
OVERRIDE_SUMMARY=""       # the whole "accepting: ..." line, ready to print

# The tags that lint.py and connect.py print WITHOUT blocking a commit: FM, STRANDED and every
# lowercase "<check>/warn" tag are
# counted by lint.py but are not in its sys.exit() expression; NEW and note are connect.py's
# advisory lines (the hook blocks on GAP only). Everything else, including every tag this
# script has never seen, is treated as blocking, so the list going stale costs a spurious
# warning, never a silent one. Keep it as short as the evidence allows: a tag belongs here only
# once somebody has read the gate and confirmed it cannot stop a commit.
ADVISORY_TAGS="FM STRANDED NEW note conflict/warn date/warn duplicate/warn fixture/warn guess/warn postnum/warn qbank/warn"

# $1: which side to count, "blocking" or "advisory". stdin: finding lines exactly as the tools
# printed them - two spaces, then the tag. stdout: one line of TAGxN pairs, RAREST FIRST, ties
# alphabetical. Rarest first because the finding that matters is usually the singleton buried
# under the expected noise.
tally_tags() {
  awk -v want="${1:-blocking}" -v advisory="$ADVISORY_TAGS" '
       BEGIN { split(advisory, _a, " "); for (_i in _a) adv[_a[_i]] = 1 }
       { sub(/^[[:space:]]+/, ""); if ($1 == "") next
         side = ($1 in adv) ? "advisory" : "blocking"
         if (side == want) n[$1]++ }
       END { for (t in n) printf "%d\t%s\n", n[t], t }' \
  | sort -k1,1n -k2,2 \
  | awk '{ printf "%s%s x%s", (NR > 1 ? "  " : ""), $2, $1 }
         END { if (NR > 0) printf "\n" }'
}

# $1 the tagged finding lines, both tools together; $2,$3 their exit codes; $4 the tools that
# printed something no tag matched, if any (counted by name, so a crashed tool's tail is not
# tallied a word at a time into invented tags).
build_override_summary() {
  local tagged="$1" l_rc="$2" c_rc="$3" untagged="$4" kept
  kept=$(printf '%s\n' "$tagged" | grep '[^[:space:]]' || true)
  OVERRIDE_TALLY=$(printf '%s\n' "$kept" | tally_tags blocking || true)
  OVERRIDE_ADVISORY=$(printf '%s\n' "$kept" | tally_tags advisory || true)
  OVERRIDE_TAG_COUNT=$(printf '%s' "$OVERRIDE_TALLY" | tr ' ' '\n' | grep -c 'x[0-9]' || true)
  if [ -n "$OVERRIDE_TALLY" ]; then
    OVERRIDE_SUMMARY="accepting: $OVERRIDE_TALLY"
    if [ -n "$OVERRIDE_ADVISORY" ]; then
      OVERRIDE_SUMMARY="$OVERRIDE_SUMMARY  |  also non-blocking: $OVERRIDE_ADVISORY"
    fi
  elif [ -n "$OVERRIDE_ADVISORY" ]; then
    OVERRIDE_SUMMARY="accepting: nothing that was blocking  |  non-blocking findings only: $OVERRIDE_ADVISORY"
  elif [ -n "$untagged" ]; then
    OVERRIDE_SUMMARY="accepting: nothing this could tag - $untagged printed no tagged finding; the block in $LOG_FILE keeps the tail of what it did print"
  else
    OVERRIDE_SUMMARY="accepting: nothing - neither gate printed a finding (lint.py exit $l_rc, connect.py exit $c_rc)"
  fi
  if [ -n "$untagged" ] && [ -n "$OVERRIDE_TALLY$OVERRIDE_ADVISORY" ]; then
    OVERRIDE_SUMMARY="$OVERRIDE_SUMMARY  (and untagged output from $untagged - see $LOG_FILE)"
  fi
  return 0
}

# Both banners print through here, so they cannot drift apart. The second line fires only for
# more than one KIND of BLOCKING finding under a single reason.
say_the_tally() {
  local pad="${1:-}"
  [ -z "$OVERRIDE_SUMMARY" ] && return 0
  echo "${pad}${OVERRIDE_SUMMARY}"
  if [ "${OVERRIDE_TAG_COUNT:-0}" -gt 1 ]; then
    echo "${pad}! more than one KIND of finding is being accepted - check that the reason covers all of them"
  fi
  return 0
}

record_the_override() {
  local when_date when_stamp lint_out connect_out lint_rc connect_rc lint_lines connect_lines
  local lint_note connect_note tmp size_before size_after block_size append_err
  local tagged_lines untagged_tools

  # The clock is read HERE, at the moment of use, never carried forward from earlier in the
  # run: a session that began before midnight would otherwise stamp the block with yesterday.
  when_date=$(date '+%Y-%m-%d')
  when_stamp=$(date '+%Y-%m-%d %H:%M %Z')

  echo "-- --no-verify: running the two gates this commit is about to skip, to record what they say --"
  lint_rc=0
  lint_out=$(python3 tools/lint.py 2>&1) || lint_rc=$?
  connect_rc=0
  connect_out=$(python3 tools/connect.py 2>&1) || connect_rc=$?

  # lint.py prints every finding as two spaces and an UPPERCASE tag (BROKEN, ORPHAN, DATE,
  # CITE...) and every warning in lower case (date/warn...), so the case of the tag is the
  # split. The block keeps everything; only the banner line sorts blocking from advisory.
  lint_lines=$(printf '%s\n' "$lint_out" | grep -E '^  [A-Z]' || true)
  connect_lines=$(printf '%s\n' "$connect_out" | grep -E '^  (GAP|NEW|note) ' || true)

  # The banner tally is counted from THESE lines - one extraction, before the fallback below
  # can put a tool's untagged tail where its findings would have been.
  tagged_lines=$(printf '%s\n%s\n' "$lint_lines" "$connect_lines" | grep '[^[:space:]]' || true)
  untagged_tools=""

  # A tool that failed and matched nothing would otherwise record an override of something the
  # block cannot name (lint.py crashed, python is missing, or its finding format moved). Keep
  # the tail of what it printed rather than an empty fence.
  lint_note=""
  connect_note=""
  if [ -z "$lint_lines" ] && [ "$lint_rc" -ne 0 ]; then
    lint_lines=$(printf '%s\n' "$lint_out" | tail -n 10)
    lint_note=" - no tagged finding lines came back, so this is the tail of what it printed"
    untagged_tools="lint.py"
  fi
  if [ -z "$connect_lines" ] && [ "$connect_rc" -ne 0 ]; then
    connect_lines=$(printf '%s\n' "$connect_out" | tail -n 10)
    connect_note=" - no tagged finding lines came back, so this is the tail of what it printed"
    untagged_tools="${untagged_tools:+$untagged_tools and }connect.py"
  fi

  build_override_summary "$tagged_lines" "$lint_rc" "$connect_rc" "$untagged_tools"

  if [ "$lint_rc" -eq 0 ] && [ "$connect_rc" -eq 0 ] \
     && [ -z "$lint_lines" ] && [ -z "$connect_lines" ]; then
    echo "! both gates came back CLEAN just now, so this override may not be needed at all."
    echo "  The run goes on, because the flag was given deliberately - and the block below says"
    echo "  plainly that there was nothing to accept, which is worth having on the record too."
  fi

  say_the_tally

  tmp=$(mktemp "${TMPDIR:-/tmp}/second-brain-override.XXXXXX") || {
    echo "x COULD NOT RECORD THE OVERRIDE - no temporary file could be created, so the block was"
    echo "  never built. Nothing was committed."
    exit 1
  }

  {
    echo ""
    echo "## [$when_date] commit-hygiene | gate override (--no-verify) - $(heading_safe "$MSG")"
    echo ""
    echo "\`safe_commit.sh --no-verify\` at $when_stamp. The pre-commit gate was skipped for this commit deliberately, and this block is the record required in exchange, written by the script rather than from memory and committed with the work it excuses. Everything else ran as it always does: the lock, the rebase onto whatever other sessions had pushed, the conflict-marker refusal and the push retry. Run here a moment before the commit, lint.py exited $lint_rc and connect.py exited $connect_rc."
    echo ""
    echo "**Reason given:** $(prose_safe "$NO_VERIFY_REASON")"
    echo ""
    echo "**What was passed, verbatim:**"
    echo ""
    echo '```'
    printf '%s\n' "message: $MSG" "reason:  $NO_VERIFY_REASON" "files:   ${FILES[*]}" | fence_safe
    echo '```'
    echo ""
    echo "**lint.py (exit $lint_rc) - the findings this commit accepts$lint_note:**"
    echo ""
    echo '```'
    cap_lines "$lint_lines" 15 | fence_safe
    echo '```'
    echo ""
    echo "**connect.py (exit $connect_rc) - the findings this commit accepts$connect_note:**"
    echo ""
    echo '```'
    cap_lines "$connect_lines" 15 | fence_safe
    echo '```'
  } > "$tmp"

  size_before=0
  [ -f "$LOG_FILE" ] && size_before=$(wc -c < "$LOG_FILE" | tr -d ' ')
  block_size=$(wc -c < "$tmp" | tr -d ' ')

  if ! append_err=$( { cat "$tmp" >> "$LOG_FILE" ; } 2>&1 ); then
    echo "x COULD NOT RECORD THE OVERRIDE - nothing was committed."
    echo "  Appending to $LOG_FILE failed:"
    echo "      ${append_err:-no reason given}"
    echo "  An override this script cannot write down is an override it will not make: the record"
    echo "  is the entire reason --no-verify exists here. The block it was going to append is kept:"
    echo "      $tmp"
    exit 1
  fi

  size_after=$(wc -c < "$LOG_FILE" | tr -d ' ')
  if [ "$((size_after - size_before))" -ne "$block_size" ]; then
    echo "x COULD NOT RECORD THE OVERRIDE - nothing was committed."
    echo "  $LOG_FILE grew by $((size_after - size_before)) bytes where the block is $block_size, so the"
    echo "  append did not land whole. Check the tail of that file by hand; the block as it"
    echo "  should read is here:"
    echo "      $tmp"
    exit 1
  fi

  # Stage ONLY the block this run appended when wiki/log.md is not one of the named files:
  # another session sharing the checkout may have its own uncommitted appends in it, and
  # `git add` on the whole file would publish them under this run's message. The index copy
  # plus our block becomes the staged blob; the file on disk keeps everyone's lines.
  local log_named=0 f blob
  for f in "${FILES[@]}"; do [ "$f" = "$LOG_FILE" ] && log_named=1; done
  if [ "$log_named" -eq 0 ] && git cat-file -e ":$LOG_FILE" 2>/dev/null \
     && ! git diff --quiet -- "$LOG_FILE" 2>/dev/null; then
    blob=$( { git cat-file blob ":$LOG_FILE" && cat "$tmp"; } | git hash-object -w --stdin ) \
      && [ -n "$blob" ] && git update-index --cacheinfo "100644,$blob,$LOG_FILE" \
      && { rm -f "$tmp"; echo "ok override recorded in $LOG_FILE under [$when_date]; only this block is staged - other uncommitted lines in that file stay unstaged"; return 0; }
  fi
  if ! git add -- "$LOG_FILE"; then
    echo "x COULD NOT RECORD THE OVERRIDE - nothing was committed."
    echo "  The block was appended to $LOG_FILE but git would not stage it, so the record and the"
    echo "  commit it excuses would not have travelled together. Stage it yourself or undo the"
    echo "  append, then run this again."
    exit 1
  fi

  rm -f "$tmp"
  echo "ok override recorded in $LOG_FILE under [$when_date] and staged alongside the named files"
}

if [ "$NO_VERIFY" -eq 1 ]; then
  if [ "$NOTHING_STAGED" -eq 0 ]; then
    record_the_override
  else
    echo "! --no-verify was given, but the named files have no changes - there is no commit to"
    echo "  make, so no gate was skipped and $LOG_FILE was not touched."
  fi
fi

# ---------- 3d. the gate this repository carries ----------
# git does not clone .git/hooks, so a fresh clone has no pre-commit hook at all and a commit
# made through this script would run ungated and still print "pushed". The gate is therefore a
# tracked file (hooks/pre-commit), and this section makes sure it is where git will look
# before the commit below runs. Four cases, in the order they are decided:
#   - AN EXECUTABLE HOOK IS ALREADY THERE: nothing changes. If its checks differ from the
#     tracked copy the drift is named in ONE line; it is never overwritten, because a clone
#     may hold a deliberate local tweak;
#   - NOTHING EXECUTABLE IS THERE: the tracked copy is INSTALLED at that path. Installing
#     rather than only running it inline also gates any later raw `git commit` in the clone;
#   - IT CANNOT BE INSTALLED (unwritable hooks directory, git will not say where it looks):
#     the tracked gate is RUN here, in front of the commit, and a red one refuses the commit;
#   - THERE IS NOTHING TO RUN EITHER: the commit is refused outright, loudly.
#
# WHERE GIT LOOKS IS ASKED OF GIT, never assembled out of `.git/hooks`: core.hooksPath moves
# it, and in a worktree `.git` is a file. A relative answer is relative to the current
# directory, which is this checkout's toplevel (the cd at the top).
#
# --no-verify DOES NOT CHANGE THE INSTALL, and the install is not a verification. What
# --no-verify does switch off is the refuse-on-red fallback, because section 3b has already
# run both tools against this very index and written every line into the log.
TRACKED_GATE="hooks/pre-commit"

# Absolute, because it is compared, copied to and printed; empty return means git would not say.
gate_hook_path() {
  local p
  p=$(git rev-parse --git-path hooks/pre-commit 2>/dev/null) || return 1
  [ -n "$p" ] || return 1
  case "$p" in
    /*) printf '%s\n' "$p" ;;
     *) printf '%s\n' "$THIS_TREE/$p" ;;
  esac
}

# The gate's executable logic, with comments, trailing whitespace and blank lines taken out.
# The comparison below is NOT a byte comparison: a hook with a shorter header but the same
# checks must not print a drift line on every commit, for ever.
gate_logic() {
  sed -e 's/[[:space:]]*$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$1" 2>/dev/null || true
}

# The gate is not where git looks and could not be put there. $1 says why, in words that go
# into the refusal, because "the gate could not run" with no reason is the kind of line a
# session works around instead of fixing.
gate_run_here_or_refuse() {
  local why="$1" out rc

  if [ "$NO_VERIFY" -eq 1 ]; then
    echo "i the commit gate is not installed where git looks ($why) - it was being skipped by --no-verify on this run anyway, and $LOG_FILE carries what both tools found."
    return 0
  fi

  if [ ! -f "$TRACKED_GATE" ]; then
    echo "x COMMIT REFUSED - THE GATE COULD NOT BE RUN AT ALL. Nothing was committed."
    echo "  $why, and there is no $TRACKED_GATE in this checkout to run in its place,"
    echo "  so lint.py and connect.py have not seen this commit and nothing here can say"
    echo "  whether they would pass it. A run with no gate must not look like a gated one."
    echo "  Restore it with: git checkout -- $TRACKED_GATE   then run this script again."
    echo "  Nothing is lost; your named files are staged as they were."
    exit 1
  fi

  echo "! the commit gate is not installed where git looks ($why)."
  echo "  Running $TRACKED_GATE here instead, in front of the commit:"
  rc=0
  out=$(bash "$TRACKED_GATE" 2>&1) || rc=$?
  printf '%s\n' "$out" | sed 's/^/    /'
  if [ "$rc" -ne 0 ]; then
    echo "x COMMIT REFUSED - the gate above exited $rc. Nothing was committed."
    echo "  Fix what it printed and run this script again, or accept the finding deliberately"
    echo "  with --no-verify=\"<why it is accepted>\", which records every line of it in $LOG_FILE."
    exit 1
  fi
  echo "ok the gate passed, run here rather than as a hook; committing."
  return 0
}

# True when the hook path sits inside this repository: its git dir, its common git dir, or
# this working tree. Paths are compared physically (pwd -P), since /tmp and the like are links.
hook_is_ours() {
  local dir gd cd_ root
  # The hooks folder may not exist yet: resolve its nearest existing ancestor instead,
  # which is inside the repository exactly when the folder would be.
  dir=$(dirname "$1")
  while [ ! -d "$dir" ] && [ "$dir" != "/" ] && [ "$dir" != "." ]; do dir=$(dirname "$dir"); done
  dir=$(cd "$dir" 2>/dev/null && pwd -P) || return 1
  gd=$(cd "$(git rev-parse --git-dir 2>/dev/null)" 2>/dev/null && pwd -P) || gd=""
  cd_=$(cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P) || cd_=""
  for root in "$gd" "$cd_" "$THIS_TREE"; do
    [ -n "$root" ] || continue
    case "$dir/" in "$root"/*) return 0 ;; esac
  done
  return 1
}

# Called once, immediately before the commit, and only when there is a commit to make.
ensure_the_gate_is_installed() {
  local hook err

  if ! hook=$(gate_hook_path); then
    gate_run_here_or_refuse "git would not say where it looks for hooks - \`git rev-parse --git-path hooks/pre-commit\` failed"
    return 0
  fi

  # A hooks folder OUTSIDE this repository (a machine-wide core.hooksPath) is shared by every
  # repository on the machine. This vault's gate refuses any commit where tools/lint.py is
  # missing, so installing it there would block commits everywhere else. Never write there:
  # run the tracked gate here instead, every time.
  if ! hook_is_ours "$hook"; then
    if [ -x "$hook" ] && [ -f "$TRACKED_GATE" ] && [ "$(gate_logic "$hook")" = "$(gate_logic "$TRACKED_GATE")" ]; then
      return 0
    fi
    gate_run_here_or_refuse "git looks for hooks outside this repository, at $hook (core.hooksPath); this vault's gate is not installed there because every other repository would run it"
    return 0
  fi

  if [ -x "$hook" ]; then
    if [ -f "$TRACKED_GATE" ] && [ "$(gate_logic "$hook")" != "$(gate_logic "$TRACKED_GATE")" ]; then
      echo "i the commit gate installed at $hook runs different checks from the tracked $TRACKED_GATE - committing through the installed one, which is left exactly as it is."
    fi
    return 0
  fi

  if [ ! -f "$TRACKED_GATE" ]; then
    gate_run_here_or_refuse "there is no executable hook at $hook"
    return 0
  fi

  # A file that is there but not executable is one git silently ignores, so it is not a gate -
  # but it is still somebody's file. It is kept beside the hook under a name git never calls.
  if [ -e "$hook" ] && cp -p "$hook" "$hook.not-executable" 2>/dev/null; then
    echo "i $hook was there but not executable, which git ignores; the old contents are kept as $hook.not-executable"
  fi

  if ! err=$( { mkdir -p "$(dirname "$hook")" && cp "$TRACKED_GATE" "$hook" && chmod +x "$hook"; } 2>&1 ); then
    gate_run_here_or_refuse "installing it at $hook failed - ${err:-no reason given}"
    return 0
  fi
  echo "i installed the commit gate at $hook from $TRACKED_GATE - this clone had none, so this commit and every later raw git commit here now run lint.py and connect.py instead of skipping them unannounced."
  return 0
}

if [ "$NOTHING_STAGED" -eq 0 ]; then
  ensure_the_gate_is_installed
fi

# ---------- 4. commit (the pre-commit hook runs the gates) ----------
THIS_RUN_COMMITTED=0
if [ "$NOTHING_STAGED" -eq 0 ]; then
  if [ "$NO_VERIFY" -eq 1 ]; then
    git commit --no-verify -m "$MSG"
    echo "================================================================================"
    echo "!  GATE SKIPPED - committed $(git rev-parse --short HEAD) without lint.py or connect.py."
    # High in the banner, above the reason, because the reason can run for lines and this is
    # the thing a session skimming the end of a run has to see.
    say_the_tally "   "
    echo "   Reason given: $NO_VERIFY_REASON"
    echo "   The accepted findings are written into $LOG_FILE in this same commit."
    echo "   Whatever they were is still wrong in the repository; this only stopped it blocking."
    echo "================================================================================"
  else
    git commit -m "$MSG"
  fi
  THIS_RUN_COMMITTED=1
fi

# ---------- 5. push, retrying through concurrent pushes ----------
# The commit being published is NOT always HEAD: when another session pushes in
# between, this run's commit is replayed onto theirs in memory and PUBLISH moves to
# that copy, while this checkout stays where it is until git can move it without
# overwriting anybody's edits.
PUBLISH=$(git rev-parse HEAD)

# No remote: the commit is made and is safe here; there is nothing to publish to.
if [ "$HAS_REMOTE" -eq 0 ]; then
  if [ "$THIS_RUN_COMMITTED" -eq 1 ]; then
    echo "ok committed $(git rev-parse --short HEAD) locally - push skipped: no remote named origin"
  else
    echo "nothing staged - the named files have no changes. Push skipped: no remote named origin"
  fi
  exit 0
fi

# After a push from a worktree, bring the main folder along. It is what an Obsidian
# window is showing, and nothing else moves it until some session commits from inside
# it. A fast-forward only, only while it is on main, and git itself refuses to
# overwrite a file with uncommitted edits, in which case nothing there changes and the
# output says so. It takes the commit that was PUBLISHED, never this checkout's HEAD:
# after an in-memory replay those are two different commits, and moving the folder you
# read onto one the remote has never seen is worse than leaving it behind.
refresh_main_folder() {
  local published="$1" main_branch out
  if [ -z "$MAIN_TREE" ] || [ "$MAIN_TREE" = "$THIS_TREE" ]; then
    return 0
  fi
  main_branch=$(git -C "$MAIN_TREE" symbolic-ref -q --short HEAD || true)
  if [ "$main_branch" != "main" ]; then
    echo "  main folder left as it is: $MAIN_TREE is on ${main_branch:-a detached HEAD}, not main"
    return 0
  fi
  if out=$(git -C "$MAIN_TREE" merge --ff-only --quiet "$published" 2>&1); then
    echo "* main folder brought up to date: $MAIN_TREE"
  else
    echo "! main folder NOT brought up to date. git declined and changed nothing there:"
    echo "$out" | sed 's/^/      /'
    echo "  The commit is published regardless; the folder catches up the next time a"
    echo "  session commits from inside it."
  fi
}

# Replay this run's commit(s) onto what main holds now, ENTIRELY IN MEMORY. Nothing in
# here reads or writes the working tree or the index, which is the whole point: the
# retry must not touch a file another session has open. A rebase would need the tree
# clean, and in a shared folder the tree is nearly always dirty.
REPLAY_NEW=""
REPLAY_CONFLICTS=""
REPLAY_UNSUPPORTED=0
replay_onto() {          # $1 = what main holds now, $2 = the commit to replay onto it
  local newbase="$1" tip="$2" new="$1" x t out rc
  REPLAY_NEW=""; REPLAY_CONFLICTS=""; REPLAY_UNSUPPORTED=0
  for x in $(git rev-list --reverse "$newbase..$tip"); do
    if [ "$(git rev-list --parents -n 1 "$x" | awk '{print NF - 1}')" -ne 1 ]; then
      REPLAY_UNSUPPORTED=1     # a merge commit; replaying one is a judgment call
      return 1
    fi
    rc=0
    out=$(git merge-tree --write-tree --name-only --no-messages \
            --merge-base="$x^" "$new" "$x" 2>/dev/null) || rc=$?
    t=$(printf '%s\n' "$out" | sed -n '1p')
    case "$t" in
      ""|*[!0-9a-f]*)
        REPLAY_UNSUPPORTED=1   # no tree came back: this git is too old for it
        return 1 ;;
    esac
    if [ "$rc" -ne 0 ]; then
      REPLAY_CONFLICTS=$(printf '%s\n' "$out" | tail -n +2)
      return 1
    fi
    if [ "$t" = "$(git rev-parse "$new^{tree}")" ]; then
      continue                 # the other session pushed this very change
    fi
    # The message is taken from the commit object byte for byte, and the author with
    # it, so a replayed commit differs from the original in nothing but its parent.
    new=$(git cat-file commit "$x" | sed '1,/^$/d' |
          GIT_AUTHOR_NAME=$(git log -1 --format=%an "$x") \
          GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae "$x") \
          GIT_AUTHOR_DATE=$(git log -1 --format=%aI "$x") \
          git commit-tree "$t" -p "$new" -F -) || { REPLAY_UNSUPPORTED=1; return 1; }
  done
  REPLAY_NEW="$new"
  return 0
}

# A replayed commit is built by merge-tree and commit-tree, which run no hooks, so the tree
# about to be pushed - upstream plus this run's edits - has never been through the gate.
# In commit-first mode that is every run where origin moved; in the normal mode it is the
# race inside the push loop. Check it in a throwaway detached worktree of that exact commit,
# which reads and writes no file in this checkout. Returns 1 (and prints why) on red.
gate_the_replayed_tree() {        # $1 = the replayed commit
  local c="$1" wt out rc=0
  if [ "$NO_VERIFY" -eq 1 ]; then
    echo "i replayed tree not re-gated: this run skips the gate by --no-verify, recorded in $LOG_FILE"
    return 0
  fi
  if ! git cat-file -e "$c:$TRACKED_GATE" 2>/dev/null; then
    echo "x the replayed tree has no $TRACKED_GATE, so it cannot be gated."
    return 1
  fi
  wt=$(mktemp -d "${TMPDIR:-/tmp}/second-brain-gate.XXXXXX") || { echo "x could not make a temp folder to gate the replayed tree"; return 1; }
  rmdir "$wt" 2>/dev/null || true
  if ! out=$(git worktree add -q --detach "$wt" "$c" 2>&1); then
    echo "x could not check out the replayed tree to gate it:"
    printf '%s\n' "$out" | sed 's/^/      /'
    return 1
  fi
  out=$(cd "$wt" && bash "$TRACKED_GATE" 2>&1) || rc=$?
  git worktree remove --force "$wt" >/dev/null 2>&1 || true
  if [ "$rc" -ne 0 ]; then
    echo "x the tree that would be pushed (main as it is now, plus this commit) fails the gate:"
    printf '%s\n' "$out" | sed 's/^/      /'
    return 1
  fi
  echo "ok replayed tree gated clean"
  return 0
}

say_the_commit_is_safe() {
  if [ "$THIS_RUN_COMMITTED" -eq 1 ]; then
    echo "  Your commit is made and is safe in this checkout:"
  else
    echo "  The commit that was already waiting here is safe, exactly as it was:"
  fi
  echo "      $(git log -1 --format='%h %s' HEAD)"
  echo "  Getting this far left nothing half-finished: no rebase in progress, no conflict"
  echo "  markers, no stash entry, and not one file changed. Only the push did not happen."
}

rerun_command() {
  # The rerun must PULL first, which commit-first mode never does: with
  # SECOND_BRAIN_COMMIT_BEFORE_PULL=1 still exported it would fetch, recommit on the same
  # stale base and hit the same conflict for ever. So the printed command switches it off.
  if [ "$COMMIT_FIRST" -eq 1 ]; then
    printf 'SECOND_BRAIN_COMMIT_BEFORE_PULL=0 '
  fi
  if [ "$STAGE_ALL" -eq 1 ]; then
    echo "./tools/safe_commit.sh --all \"<the same message>\""
  elif [ "$NO_VERIFY" -eq 1 ]; then
    # The flag has to come with it, or the re-run walks straight back into the gate this run
    # was let past. It appends a second block to the log, which is correct: the log is
    # append-only and the second one records the attempt that actually published.
    echo "./tools/safe_commit.sh --no-verify=\"$NO_VERIFY_REASON\" \"<the same message>\" ${FILES[*]}"
  else
    echo "./tools/safe_commit.sh \"<the same message>\" ${FILES[*]}"
  fi
}

# Undoing this run's own commit is the one recovery that works the same in the main
# folder and in a worktree. Two wrong answers, both common: "just run it again"
# publishes nothing when the lines really collide, because the commit sits on local
# main and every re-run rebases it onto theirs and stops; and a soft reset to main
# itself keeps this checkout's OLD copy of every file, so the next commit quietly
# reverts whatever landed since.
say_how_to_get_it_out() {
  local parent=""
  if [ "$THIS_RUN_COMMITTED" -eq 1 ]; then
    parent=$(git rev-parse --short "HEAD^" 2>/dev/null || true)
  fi
  if [ -n "$parent" ]; then
    echo "  What to do - the same wherever you are standing:"
    echo "    1. git reset --soft $parent"
    echo "       Your commit becomes plain edits again. Every edit stays in its file,"
    echo "       only the commit goes, and nothing anybody else has open is touched."
    echo "    2. $(rerun_command)"
    echo "       Its first step takes in whatever main holds by then and your edits go"
    echo "       out on top of that, with any overlapping lines put in front of you once."
  else
    echo "  This run committed nothing of its own, so it has nothing to undo. Deal with"
    echo "  what git said above, then run this script again - it publishes a commit"
    echo "  already waiting here."
  fi
  echo "  Do not force-push, and do not reset to main itself: both throw away what the"
  echo "  other sessions have pushed since."
}

if [ "$NOTHING_STAGED" -eq 1 ]; then
  echo "nothing staged - the named files have no changes."
  # A commit can still be sitting on local main unpublished: an earlier run whose push
  # failed, or a session that stopped after resolving a conflict. Exiting here would
  # make "run this script again" - the recovery every failure message names - do
  # nothing at all.
  if [ -z "$(git rev-list -n 1 FETCH_HEAD..HEAD 2>/dev/null || true)" ]; then
    echo "  Nothing to commit, and nothing waiting here to publish."
    exit 0
  fi
  echo "  There is an unpublished commit here, though, so this run sends it out:"
  git log --format='    %h %s' FETCH_HEAD..HEAD
fi

for i in 1 2 3; do
  PUSH_OUT=""
  if PUSH_OUT=$(git push origin "$PUBLISH:refs/heads/main" 2>&1); then
    echo "✓ pushed $(git rev-parse --short "$PUBLISH") to main"
    if [ "$PUBLISH" != "$(git rev-parse HEAD)" ]; then
      echo "  (another session pushed while this one was committing; your commit was"
      echo "   rebased onto theirs in memory, without touching any file here)"
      if KEEP_ERR=$(git reset --keep "$PUBLISH" 2>&1); then
        :
      else
        echo "! published - but this checkout was NOT moved onto it, and nothing here changed."
        echo "  git declined:"
        echo "$KEEP_ERR" | sed 's/^/      /'
        echo "  That is git protecting a file somebody has uncommitted edits in. The same"
        echo "  work is published under the other sha; nothing is lost and there is"
        echo "  nothing to undo."
      fi
    fi
    refresh_main_folder "$PUBLISH" || true
    exit 0
  fi

  # Was that the publishing race this loop exists for, or something else? Ask the
  # remote rather than reading git's sentence: the word "rejected" also appears when a
  # rule on the remote refuses the push outright, and no amount of rebasing fixes that.
  if ! git fetch -q origin main; then
    echo "x NOT PUBLISHED - the push failed and the remote could not be reached to find out why."
    echo "  git said:"
    echo "$PUSH_OUT" | sed 's/^/      /'
    say_the_commit_is_safe
    say_how_to_get_it_out
    exit 1
  fi
  UPSTREAM=$(git rev-parse FETCH_HEAD)
  if [ "$UPSTREAM" = "$PUBLISH" ]; then
    echo "✓ main already holds this commit ($(git rev-parse --short "$PUBLISH")) - the push"
    echo "  reported a failure, but the commit is there. git said:"
    echo "$PUSH_OUT" | sed 's/^/      /'
    if [ "$PUBLISH" != "$(git rev-parse HEAD)" ]; then
      git reset --keep "$PUBLISH" >/dev/null 2>&1 || true
    fi
    refresh_main_folder "$PUBLISH" || true
    exit 0
  fi
  if git merge-base --is-ancestor "$UPSTREAM" "$PUBLISH"; then
    echo "x NOT PUBLISHED - the push failed, and not because another session got there first:"
    echo "  main has not moved past this commit. git said:"
    echo "$PUSH_OUT" | sed 's/^/      /'
    say_the_commit_is_safe
    echo "  That reason is git's, and this script has no fix for it."
    say_how_to_get_it_out
    exit 1
  fi

  echo "another session pushed first - rebasing this commit onto theirs, without touching"
  echo "  any file here (try $i of 3)"
  if replay_onto "$UPSTREAM" "$PUBLISH"; then
    if ! gate_the_replayed_tree "$REPLAY_NEW"; then
      echo "x NOT PUBLISHED - what main holds now, plus this commit, does not pass the gate."
      say_the_commit_is_safe
      say_how_to_get_it_out
      exit 1
    fi
    PUBLISH="$REPLAY_NEW"
    continue
  fi

  if [ "$REPLAY_UNSUPPORTED" -eq 0 ]; then
    echo "x CANNOT PUBLISH - the other session changed the same lines you did."
    echo "  Both of you edited:"
    echo "$REPLAY_CONFLICTS" | sed 's/^/      /'
    say_the_commit_is_safe
    echo "  Somebody has to decide what those lines should say, and that is not this"
    echo "  script's call. Follow the steps below and the pull at the start of the next"
    echo "  run brings the other session's version in, so you settle it once, in one place."
    say_how_to_get_it_out
    exit 1
  fi

  # This git cannot merge in memory, so fall back to rebasing this checkout in place,
  # which needs everything here committed or clean - and undo a rebase that stops,
  # rather than walking away and leaving markers in somebody's open file.
  echo "! this git cannot do the merge in memory ($(git --version)); falling back to"
  echo "  rebasing this checkout in place, which needs everything here committed or clean."
  if git pull --rebase origin main; then
    PUBLISH=$(git rev-parse HEAD)
    continue
  fi
  git rebase --abort 2>/dev/null || true
  echo "x COULD NOT REBASE onto what the other session pushed. The rebase was undone, so"
  echo "  nothing here is half-finished and no conflict markers were written."
  say_the_commit_is_safe
  say_how_to_get_it_out
  exit 1
done

echo "x NOT PUBLISHED after 3 tries - main kept moving under this commit, or the push kept"
echo "  being refused. git's words the last time:"
echo "$PUSH_OUT" | sed 's/^/      /'
say_the_commit_is_safe
say_how_to_get_it_out
exit 1
