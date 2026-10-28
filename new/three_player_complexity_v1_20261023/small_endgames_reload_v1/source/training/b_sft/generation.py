"""Synchronized ZeRO-3 generation: batch one, last-position logits, no weight gathering."""

import math
import hashlib
import random
import time
from contextlib import contextmanager

from .semantic import parse_response


def prepare_prompts(records, tokenizer, max_length, max_new_tokens):
    prompts = []
    for row in records:
        text = tokenizer.apply_chat_template(row['messages'][:-1], tools=row['tools'],
                                             tokenize=False, add_generation_prompt=True)
        ids = tokenizer(text, add_special_tokens=False)['input_ids']
        if len(ids) + max_new_tokens > max_length:
            raise ValueError(f"Generation budget exceeds max-length for {row['id']}: "
                             f'{len(ids)} + {max_new_tokens} > {max_length}; refusing truncation')
        prompts.append(dict(id=row['id'], source_id=row['source_id'], prompt=text,
                            allow_preface=row.get('allow_reasoning', True),
                            input_ids=ids))
    return prompts


def rank_indices(size, rank, world_size):
    """Every rank must call generate equally often, even when the split is tiny."""
    for start in range(0, size, world_size):
        index = start + rank
        yield (min(index, size - 1), index < size)


@contextmanager
def preserve_rng():
    import numpy as np
    import torch
    python_state, numpy_state = random.getstate(), np.random.get_state()
    try:
        devices = [torch.cuda.current_device()] if torch.cuda.is_available() else []
        with torch.random.fork_rng(devices=devices):
            yield
    finally:
        random.setstate(python_state)
        np.random.set_state(numpy_state)


def generate_predictions(trainer, prompts, tokenizer, max_new_tokens, backend):
    import torch
    from transformers import GenerationConfig
    rank, world_size = trainer.args.process_index, trainer.args.world_size
    # ZeRO hooks remain installed. Do not use GatheredParameters / unwrap-for-full-weight generation.
    model = trainer.accelerator.unwrap_model(trainer.model_wrapped)
    eos = model.generation_config.eos_token_id
    if eos is None:
        eos = tokenizer.eos_token_id
    if eos is None:
        raise ValueError('Generation requires an EOS token')
    eos_ids = [eos] if isinstance(eos, int) else list(eos)
    config = GenerationConfig(do_sample=False, num_beams=1, max_new_tokens=max_new_tokens,
                              eos_token_id=eos, pad_token_id=tokenizer.pad_token_id,
                              bos_token_id=tokenizer.bos_token_id, use_cache=True)
    # GenerationConfig values equal to global defaults can otherwise inherit
    # Qwen's sampling defaults in HF 4.57. kwargs have highest priority.
    options = dict(logits_to_keep=1, use_model_defaults=False, do_sample=False, num_beams=1,
                   temperature=1.0, top_p=1.0, top_k=50)
    if backend == 'liger':
        options['skip_logits'] = False
    predictions = []
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad(), trainer.accelerator.autocast():
            total_batches = math.ceil(len(prompts) / world_size)
            for batch_number, (index, keep) in enumerate(rank_indices(len(prompts), rank, world_size), 1):
                prompt = prompts[index]
                ids = torch.tensor([prompt['input_ids']], device=trainer.args.device)
                started = time.perf_counter()
                output = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids),
                                        generation_config=config, synced_gpus=world_size > 1, **options)
                continuation = output[0, ids.shape[1]:].tolist()
                # generate may append padding; retain only through the first EOS.
                stop = next((i + 1 for i, token in enumerate(continuation) if token in eos_ids), None)
                if stop is not None:
                    continuation = continuation[:stop]
                truncated = stop is None and len(continuation) >= max_new_tokens
                raw = tokenizer.decode(continuation, skip_special_tokens=False,
                                       clean_up_tokenization_spaces=False)
                if keep:
                    predictions.append(dict(id=prompt['id'], raw_response=raw,
                                            prompt_sha256=hashlib.sha256(prompt.get('prompt', '').encode()).hexdigest(),
                                            decoding=dict(do_sample=False, num_beams=1, max_new_tokens=max_new_tokens,
                                                          enforced_greedy=True),
                                            generated_token_ids=continuation,
                                            generated_tokens=len(continuation), prompt_tokens=ids.shape[1],
                                            truncated=truncated, seconds=time.perf_counter()-started,
                                            **parse_response(raw, truncated, allow_preface=prompt.get('allow_preface', True))))
                if rank == 0 and (batch_number == 1 or batch_number % 5 == 0 or batch_number == total_batches):
                    print(f'GENERATION {batch_number}/{total_batches} batches; '
                          f'last batch {time.perf_counter()-started:.1f}s', flush=True)
    finally:
        model.train(was_training)
    if world_size > 1:
        gathered = [None] * world_size
        torch.distributed.all_gather_object(gathered, predictions)
        predictions = [row for shard in gathered for row in shard]
    order = {p['id']: i for i, p in enumerate(prompts)}
    return sorted(predictions, key=lambda p: order[p['id']])


def select_train_probe(records, limit):
    """Fixed round-robin source coverage, independent of labels/model performance."""
    from collections import defaultdict
    groups = defaultdict(list)
    for row in sorted(records, key=lambda r: r['id']):
        groups[row['source_id']].append(row)
    result = []
    for position in range(max((len(g) for g in groups.values()), default=0)):
        for source in sorted(groups):
            if len(result) >= limit:
                return result
            if position < len(groups[source]):
                result.append(groups[source][position])
    return result


def evaluation_interval(n_records, world_size, accumulation, fraction):
    # DistributedSampler pads to ceil(N/world_size); each rank uses batch one.
    updates_per_epoch = math.ceil(math.ceil(n_records/world_size)/accumulation)
    return max(1, math.ceil(updates_per_epoch * fraction))


def select_validation_pairs(records, pairs, per_source):
    """Fixed, label-independent pairs; retain complete endpoints and every source."""
    from collections import defaultdict
    by_id = {r['id']: r for r in records}
    groups = defaultdict(list)
    for pair in pairs:
        if pair['before'] in by_id and pair['after'] in by_id:
            groups[pair['source_id']].append(pair)
    selected = set()
    for source in sorted({r['source_id'] for r in records}):
        candidates = sorted(groups[source], key=lambda p: hashlib.sha256(
            (p['before'] + '\n' + p['after']).encode()).hexdigest())
        if not candidates:
            raise ValueError(f'No complete validation pair for source {source}')
        for pair in candidates[:per_source]:
            selected.update((pair['before'], pair['after']))
    return [r for r in records if r['id'] in selected]
