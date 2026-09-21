"""Read-only representative parameter gradients from saved training calls.

Run inside an allocated GPU job. No optimizer, no generation, no remote submission.
This HF check complements, and does not certify, Megatron distributed updates.
"""
import argparse
import gc
import json
from pathlib import Path
import torch


def main():
    from transformers import AutoModelForCausalLM
    from training.social_mixed.objective import stable_objective
    cli=argparse.ArgumentParser()
    for name in ('model','reference','calls','output'):cli.add_argument('--'+name,required=True)
    cli.add_argument('--rows',type=int,default=16)
    a=cli.parse_args()
    rows=[json.loads(x) for x in Path(a.calls).read_text().splitlines()]
    # Round-robin across domain/protocol strata; deliberately a diagnostic subset.
    groups={}
    for r in rows:groups.setdefault((r['kind'],bool(r.get('protocol_failure'))),[]).append(r)
    selected=[]
    while len(selected)<a.rows and any(groups.values()):
        for rs in groups.values():
            if rs and len(selected)<a.rows:selected.append(rs.pop(0))
    if not selected:raise ValueError('No recorded calls')
    device='cuda'
    def load(path):return AutoModelForCausalLM.from_pretrained(path,torch_dtype=torch.bfloat16).to(device).eval()
    def logprobs(model,r):
        ids=torch.tensor([r['prompt_ids']+r['response_ids']],device=device)
        logits=model(ids,use_cache=False).logits[:,:-1].float()
        return torch.log_softmax(logits,-1).gather(-1,ids[:,1:,None]).squeeze(-1)[:,len(r['prompt_ids'])-1:]
    reference=load(a.reference)
    with torch.no_grad():refs=[logprobs(reference,r).cpu() for r in selected]
    del reference;gc.collect();torch.cuda.empty_cache()
    actor=load(a.model)
    norms=[(name,p) for name,p in actor.named_parameters() if 'norm' in name and p.ndim==1]
    representatives=norms[:1]+norms[-1:]
    if not representatives:raise ValueError('No representative norm parameters')
    parameters=[p for _,p in representatives]
    domains=sorted({r['kind'] for r in selected})
    sums={k:[torch.zeros_like(p,dtype=torch.float32) for p in parameters] for k in domains+['protocol','kl_weighted']}
    ratios=[]
    for r,ref in zip(selected,refs):
        lp=logprobs(actor,r);old=torch.tensor([r['behavior_log_probs']],device=device)
        d={k:torch.tensor([r[k]],device=device) for k in ('task_advantage','protocol_advantage','task_weight','protocol_weight','kl_weight','task_denominator')}
        _,parts=stable_objective(lp,old,ref.to(device),torch.ones_like(lp),d,.2,.01)
        ratios.append(float((lp.detach()-old).abs().mean()))
        for name,loss in parts.items():
            key=r['kind'] if name=='task' else name
            grads=torch.autograd.grad(loss,parameters,retain_graph=True,allow_unused=True)
            for total,g in zip(sums[key],grads):
                if g is not None:total.add_(g.detach().float()/len(selected))
        del lp,parts
    flat={k:torch.cat([g.flatten() for g in gs]) for k,gs in sums.items()}
    result=dict(rows=len(selected),model=a.model,reference=a.reference,calls=a.calls,
                parameters=[n for n,_ in representatives],
                gradient_norms={k:float(g.norm()) for k,g in flat.items()},
                task_cosines={a+':'+b:(float(torch.nn.functional.cosine_similarity(flat[a],flat[b],dim=0))
                    if flat[a].norm()>0 and flat[b].norm()>0 else None)
                    for j,a in enumerate(domains) for b in domains[j+1:]},
                mean_abs_actor_behavior_logprob_delta=sum(ratios)/len(ratios),
                limitation='HF diagnostic subset, two norm tensors; not full parameter gradients, not Megatron clipping/update verification. Use matching actor checkpoint and saved calls.')
    Path(a.output).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
