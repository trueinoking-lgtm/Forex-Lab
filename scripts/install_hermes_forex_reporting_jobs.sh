#!/usr/bin/env bash
# /root/.hermes/scripts/*.sh are GENERATED operational files.
# ops/hermes/*.sh are the AUTHORITATIVE repository copies.
set -euo pipefail

repo_root=/root/aether-forex-lab
repo_dir="$repo_root/ops/hermes"
install_dir=/root/.hermes/scripts
mode=install
if [[ ${1:-} == "--verify" ]]; then
  mode=verify
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--verify]" >&2
  exit 2
fi

check_forbidden() {
  local file=$1
  if [[ -f "$file" ]] && grep -Fq '/root/trading-agent' "$file"; then
    echo "refusing Hermes reporting install: forbidden legacy path in $file" >&2
    exit 1
  fi
}

verify_one() {
  local name=$1 repo_file="$repo_dir/$1" installed_file="$install_dir/$1"
  check_forbidden "$repo_file"
  check_forbidden "$installed_file"
  [[ -f "$repo_file" ]] || { echo "missing authoritative file: $repo_file" >&2; return 1; }
  [[ -f "$installed_file" ]] || { echo "missing installed file: $installed_file" >&2; return 1; }
  local repo_sha installed_sha
  repo_sha=$(sha256sum "$repo_file" | awk '{print $1}')
  installed_sha=$(sha256sum "$installed_file" | awk '{print $1}')
  [[ "$repo_sha" == "$installed_sha" ]] || {
    echo "SHA-256 mismatch for $name" >&2
    return 1
  }
  echo "$name SHA-256 verified: $installed_sha"
}

for name in trading_deliver_reports.sh trading_run.sh; do
  check_forbidden "$repo_dir/$name"
  check_forbidden "$install_dir/$name"
done

if [[ "$mode" == install ]]; then
  mkdir -p "$install_dir"
  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  for name in trading_deliver_reports.sh trading_run.sh; do
    if [[ -f "$install_dir/$name" ]]; then
      cp -p "$install_dir/$name" "$install_dir/$name.bak.$timestamp"
    fi
    install -m 0755 "$repo_dir/$name" "$install_dir/$name"
  done
fi

for name in trading_deliver_reports.sh trading_run.sh; do
  verify_one "$name"
done
