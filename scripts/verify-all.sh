#!/bin/bash
# Run all milestone verifications back to back.
# Usage: ./scripts/verify-all.sh

set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

echo "════════════════════════════════════════════════════════"
echo "  Verifying K-12 AI Tutor build"
echo "════════════════════════════════════════════════════════"
echo ""

echo "▶ Phase 1 — foundation"
echo "--------------------------------------------------------"
bash "$ROOT/scripts/verify-phase-1.sh"

echo ""
echo "▶ Phase 2 — screens"
echo "--------------------------------------------------------"
bash "$ROOT/scripts/verify-phase-2.sh"

echo ""
echo "════════════════════════════════════════════════════════"
echo "✓ ALL CHECKS PASS"
echo "════════════════════════════════════════════════════════"
