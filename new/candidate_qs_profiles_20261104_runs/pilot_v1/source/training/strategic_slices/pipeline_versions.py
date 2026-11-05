"""Require a registered, source-matched configuration snapshot before launch."""
import json
import os
from pathlib import Path
from .common import file_hash

ROOT=Path(__file__).resolve().parents[2]
REGISTRY=ROOT/'examples/strategic_slices/versions'


def registered_snapshot(version,prompt_version):
    index=json.loads((REGISTRY/'index.json').read_text())
    if version not in index['versions']:raise ValueError('Unregistered pipeline version; create a new snapshot first')
    path=REGISTRY/index['versions'][version]
    record=json.loads(path.read_text())
    if record['version']!=version or record['prompt_version']!=prompt_version:raise ValueError('Snapshot contract differs')
    for name,sha in record['contract_sources'].items():
        if file_hash(ROOT/name)!=sha:raise ValueError('Versioned source changed without a new snapshot: '+name)
    for name,sha in record['review_files'].items():
        if file_hash(path.parent/name)!=sha:raise ValueError('Frozen review artifact changed: '+name)
    return dict(version=version,prompt_version=prompt_version,
        path=str(path.relative_to(ROOT)),sha256=file_hash(path))


def write_run_snapshot(root,registered,options,resolved_config,contract,sources,model_hashes):
    # Every launch records actual CLI/profile overrides, not just defaults.
    env_keys=('SLURM_JOB_ID','SLURM_CPUS_PER_TASK','CUDA_VISIBLE_DEVICES','SOCIAL_GPU_PROFILE',
        'SOCIAL_SEQUENCE_PARALLEL','SOCIAL_TRANSFORMER_IMPL','SOCIAL_NVTE_FLASH_ATTN',
        'SOCIAL_NVTE_FUSED_ATTN','SOCIAL_NVTE_UNFUSED_ATTN','CUDA_HOME','CONDA_PREFIX',
        'VLLM_BATCH_INVARIANT','VLLM_TOOL_CALL_PARSER','CUDA_DEVICE_MAX_CONNECTIONS',
        'NCCL_SOCKET_IFNAME','GLOO_SOCKET_IFNAME','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS')
    snapshot=dict(schema=1,registered_version=registered,status='launched-not-completed',
        launch_environment={name:os.environ.get(name) for name in env_keys},
        actual_options=options,resolved_config=resolved_config,run_contract=contract,
        source_manifest=sources,model_hashes=model_hashes)
    with (Path(root)/'pipeline_snapshot.json').open('x') as handle:
        json.dump(snapshot,handle,ensure_ascii=False,indent=2);handle.write('\n')
