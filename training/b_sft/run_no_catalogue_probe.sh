#!/usr/bin/env bash
# Frozen-model diagnostic only. No optimizer or model-server mutations.
set -euo pipefail
probe_bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_python=/raid/chenjiahao/conda_envs/mas/bin/python
probe_output="${1:-${probe_bundle_dir}/../results}"
if [[ $# -gt 0 ]]; then shift; fi
probe_endpoints=("$@")
if [[ ${#probe_endpoints[@]} -eq 0 ]]; then
    for port in 8000 8001 8002 8003 8004 8005 8006 8007; do
        probe_endpoints+=("http://127.0.0.1:${port}/v1")
    done
fi
"$probe_python" - "$probe_bundle_dir" "${probe_endpoints[@]}" <<'PY'
import hashlib,json,sys
from pathlib import Path
from urllib.request import urlopen
bundle=Path(sys.argv[1])
manifest=json.loads((bundle/'manifest.json').read_text())
for name,expected in manifest['files'].items():
    if hashlib.sha256((bundle/name).read_bytes()).hexdigest()!=expected:
        raise SystemExit('Bundle checksum mismatch: '+name)
for endpoint in sys.argv[2:]:
    try:
        with urlopen(endpoint+'/models',timeout=10) as r:body=json.load(r)
        if not any(m['id']=='social-base' for m in body['data']):raise ValueError('social-base is unavailable')
    except Exception as exc:
        raise SystemExit(f'Endpoint check failed: {endpoint}: {exc}')
    print('Ready:',endpoint)
PY
if [[ -e "$probe_output" ]]; then
    echo "Output already exists: $probe_output. Select a fresh directory."
    exit 1
fi
mkdir -p "$probe_output"
set -o pipefail
echo "Preflight: B/P output-interface representatives in parallel across ${#probe_endpoints[@]} configured services; protocol errors are recorded, not a launch gate."
"$probe_python" -u "$probe_bundle_dir/remote_bp_probe.py" \
    --requests "$probe_bundle_dir/requests.jsonl" --out "$probe_output/preflight" \
    --base-urls "${probe_endpoints[@]}" --model social-base --preflight \
    2>&1 | tee "$probe_output/preflight.log"
echo "Formal sampling: all ${#probe_endpoints[@]} services, 8 samples per request condition."
"$probe_python" -u "$probe_bundle_dir/remote_bp_probe.py" \
    --requests "$probe_bundle_dir/requests.jsonl" --out "$probe_output/probe" \
    --base-urls "${probe_endpoints[@]}" --model social-base --group-size 8 \
    2>&1 | tee "$probe_output/probe.log"
echo "Complete. Download $probe_output for local scoring and reasoning analysis."
