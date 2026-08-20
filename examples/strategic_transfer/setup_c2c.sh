#!/usr/bin/env bash
set -euo pipefail

repo_dir="${1:-third_party/cooperate-to-compete}"
expected_commit="2f7eb4a163d21e139a3ea8b9f7d625b470594f00"

if [[ ! -d "${repo_dir}/.git" ]]; then
  git clone --no-checkout https://github.com/abbykoneill/negotiationgames.git "${repo_dir}"
  git -C "${repo_dir}" checkout --detach "${expected_commit}"
fi

actual_commit="$(git -C "${repo_dir}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${expected_commit}" ]]; then
  echo "C2C commit mismatch: expected ${expected_commit}, found ${actual_commit}" >&2
  echo "Use a checkout at the pinned commit before collecting results." >&2
  exit 1
fi

python -m pip install -e "${repo_dir}[analysis]"
