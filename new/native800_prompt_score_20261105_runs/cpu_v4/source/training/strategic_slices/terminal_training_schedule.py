"""Token-based monitoring independent of the optimizer batch size."""

DEFAULT_NODE_GROUPS_PER_UPDATE = 20
DEFAULT_EVAL_TOKENS = 500_000
DEFAULT_SAVE_TOKENS = 1_000_000


def due(options, state, kind, step, consumed):
    """Cross an absolute token boundary once; update overrides are for smoke.

    A complete collection can cross several boundaries: evaluate/save once at
    its actual resulting actor, never invent intermediate checkpoints. Saved
    progress travels with optimizer/sampler state across resume.
    """
    every = options.get(f'{kind}_every')
    if every is not None:
        return (step + 1) % every == 0
    interval = options[f'{kind}_every_tokens']
    key = 'terminal_last_validation_tokens' if kind == 'eval' else 'terminal_last_checkpoint_tokens'
    return consumed // interval > state.kv.get(key, 0) // interval
