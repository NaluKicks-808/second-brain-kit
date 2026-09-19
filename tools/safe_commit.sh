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
# USAGE (run the copy in the checkout you edited):
#   ./tools/safe_commit.sh "message" wiki/people/sam-rivera.md wiki/log.md
#   ./tools/safe_commit.sh --all "message"      # a deliberate whole-tree sweep
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

STAGE_ALL=0

usage() {
  echo "usage: safe_commit.sh \"message\" <file> [file...]"
  echo "       safe_commit.sh --all \"message\"    # deliberate whole-tree sweep"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --all)
      STAGE_ALL=1
      shift ;;
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

if [ "$STAGE_ALL" -eq 0 ] && [ ${#FILES[@]} -eq 0 ]; then
  echo "x No files named, and --all not given."
  echo "  Name the files this session actually edited, so another session's"
  echo "  in-progress work is not swept into your commit. Currently dirty:"
  git status --short | sed 's/^/    /'
  exit 1
fi

# ---------- which checkout, which branch ----------
BRANCH=$(git symbolic-ref -q --short HEAD || true)
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
if [ "$BRANCH" != "main" ]; then
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
STASH_BEFORE=$(git rev-parse -q --verify refs/stash || true)
MARKERS_BEFORE=$(marker_files)

git pull --rebase --autostash origin main || {
  echo "x REBASE FAILED - another session's changes conflict with this one."
  echo "  Resolve by hand (git status), and never commit the markers. Aborting."
  git rebase --abort 2>/dev/null || true
  exit 1
}

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

# ---------- 4. commit (the pre-commit hook runs the gates) ----------
THIS_RUN_COMMITTED=0
if [ "$NOTHING_STAGED" -eq 0 ]; then
  git commit -m "$MSG"
  THIS_RUN_COMMITTED=1
fi

# ---------- 5. push, retrying through concurrent pushes ----------
# The commit being published is NOT always HEAD: when another session pushes in
# between, this run's commit is replayed onto theirs in memory and PUBLISH moves to
# that copy, while this checkout stays where it is until git can move it without
# overwriting anybody's edits.
PUBLISH=$(git rev-parse HEAD)

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
  if [ "$STAGE_ALL" -eq 1 ]; then
    echo "./tools/safe_commit.sh --all \"<the same message>\""
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
