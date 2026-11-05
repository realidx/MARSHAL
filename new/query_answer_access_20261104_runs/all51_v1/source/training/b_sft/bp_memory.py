"""Memory-only changes for native B/P DeepSpeed training."""


def trim_training_padding(data):
    """Drop right padding and align next-token targets; never discard active tokens."""
    import torch
    tensors=data.batch
    mask=tensors['attention_mask'].bool()
    width=mask.shape[-1]
    active=torch.nonzero(mask.any(dim=0),as_tuple=False).flatten()
    if not active.numel():raise ValueError('Training batch contains no active tokens')
    end=int(active[-1])+1
    if end<2:raise ValueError('Training requires a context and next-token target')
    if end==width:return data
    if tensors['response_mask'][:,end:].any():raise ValueError('Response outside attention mask')
    trimmed=tensors.clone(recurse=False)
    for key in ('input_ids','attention_mask','position_ids','response_mask'):
        if key in trimmed:
            assert trimmed[key].shape[-1]==width, (key,trimmed[key].shape,width)
            trimmed[key]=trimmed[key][...,:end].contiguous()
    for key in ('old_log_probs','ref_log_probs','advantages','final_response_mask'):
        if key in trimmed:
            assert trimmed[key].shape[-1]==width-1, (key,trimmed[key].shape,width)
            trimmed[key]=trimmed[key][...,:end-1].contiguous()
    return type(data)(batch=trimmed,non_tensor_batch=data.non_tensor_batch,meta_info=data.meta_info)


def check_fused_adamw():
    """Small real CUDA update, offload/reload and restore before loading any LLM."""
    import copy
    import torch
    from roll.third_party.deepspeed.offload_states import offload_adam_states, reload_adam_states
    results=[]
    for device in range(torch.cuda.device_count()):
        with torch.cuda.device(device):
            initial=torch.linspace(-1,1,1024,device='cuda',dtype=torch.float32)
            p=torch.nn.Parameter(initial.clone());q=torch.nn.Parameter(initial.clone())
            fused=torch.optim.AdamW([p],lr=1e-6,weight_decay=0.,fused=True)
            plain=torch.optim.AdamW([q],lr=1e-6,weight_decay=0.,foreach=False)
            for index in range(3):
                grad=torch.sin(initial+index)
                p.grad=grad.clone();q.grad=grad.clone()
                fused.step();plain.step()
                torch.testing.assert_close(p,q,rtol=1e-6,atol=1e-7)
                offload_adam_states(fused,torch.device('cpu'),pin_memory=False)
                assert all(s[key].device.type=='cpu' for s in fused.state.values()
                           for key in ('exp_avg','exp_avg_sq'))
                reload_adam_states(fused,torch.device('cuda',device))
                assert all(s[key].device==p.device for s in fused.state.values()
                           for key in ('exp_avg','exp_avg_sq'))
                state=copy.deepcopy(fused.state_dict())
                # Native torch load_state_dict must preserve the fused CUDA step tensor.
                replacement=torch.optim.AdamW([p],lr=1e-6,weight_decay=0.,fused=True)
                replacement.load_state_dict(state);fused=replacement
            torch.cuda.synchronize()
            results.append(dict(device=device,updates=3,offload_and_state_restore=True))
    return results
