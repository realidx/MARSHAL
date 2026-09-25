#!/usr/bin/env bash
#SBATCH --job-name=export-bp139-hf
#SBATCH --partition=normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/e/e1300530/tmp/export-bp139-hf-%j.out
#SBATCH --error=/home/e/e1300530/tmp/export-bp139-hf-%j.err

set -euo pipefail
if [[ $# -ne 2 ]]; then echo "usage: sbatch $0 CHECKPOINT OUTPUT" >&2; exit 2; fi
checkpoint=$1
output=$2
converter_repo=/home/e/e1300530/tmp/MARSHAL-train-new-20260918-0f6d73a

# The old shared Git worktree metadata has disappeared; pin the converter file
# content directly so this export keeps using the previously verified code.
echo 'c78f027ba83088ba2b31f29c03823de43f45ea7b96ece983ad3c2e3f74c2dd30  /home/e/e1300530/tmp/MARSHAL-train-new-20260918-0f6d73a/mcore_adapter/src/mcore_adapter/models/converter/post_converter.py' | sha256sum -c -
[[ ! -e "$output" ]]
python - "$checkpoint" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); meta=json.loads((p/'COMPLETE.json').read_text())
for rel,size in meta['files'].items():
    f=p/rel
    if not f.is_file() or f.stat().st_size != size: raise RuntimeError(f'incomplete checkpoint file: {f}')
print('native checkpoint manifest verified:',p)
PY

source /home/e/e1300530/miniconda3/etc/profile.d/conda.sh
conda activate /home/e/e1300530/tmp/marshal-vllm09
export PYTHONPATH="$converter_repo:$converter_repo/mcore_adapter/src:$converter_repo/third_party/negotiation_benchmark/src:${PYTHONPATH:-}"
cd "$converter_repo"
python -u -m training.social_mixed.export "$checkpoint" "$output"

python - "$output" "$checkpoint" <<'PY'
import hashlib,json,sys
from pathlib import Path
from transformers import AutoConfig,AutoTokenizer,AutoModelForCausalLM
p=Path(sys.argv[1]); source=Path(sys.argv[2]).resolve(); weights=sorted(p.glob('*.safetensors'))
assert weights and sum(x.stat().st_size for x in weights)>7_000_000_000
assert Path(json.loads((p/'export_source.json').read_text())['checkpoint'])==source
c=AutoConfig.from_pretrained(p,trust_remote_code=True,local_files_only=True)
t=AutoTokenizer.from_pretrained(p,trust_remote_code=True,local_files_only=True)
m=AutoModelForCausalLM.from_pretrained(p,trust_remote_code=True,local_files_only=True,device_map='cpu',low_cpu_mem_usage=True)
h=hashlib.sha256()
for w in weights:
    with w.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
report={'checkpoint':str(source),'export':str(p.resolve()),'weight_bytes':sum(x.stat().st_size for x in weights),'weights_sha256':h.hexdigest(),'model_type':c.model_type,'vocab_size':c.vocab_size,'tokenizer_size':len(t),'loaded_class':type(m).__name__}
(p/'EXPORT_VERIFIED.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
PY
