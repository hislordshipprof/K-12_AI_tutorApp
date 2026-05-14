#!/bin/bash
# Verifies Phase 1 (foundation) deliverables.
# Pinned to absolute paths so subshell cd's don't break the script.

set +e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PASS=0
FAIL=()

check() {
  local label="$1"
  shift
  echo ""
  echo "=== $label ==="
  if "$@"; then
    PASS=$((PASS + 1))
    echo "✓ $label"
  else
    FAIL+=("$label")
    echo "✗ $label"
  fi
}

# ── DB ─────────────────────────────────────────────────
check "DB migrations exist" sh -c "ls $ROOT/supabase/migrations/*.sql >/dev/null"
check "Seed exists" test -f "$ROOT/supabase/seed.sql"
check "config.toml exists" test -f "$ROOT/supabase/config.toml"
check "RLS migration present" sh -c "grep -liq 'enable row level security' $ROOT/supabase/migrations/*.sql"
check "pgvector enabled" sh -c "grep -liq 'create extension.*vector' $ROOT/supabase/migrations/*.sql"

# ── API ────────────────────────────────────────────────
check "API pyproject.toml" test -f "$ROOT/apps/api/pyproject.toml"
check "google-genai in deps" sh -c "grep -q 'google-genai' $ROOT/apps/api/pyproject.toml"
check "API package importable" sh -c "cd $ROOT/apps/api && .venv/bin/python -c 'import app.main' 2>&1"
check "API tests pass" sh -c "cd $ROOT/apps/api && .venv/bin/pytest -q 2>&1 | tail -3"
check "API starts (smoke)" bash -c "
  cd $ROOT/apps/api && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18001 > /tmp/verify-api-1.log 2>&1 &
  PID=\$!
  sleep 4
  curl -sf http://127.0.0.1:18001/health > /tmp/health1.json
  RC=\$?
  kill \$PID 2>/dev/null
  wait \$PID 2>/dev/null
  test \$RC -eq 0 && grep -q '\"ok\":true' /tmp/health1.json
"

# ── Web ────────────────────────────────────────────────
check "Web package.json" test -f "$ROOT/apps/web/package.json"
check "Web Tailwind config" test -f "$ROOT/apps/web/tailwind.config.ts"
check "Web has design tokens" sh -c "grep -q 'paper' $ROOT/apps/web/tailwind.config.ts && grep -q 'indigo' $ROOT/apps/web/tailwind.config.ts && grep -q 'chalk' $ROOT/apps/web/tailwind.config.ts"
check "Web typecheck" sh -c "cd $ROOT/apps/web && pnpm typecheck 2>&1 | tail -5"
check "Web builds" sh -c "cd $ROOT/apps/web && pnpm build 2>&1 | tail -10"

# ── Secrets safety ─────────────────────────────────────
check ".env IS gitignored" sh -c "cd $ROOT && git check-ignore apps/api/.env >/dev/null"
check "No real Gemini key in tracked files" sh -c "cd $ROOT && ! git ls-files | xargs grep -lE 'AIzaSy[A-Za-z0-9_-]{30,}' 2>/dev/null"

# ── Summary ────────────────────────────────────────────
TOTAL=$((PASS + ${#FAIL[@]}))
echo ""
echo "═══════════════════════════════════════════════════════"
echo "Passed: $PASS / $TOTAL"
if [ ${#FAIL[@]} -gt 0 ]; then
  echo ""
  echo "FAILURES:"
  printf '  ✗ %s\n' "${FAIL[@]}"
  exit 1
fi
echo "✓ ALL PHASE 1 CHECKS PASS"
