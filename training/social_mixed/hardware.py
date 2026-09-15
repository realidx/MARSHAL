"""Fixed execution profiles; no change to rewards, sampling or token budgets."""
PROFILES={
 'h100-47':dict(gpus=2,tp=2,train_microbatch=1,reference_microbatch=1,train_resident=False,reference_resident=False,vllm_memory=.50,max_num_seqs=16,recompute='full'),
 'h100-96':dict(gpus=2,tp=2,train_microbatch=2,reference_microbatch=4,train_resident=False,reference_resident=True,vllm_memory=.55,max_num_seqs=16,recompute='full'),
 'h200-141':dict(gpus=1,tp=1,train_microbatch=2,reference_microbatch=4,train_resident=False,reference_resident=True,vllm_memory=.45,max_num_seqs=32,recompute='full'),
}
def apply(config,name):
 if name not in PROFILES:raise ValueError('Unknown SOCIAL_GPU_PROFILE: '+name)
 p=PROFILES[name]
 config.num_gpus_per_node=p['gpus']
 for worker in (config.actor_train,config.actor_infer,config.reference):
  worker.device_mapping=str(list(range(p['gpus'])))
 config.actor_train.strategy_args.strategy_config.tensor_model_parallel_size=p['tp']
 config.actor_train.strategy_args.strategy_config.sequence_parallel=p['tp']>1
 config.actor_train.training_args.per_device_train_batch_size=p['train_microbatch']
 config.actor_train.keep_states_on_device=p['train_resident']
 config.reference.infer_batch_size=p['reference_microbatch']
 config.reference.keep_states_on_device=p['reference_resident']
 config.actor_infer.strategy_args.strategy_config.gpu_memory_utilization=p['vllm_memory']
 config.actor_infer.strategy_args.strategy_config.max_num_seqs=p['max_num_seqs']
 config.actor_infer.strategy_args.strategy_config.enable_prefix_caching=True
 config.actor_train.strategy_args.strategy_config.recompute_granularity=p['recompute']
 return dict(p)
