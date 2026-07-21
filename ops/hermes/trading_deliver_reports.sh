#!/usr/bin/env bash
# Regenerate and deliver the canonical paper-only accounting-v2 report on stdout.
cd /root/aether-forex-lab/app || exit 1
node scripts/report_payload.mjs || exit 1
report=/root/aether-forex-lab/engine/results/daily_report_message.md
sent=/root/aether-forex-lab/engine/results/sent
mkdir -p "$sent"
cat "$report"
echo ""
mv "$report" "$sent/daily_report_message_$(date -u +%Y%m%dT%H%M%SZ).md"
