"""Create a new immutable version record. Refuse overwriting any version.

Write the human comparison/change entry and prompt examples before freezing.
Actual launches additionally persist their full resolved configuration.
"""
import ast
import argparse
import json
from pathlib import Path
from training.strategic_slices.common import file_hash
from training.strategic_slices.terminal_training import VERSION,CONTRACT,TrainingData
from training.strategic_slices.named_prompt import VERSION as PROMPT_VERSION
from training.strategic_slices.train_terminal import source_identity
from training.strategic_slices.terminal_training_schedule import (
    DEFAULT_NODE_GROUPS_PER_UPDATE,DEFAULT_EVAL_TOKENS,DEFAULT_SAVE_TOKENS)
from training.social_mixed.hardware import PROFILES

ROOT=Path(__file__).resolve().parents[2]
REGISTRY=ROOT/'examples/strategic_slices/versions'


def defaults():
    env=dict(ROOT=ROOT,DEFAULT_NODE_GROUPS_PER_UPDATE=DEFAULT_NODE_GROUPS_PER_UPDATE,
        DEFAULT_EVAL_TOKENS=DEFAULT_EVAL_TOKENS,DEFAULT_SAVE_TOKENS=DEFAULT_SAVE_TOKENS)
    def value(n):
        if isinstance(n,ast.Constant):return n.value
        if isinstance(n,ast.Name):return env[n.id]
        if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Div):return value(n.left)/value(n.right)
        if isinstance(n,(ast.List,ast.Tuple)):return [value(v) for v in n.elts]
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Path':return Path(value(n.args[0]))
        raise ValueError('Unresolved CLI default: '+ast.unparse(n))
    result={}
    tree=ast.parse((ROOT/'training/strategic_slices/train_terminal.py').read_text())
    for n in ast.walk(tree):
        if not isinstance(n,ast.Call) or not isinstance(n.func,ast.Attribute) or n.func.attr!='add_argument':continue
        kw={k.arg:k.value for k in n.keywords};flag=value(n.args[0]);default=value(kw['default']) if 'default' in kw else False if 'action' in kw and value(kw['action'])=='store_true' else None
        result[flag]=dict(default=str(default) if isinstance(default,Path) else default,
            choices=value(kw['choices']) if 'choices' in kw else None,required=value(kw['required']) if 'required' in kw else False)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',help='New directory name under versions; defaults to the recipe version')
    parser.add_argument('--parent',help='Parent registered version; defaults to the current active version')
    args=parser.parse_args()
    index_path=REGISTRY/'index.json';index=json.loads(index_path.read_text())
    if VERSION in index['versions']:raise ValueError('Version already frozen; increment VERSION instead of overwriting')
    folder=REGISTRY/(args.directory or VERSION)
    if folder.parent!=REGISTRY:raise ValueError('Use a simple version directory name')
    parent=args.parent or index['active']
    if parent not in index['versions']:raise ValueError('Parent version is not registered')
    if not (folder/'CHANGELOG.md').is_file() or not (folder/'PROMPT_PREVIEW.md').is_file():
        raise ValueError('Create CHANGELOG.md and a full PROMPT_PREVIEW.md first')
    sources=source_identity()
    data=TrainingData(ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4',
        ROOT/'new/local_data/strategic_slices_terminal_selected_v4')
    asset_paths=[data.pool.root/'manifest.json',data.pool.root/'CANDIDATES_VERIFIED.json',
        data.selection/'SELECTION.json',data.selection/'COMPLETE.json',
        ROOT/'new/local_data/strategic_slices_terminal_d_v4_analysis/COMPLETE.json']
    assets={str(p.relative_to(ROOT)):file_hash(p) for p in asset_paths}
    critical={name:sha for name,sha in sources.items() if '/test_' not in name}
    for name in ('examples/strategic_slices/sbatch_terminal_train.sh','examples/social_mixed/run_config.yaml'):
        if (ROOT/name).is_file():critical[name]=file_hash(ROOT/name)
    yaml={str(p.relative_to(ROOT)):p.read_text() for p in (ROOT/'examples/social_mixed').glob('*.yaml')}
    preview_hashes={p.name:file_hash(p) for p in folder.iterdir() if p.is_file() and p.name!='SNAPSHOT.json'}
    record=dict(schema=1,version=VERSION,prompt_version=PROMPT_VERSION,status='implemented-CPU-checked-not-GPU-run',
        parent=parent,contract=CONTRACT,cli_defaults=defaults(),
        hardware_profiles=PROFILES,base_yaml_contents=yaml,contract_sources=critical,source_manifest=sources,
        dataset_sha256=data.sha,data_selection_D_files=assets,
        review_files=preview_hashes,selection_measurement='Frozen selected-v4 uses historical JSON/act D; no new-prompt D claimed',
        gpu_tested=False,submitted=False)
    path=folder/'SNAPSHOT.json'
    with path.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2);f.write('\n')
    index['versions'][VERSION]=str(path.relative_to(REGISTRY));index['active']=VERSION
    index_path.write_text(json.dumps(index,indent=2)+'\n')
    print(path)


if __name__=='__main__':main()
