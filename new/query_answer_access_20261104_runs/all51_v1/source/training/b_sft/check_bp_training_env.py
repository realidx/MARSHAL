"""CPU import/contract preflight; does not install packages or load weights."""
import importlib.metadata
import json
import os


def main():
    expected = {'vllm': '0.8.5.post1', 'torch': '2.6.0', 'transformers': '4.51.3',
                'deepspeed': '0.16.4', 'ray': '2.46.0'}
    actual = {p: importlib.metadata.version(p) for p in expected}
    for p, v in expected.items():
        if actual[p].split('+')[0] != v: raise RuntimeError(f'{p}={actual[p]}; use the isolated BP training environment ({v})')
    if os.environ.get('VLLM_USE_V1') != '0': raise RuntimeError('ROLL adapter requires VLLM_USE_V1=0')
    from roll.pipeline.rlvr.rlvr_pipeline import RLVRPipeline
    from training.b_sft.social_bp_reward_worker import SocialBPRewardWorker
    from roll.third_party.vllm import LLM
    if LLM is None: raise RuntimeError('Missing vLLM training adapter')
    print(json.dumps(dict(versions=actual, imports_passed=True, gpu_tested=False)))


if __name__ == '__main__': main()
