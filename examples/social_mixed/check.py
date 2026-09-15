"""CPU-only input/rollout/token-budget check; never queries a model."""
import argparse
import json
import random
import unittest
from pathlib import Path


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--tokenizer',type=Path)
    args=cli.parse_args()
    from training.social_mixed import test_core
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromModule(test_core))
    if not result.wasSuccessful():raise SystemExit(1)
    if args.tokenizer:
        from transformers import AutoTokenizer
        from training.social_mixed.core import load_data,Episode
        from training.b_sft.social_named_probe import request
        tokenizer=AutoTokenizer.from_pretrained(args.tokenizer,local_files_only=True)
        sizes=[]
        def check(req):
            n=len(tokenizer.apply_chat_template(req['messages'],tools=req['tools'],tokenize=True,add_generation_prompt=True))
            if n+1024>4096:raise ValueError(f'Context budget exceeded: {n}+1024')
            sizes.append(n)
        data=load_data()
        for split in ('train','validation'):
            for task in data[f'bp_{split}']:check(request(task,'action_tools',task.get('name_variant',0)))
            for reset in data[f'selfplay_{split}']:
                e=Episode(reset,'check',0,42);rng=random.Random(42)
                while e.status=='running':
                    check(e.request());e.accept(test_core.legal_response(e,rng))
        print(json.dumps(dict(tokenizer=str(args.tokenizer),checked_prompts=len(sizes),max_prompt_tokens=max(sizes),max_response_tokens=1024)))


if __name__=='__main__':main()
