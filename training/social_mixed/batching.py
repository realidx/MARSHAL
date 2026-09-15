"""Length trimming and loss-preserving padding for native social batches."""
import math
import torch

def trim(data,multiple=2):
 width=data.batch['input_ids'].shape[1]
 length=int(data.batch['attention_mask'].sum(-1).max().item())
 target=min(width,math.ceil(length/multiple)*multiple)
 data.meta_info=dict(data.meta_info,social_original_width=width)
 for key,value in list(data.batch.items()):
  if value.ndim==2 and value.shape[1]==width:data.batch[key]=value[:,:target]
  elif value.ndim==2 and value.shape[1]==width-1:data.batch[key]=value[:,:target-1]
 return data

def pad_weights(weights,padded_count):
 count=len(weights)
 if padded_count<count:raise ValueError('Cannot drop rows')
 return torch.cat((weights*(padded_count/count),weights.new_zeros(padded_count-count)))

def balanced_order(lengths,replicas=2):
 if len(lengths)%replicas:raise ValueError('Pad replicas before distributing rows')
 ranked=sorted(range(len(lengths)),key=lambda i:lengths[i])
 return [i for rank in range(replicas) for i in ranked[rank::replicas]]
