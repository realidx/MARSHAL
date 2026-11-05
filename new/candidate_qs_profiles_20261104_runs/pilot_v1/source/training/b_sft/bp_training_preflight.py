"""Verify the exact resolved optimizer plan and record reproducibility inputs."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path


def main():
    from hydra import initialize_config_dir, compose
    from omegaconf import OmegaConf
    from dacite import from_dict
    from roll.pipeline.rlvr.rlvr_config import RLVRConfig
    from training.b_sft.social_bp_grpo import validate_export
    from training.b_sft.social_bp_training import CONTRACT
    with initialize_config_dir(config_dir=str(Path('examples/social_bp').resolve()), version_base=None):
        cfg = compose(config_name='grpo')
        resolved = OmegaConf.to_container(cfg, resolve=True)
    parsed = from_dict(RLVRConfig, resolved); parsed.set_max_steps(parsed.max_steps)
    assert Path(parsed.output_dir).resolve() == Path(os.environ['BP_RUN_DIR']).resolve()
    a = parsed.actor_train
    effective = a.world_size*a.training_args.per_device_train_batch_size*a.training_args.gradient_accumulation_steps
    assert effective == parsed.rollout_batch_size*parsed.num_return_sequences_in_group == 128
    assert parsed.ppo_epochs == 1 and parsed.max_steps == 100
    assert parsed.social_bp_curriculum and not parsed.social_b_curriculum
    assert parsed.validation.generating_args.num_return_sequences == 4 and parsed.eval_steps == 10
    assert set(a.device_mapping) == {0,1,2,3} and parsed.actor_infer.device_mapping == [4] and parsed.reference.device_mapping == [5]
    checks = validate_export(os.environ['BP_EXPORT_DIR'])
    sources = list(Path('training/b_sft').glob('*.py'))+list(Path('examples/social_bp').glob('*'))
    sources += list(Path('roll').rglob('*.py'))
    record = dict(contract=CONTRACT, effective_optimizer_batch=effective, adam_updates_per_rollout=1, resolved_config=resolved,
        data_checks=checks, versions={p: importlib.metadata.version(p) for p in ('torch','vllm','transformers','deepspeed','ray')},
        source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()})
    (Path(os.environ['BP_RUN_DIR'])/'run_manifest.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(dict(data_checks=checks,effective_optimizer_batch=effective,adam_updates_per_rollout=1)))


if __name__ == '__main__': main()
