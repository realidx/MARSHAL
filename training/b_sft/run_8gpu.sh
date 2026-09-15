#!/usr/bin/env bash
set -euo pipefail
# Backwards-compatible name; GPU selection and process count are now explicit/dynamic.
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/run_shared.sh" "$@"
