#!/bin/bash
# Pushes the local repo to https://github.com/hislordshipprof/K-12_AI_tutorApp.git
#
# This script is for the OWNER to run when they wake up — I couldn't push from
# the build environment because no GitHub credentials are configured here.

set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# ── Auth options ─────────────────────────────────────────────
# Option A: gh CLI (recommended)
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  echo "✓ gh CLI authenticated. Pushing…"
  git push -u origin main
  echo "✓ Pushed."
  exit 0
fi

# Option B: GITHUB_TOKEN env var (personal access token)
if [ -n "$GITHUB_TOKEN" ]; then
  echo "✓ Using GITHUB_TOKEN env. Pushing…"
  git push -u "https://${GITHUB_TOKEN}@github.com/hislordshipprof/K-12_AI_tutorApp.git" main
  echo "✓ Pushed."
  exit 0
fi

# Option C: interactive prompt (HTTPS)
echo "No gh CLI auth + no GITHUB_TOKEN env. Falling back to interactive HTTPS."
echo "GitHub will prompt for username + personal access token (NOT your password —"
echo "create one at https://github.com/settings/tokens with 'repo' scope)."
echo ""
git push -u origin main
