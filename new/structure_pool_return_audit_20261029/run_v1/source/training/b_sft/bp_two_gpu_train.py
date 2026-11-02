"""Run the formal DeepSpeed B/P experiment with one training initialization."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--model',required=True)
    args=parser.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)

    def run(command,name,env=None,monitor=False):
        print('Running: '+' '.join(command),flush=True)
        children=[];streams=[]
        with (root/name).open('w') as log:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
            try:
                if monitor:
                    stream=(root/'resources.monitor.log').open('w');streams.append(stream)
                    children.append(subprocess.Popen([sys.executable,'-u','-m','training.b_sft.bp_runtime_monitor',
                        '--pid',str(process.pid),'--output',str(root/'train.resources.jsonl')],
                        stdout=stream,stderr=subprocess.STDOUT,env=env))
                    stream=(root/'gpu.csv').open('w');streams.append(stream)
                    children.append(subprocess.Popen(['nvidia-smi','--id='+os.environ['CUDA_VISIBLE_DEVICES'],
                        '--query-gpu=timestamp,index,utilization.gpu,memory.used,memory.total,power.draw',
                        '--format=csv','-l','5'],stdout=stream,stderr=subprocess.STDOUT))
                for line in process.stdout:
                    log.write(line);log.flush();print(line,end='',flush=True)
                status=process.wait()
                if status:raise RuntimeError(f'Command failed ({status}); inspect {root/name}')
            finally:
                for child in [process,*children]:
                    if child.poll() is None:
                        child.terminate()
                        try:child.wait(timeout=5)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                for stream in streams:stream.close()
    try:
        run([sys.executable,'-m','training.b_sft.bp_cpu_preflight'],'cpu_contract.log')
        env=os.environ.copy();env['ROLL_LOG_DIR']=str(root/'environment_logs')
        run([sys.executable,'-c',
            'from pathlib import Path; import sys; from training.b_sft.bp_two_gpu_preflight import environment; environment(Path(sys.argv[1]),backend="deepspeed",check_fused=True)',
            str(root)],'environment.log',env)
        export=root/'export'
        run([sys.executable,'-m','training.b_sft.social_bp_grpo',
            '--data','examples/social_bp/data_two_a100_v1','--out',str(export),'--model',args.model],'export.log')
        manifest=json.loads((export/'manifest.json').read_text())
        if manifest['max_prompt_tokens']>2048:raise RuntimeError('Frozen prompts exceed 2048 tokens')
        train=root/'training'
        env=os.environ.copy();env.update(BP_RUN_DIR=str(train),BP_EXPORT_DIR=str(export),BP_MODEL=args.model,
            ROLL_OUTPUT_DIR=str(train),ROLL_LOG_DIR=str(train/'logs'))
        run([sys.executable,'-u','-m','training.b_sft.run_bp_two_gpu',
             '--config','grpo_two_a100_deepspeed'],'train.log',env,monitor=True)
        for marker in (train/'DRIVER_COMPLETE.json',train/'checkpoints/checkpoint-29/COMPLETE.json'):
            if not marker.is_file():raise RuntimeError(f'Missing completion evidence: {marker}')
        (root/'TRAINING_COMPLETE.json').write_text(json.dumps(dict(backend='deepspeed_train',
            optimizer_updates=30,validation_steps=[0,10,20,30],training_initializations=1),indent=2)+'\n')
        print('TRAINING_COMPLETE: '+str(root),flush=True)
    except BaseException as exc:
        (root/'TRAINING_FAILED.json').write_text(json.dumps(dict(error=repr(exc)),indent=2)+'\n')
        raise


if __name__=='__main__':main()
