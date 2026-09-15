from types import SimpleNamespace

import pytest
import torch

from training.b_sft.bp_cpu_preflight import load_cpu_path
from training.b_sft.bp_memory import trim_training_padding


def fixture(length=6,width=16,entropy=0.):
    scope=load_cpu_path();proto=scope['DataProto']
    attention=torch.zeros(1,width,dtype=torch.long);attention[:,:length]=1
    response=attention.clone();response[:,:2]=0
    data=proto.from_dict(tensors=dict(input_ids=torch.arange(width).view(1,-1)%23,
        attention_mask=attention,position_ids=torch.arange(width).view(1,-1),response_mask=response,
        final_response_mask=response[:,1:].clone(),old_log_probs=torch.zeros(1,width-1),
        ref_log_probs=torch.zeros(1,width-1),advantages=torch.linspace(-1,1,width-1).view(1,-1)))
    calls=[]
    def entropy_fn(**kwargs):
        calls.append(True);return scope['op_compute_entropy'](None,**kwargs)
    strategy=SimpleNamespace(op_compute_log_probs=lambda **kw:scope['op_compute_log_probs'](None,**kw),
        op_compute_entropy=entropy_fn)
    cfg=SimpleNamespace(pg_clip=.2,pg_clip_high=.2,dual_clip_loss=False,
        loss_agg_mode='seq-mean-token-mean',use_kl_loss=True,kl_loss_coef=.01,entropy_loss_coef=entropy)
    return scope,data,SimpleNamespace(strategy=strategy,pipeline_config=cfg),calls


@pytest.mark.parametrize('length',[3,6,16])
@pytest.mark.parametrize('entropy',[0.,.01])
def test_trim_preserves_actual_grpo_loss_and_logits_gradients(length,entropy):
    scope,data,actor,calls=fixture(length=length,entropy=entropy)
    torch.manual_seed(7)
    logits=torch.randn(1,16,23,requires_grad=True)
    old=actor.strategy.op_compute_log_probs(logits=logits,input_ids=data.batch['input_ids'],
        attention_mask=data.batch['response_mask']).detach()
    data.batch['old_log_probs']=old+.02;data.batch['ref_log_probs']=old-.03
    loss,_=scope['loss_func'](actor,data,logits);loss.backward()
    trimmed=trim_training_padding(data)
    shorter=logits.detach()[:,:length].clone().requires_grad_(True)
    new_loss,_=scope['loss_func'](actor,trimmed,shorter);new_loss.backward()
    torch.testing.assert_close(loss,new_loss)
    torch.testing.assert_close(logits.grad[:,:length],shorter.grad)
    assert torch.count_nonzero(logits.grad[:,length:])==0
    assert data.batch['input_ids'].shape[-1]==16  # caller batch is untouched
    assert trimmed.batch['final_response_mask'].shape[-1]==length-1
    assert len(calls)==(2 if entropy else 0)


def test_trim_rejects_dropping_response_tokens():
    _,data,_,_=fixture()
    data.batch['response_mask'][0,14]=1
    with pytest.raises(ValueError,match='Response outside'):trim_training_padding(data)


def test_tiny_qwen3_padding_has_equal_loss_and_parameter_gradients():
    from transformers import Qwen3Config,Qwen3ForCausalLM
    scope,data,actor,_=fixture(length=6)
    torch.manual_seed(1)
    cfg=Qwen3Config(vocab_size=23,hidden_size=32,intermediate_size=64,
        num_hidden_layers=1,num_attention_heads=2,num_key_value_heads=1,head_dim=16,
        attention_dropout=0.,use_cache=False)
    cfg._attn_implementation='sdpa'
    model=Qwen3ForCausalLM(cfg).float()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.train()
    def forward(batch):
        return model(**{k:batch.batch[k] for k in ('input_ids','attention_mask','position_ids')}).logits
    logits=forward(data)
    old=actor.strategy.op_compute_log_probs(logits=logits,input_ids=data.batch['input_ids'],
        attention_mask=data.batch['response_mask']).detach()
    data.batch['old_log_probs']=old+.02;data.batch['ref_log_probs']=old-.03
    loss,_=scope['loss_func'](actor,data,logits);loss.backward()
    gradients={n:p.grad.clone() for n,p in model.named_parameters()}
    model.zero_grad(set_to_none=True)
    short=trim_training_padding(data)
    new_loss,_=scope['loss_func'](actor,short,forward(short));new_loss.backward()
    torch.testing.assert_close(loss,new_loss,atol=1e-6,rtol=1e-5)
    for n,p in model.named_parameters():
        torch.testing.assert_close(gradients[n],p.grad,atol=2e-6,rtol=1e-4)
