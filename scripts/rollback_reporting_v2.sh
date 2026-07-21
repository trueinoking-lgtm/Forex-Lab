#!/usr/bin/env bash
# Rollback plan for Operational Reporting v2 hardening cutover.
# SAFE: paper-only, no order/execution paths touched. Idempotent.
#
# Hardening-only rollback restores the installer-created external-script backups
# and (optionally) returns the repo to the prior operational-reporting commit.
# It does NOT roll back the accounting-v2 database schema (forward-validation
# ledger is preserved).
#
# Usage:
#   scripts/rollback_reporting_v2.sh            # restore external-script backups only
#   scripts/rollback_reporting_v2.sh --repo     # also reset repo to prior commit
#   scripts/rollback_reporting_v2.sh --verify   # check state, no changes
set -euo pipefail

EXTERNAL_DIR=/root/.hermes/scripts
HERMES_REPO_OPS=/root/aether-forex-lab/ops/hermes
PRIOR_COMMIT="${PRIOR_COMMIT:-baa9530}"   # prior operational-reporting commit before the cutover fix

echo "[rollback] mode: ${1:-restore-backups}"

if [[ "${1:-}" == "--verify" ]]; then
  echo "[rollback] external scripts present:"; ls -1 "$EXTERNAL_DIR"/trading_{deliver_reports,run}.sh 2>/dev/null || true
  echo "[rollback] installer backups present:"; ls -1t "$EXTERNAL_DIR"/trading_{deliver_reports,run}.sh.bak.* 2>/dev/null || echo "  (no backups yet)"
  echo "[rollback] current repo HEAD: $(git -C /root/aether-forex-lab rev-parse --short HEAD)"
  exit 0
fi

# 1) Restore installer-created backups of the external scripts.
restored=0
for name in trading_deliver_reports.sh trading_run.sh; do
  bak=$(ls -1t "$EXTERNAL_DIR/$name.bak."* 2>/dev/null | head -1 || true)
  if [[ -n "$bak" ]]; then
    cp "$bak" "$EXTERNAL_DIR/$name"
    chmod 0755 "$EXTERNAL_DIR/$name"
    echo "[rollback] restored $name from $bak"
    restored=1
  else
    echo "[rollback] no backup for $name; leaving current in place"
  fi
done

# 2) Optionally return the repository to the prior operational-reporting commit.
if [[ "${1:-}" == "--repo" ]]; then
  git -C /root/aether-forex-lab checkout -q "$PRIOR_COMMIT" -- \
    app/scripts/report_payload.mjs app/scripts/reporting_source_policy.test.mjs \
    ops/hermes/trading_deliver_reports.sh ops/hermes/trading_run.sh \
    scripts/install_hermes_forex_reporting_jobs.sh 2>/dev/null || \
    git -C /root/aether-forex-lab reset -q --hard "$PRIOR_COMMIT"
  echo "[rollback] repo returned to $PRIOR_COMMIT"
fi

# 3) Regenerate a report (paper-only) and verify paper-only safety. No trading path.
echo "[rollback] regenerating report via hardened path (paper-only)..."
( cd /root/aether-forex-lab/app && node scripts/paper_update_pnl.mjs && node scripts/report_payload.mjs ) || true
echo "[rollback] paper_only check:"
grep -q "paper_only=true" /root/aether-forex-lab/engine/results/daily_report_payload.json \
  && echo "  OK paper_only=true" || echo "  WARN paper_only not asserted"

echo "[rollback] done. restored=$restored. NOTHING in the accounting-v2 DB schema was changed."
