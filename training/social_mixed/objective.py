"""Pure tensor objective shared by training and read-only diagnostics."""
import torch

def stable_objective(log_probs, old, reference, mask, data, clip, kl_coef):
    ratio=(log_probs-old).exp()
    lengths=mask.sum(-1).clamp_min(1)
    denom=torch.where(data['task_denominator']>0,data['task_denominator'],lengths)
    def surrogate(adv):
        adv=adv[:,None]
        return -torch.minimum(ratio*adv,ratio.clamp(1-clip,1+clip)*adv)
    task=(surrogate(data['task_advantage'])*mask).sum(-1)/denom*data['task_weight']
    protocol=(surrogate(data['protocol_advantage'])*mask).sum(-1)/lengths*data['protocol_weight']
    delta=reference-log_probs
    kl=((delta.exp()-delta-1)*mask).sum(-1)/lengths*data['kl_weight']*kl_coef
    parts={'task':task.mean(),'protocol':protocol.mean(),'kl_weighted':kl.mean()}
    return sum(parts.values()),parts

