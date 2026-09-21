"""CPU SP/O coverage and initial-state audit; no model generation or submission."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random

from training.social_mixed.core import Episode, load_data
from training.social_mixed.curriculum_sampling import reset_order
from training.social_mixed.reasoning_bank import load
from training.social_mixed.reasoning_training import ReasoningCollector


def audit(tokenizer=None):
    data=load_data()
    data['bp_train']=load('train')
    c=ReasoningCollector(data,lambda _:[],seed=42,concurrency=8)
    resets=data['selfplay_train']
    size=len(reset_order(resets,random.Random(42)))
    sequence=[c.next_training_reset(resets) for _ in range(size)]
    counts=Counter(r['id'] for r in sequence)
    assert set(counts)=={r['id'] for r in resets}, 'SP cycle misses resets'
    state=deepcopy(c.state)
    expected=[c.next_training_reset(resets)['id'] for _ in range(31)]
    c.restore(state)
    assert expected==[c.next_training_reset(resets)['id'] for _ in range(31)]
    lengths=[]
    for reset in resets:
        req=Episode(reset,'preflight',0,42).request()
        if tokenizer is not None:
            rendered=tokenizer.apply_chat_template(
                req['messages'],tools=req['tools'],tokenize=True,
                add_generation_prompt=True,return_dict=True)
            ids=rendered['input_ids']
            if (not isinstance(ids,list) or not ids or
                    any(not isinstance(token_id,int) for token_id in ids)):
                raise TypeError('Tokenizer must return one unbatched input_ids list')
            lengths.append(dict(id=reset['id'],tokens=len(ids)))
    failures=[r for r in lengths if r['tokens']>3072]
    tasks=[t for t in data['bp_train'] if t['paired_view']=='O']
    return dict(passed=not failures,sp_resets=len(resets),sp_schedule_groups=size,
                sp_min_visits=min(counts.values()),sp_max_visits=max(counts.values()),
                sp_cycle_coverage=1.,sp_resume_sequence_equal=True,
                sp_initial_requests_rendered=len(resets),context_checked=tokenizer is not None,
                context_failures=failures,context_scope='SP initial states only; runtime checks every later prompt',
                O_cases=len(tasks),O_parents=len({t['package_id'] for t in tasks}),
                O_source_cells=dict(Counter(t['source_kernel']+'/'+t['completion_mode'] for t in tasks)),
                caveat='A complete sampling cycle is not a promised token-budget exposure; actual games depend on response length.',
                Q0_generation='not performed',GPU_acceptance='not performed')


def main():
    cli=argparse.ArgumentParser();cli.add_argument('--output',required=True);cli.add_argument('--tokenizer')
    args=cli.parse_args();tokenizer=None
    if args.tokenizer:
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(args.tokenizer,local_files_only=True,trust_remote_code=True)
    result=audit(tokenizer)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    if not result['passed']:raise SystemExit('SP prompt length acceptance failed')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
