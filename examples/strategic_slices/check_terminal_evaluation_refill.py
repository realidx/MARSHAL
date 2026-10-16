"""CPU report equivalence on frozen validation data; synthetic responses only."""
import argparse
from pathlib import Path
from training.social_mixed.native_stream import BatchStream
from training.strategic_slices.common import write_json
from training.strategic_slices.train_terminal import ROOT
from training.strategic_slices.terminal_training import TrainingData,mock_generate
from training.strategic_slices.terminal_training_evaluate import Validator


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--limit',type=int,default=4)
    cli.add_argument('--concurrency',type=int,default=8)
    args=cli.parse_args()
    if args.output.exists() or args.limit<1 or args.concurrency<1:raise ValueError('Use a new output and positive limits')
    data=TrainingData(ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4',
        ROOT/'new/local_data/strategic_slices_terminal_selected_v4')
    cfg=dict(seed=42,workers=args.concurrency,max_tokens=1024,context=16384,temperature=0.,
        top_p=1.,top_k=-1,repetition_penalty=1.)
    old=Validator(data,mock_generate,cfg,limit=args.limit).run()
    current=Validator(data,mock_generate,cfg,limit=args.limit,stream_factory=lambda n:BatchStream(mock_generate,n))
    new=current.run()
    if old!=new:raise AssertionError('Evaluation reports differ under frozen cohort/seeds')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    write_json(args.output,dict(dataset_sha256=data.sha,split='validation',limit=args.limit,
        old_and_refill_reports_equal=True,slice_episodes=new['slices']['episodes'],
        parents=len({g['parent_id'] for g in new['slice_games']}),full_game_episodes=len(new['full_games']['games']),
        generated_response_tokens=new['generated_response_tokens'],execution=current.last_execution,
        synthetic_responses=True,new_model_calls=0,gpu_tested=False,
        limitation='CPU frozen-data report equivalence; synchronous stream adapter, not a throughput benchmark.'))
    print('Frozen validation report equivalence passed',flush=True)


if __name__=='__main__':main()
