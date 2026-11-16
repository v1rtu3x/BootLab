#!/usr/bin/env bash
# Push one day of the BootLab commit tree to GitHub.
#
# Usage:
#   ./scripts/push-day.sh [--force] <day>
#   ./scripts/push-day.sh 1        # push Day 1 (first commit)
#   ./scripts/push-day.sh 17       # push Day 17 (final commit)
#   ./scripts/push-day.sh --force 1  # force-push Day 1 (useful for the very first push)
#
# Before pushing, the script rewrites the target commit's author date to the
# current date/time. This makes the GitHub contribution graph reflect the day
# you actually push, rather than the placeholder dates used when the tree was
# bootstrapped.
#
# The local branch must contain exactly 17 commits created by the bootstrap
# workflow documented in docs/COMMIT_PUSH_WORKFLOW.md.

set -euo pipefail

FORCE=0
DAY=""
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
TOTAL_DAYS=17

usage() {
    echo "Usage: $0 [--force] <day 1-$TOTAL_DAYS>" >&2
    exit 1
}

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --force)
            FORCE=1
            ;;
        -*)
            echo "Error: unknown option $arg" >&2
            usage
            ;;
        *)
            if [[ -n "$DAY" ]]; then
                echo "Error: multiple day arguments" >&2
                usage
            fi
            DAY="$arg"
            ;;
    esac
done

[[ -z "$DAY" ]] && usage
if ! [[ "$DAY" =~ ^[0-9]+$ ]] || (( DAY < 1 || DAY > TOTAL_DAYS )); then
    echo "Error: day must be an integer between 1 and $TOTAL_DAYS" >&2
    usage
fi

# Ensure we are on the target branch and the working tree is clean.
if [[ "$(git rev-parse --abbrev-ref HEAD)" != "$BRANCH" ]]; then
    echo "Error: not on $BRANCH branch" >&2
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Error: working tree is not clean" >&2
    echo "Commit or stash changes before running this script." >&2
    exit 1
fi

OFFSET=$((TOTAL_DAYS - DAY))
TARGET="HEAD~${OFFSET}"

if ! git rev-parse --verify "$TARGET" >/dev/null 2>&1; then
    echo "Error: $TARGET does not resolve to a commit" >&2
    echo "Make sure the local branch has $TOTAL_DAYS commits." >&2
    exit 1
fi

TREE=$(git rev-parse "$TARGET^{tree}")
MESSAGE_FILE=$(mktemp)
trap 'rm -f "$MESSAGE_FILE"' EXIT
git log -1 --format=%B "$TARGET" > "$MESSAGE_FILE"
DATE=$(date -R)

# Determine the parent of the target commit. For the root commit, this is empty.
export GIT_AUTHOR_DATE="$DATE"
export GIT_COMMITTER_DATE="$DATE"
if PARENT=$(git rev-parse "$TARGET^" 2>/dev/null); then
    NEW_COMMIT=$(git commit-tree -p "$PARENT" -F "$MESSAGE_FILE" "$TREE")
else
    NEW_COMMIT=$(git commit-tree -F "$MESSAGE_FILE" "$TREE")
fi
unset GIT_AUTHOR_DATE GIT_COMMITTER_DATE

echo "Rewriting Day $DAY commit with date: $DATE"
git rebase --onto "$NEW_COMMIT" "$TARGET" "$BRANCH"

# After rebase, the target commit is again at the same offset from the tip.
PUSH_TARGET="HEAD~${OFFSET}"
if (( DAY == TOTAL_DAYS )); then
    PUSH_TARGET="HEAD"
fi

PUSH_ARGS=()
if (( FORCE )); then
    PUSH_ARGS+=(--force)
fi

echo "Pushing Day $DAY ($PUSH_TARGET) to $REMOTE/$BRANCH ..."
git push "${PUSH_ARGS[@]}" "$REMOTE" "${PUSH_TARGET}:refs/heads/${BRANCH}"
echo "Day $DAY pushed."

if (( DAY == TOTAL_DAYS )); then
    echo "All $TOTAL_DAYS days are now on $REMOTE/$BRANCH."
fi
