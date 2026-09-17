"""Active experiment includes homogeneous binary or homogeneous linear goals."""
ALLOWED_MODES = ('binary', 'linear')


def completion_mode(row):
    container = row['input'] if 'input' in row else row['raw']
    goals = container['game']['goals']
    if not goals:
        raise ValueError('Cannot classify a game without goals')
    flags = [g['binary'] for g in goals]
    if any(type(flag) is not bool for flag in flags):
        raise ValueError('Goal binary flags must be booleans')
    return 'binary' if all(flags) else 'linear' if not any(flags) else 'mixed'


def validate_rows(rows, source):
    for row in rows:
        mode = completion_mode(row)
        if mode not in ALLOWED_MODES:
            raise ValueError(f'Mixed completion rules excluded: {source}/{row["id"]}')
        if row.get('completion_mode', mode) != mode:
            raise ValueError(f'Completion metadata disagrees with game: {source}/{row["id"]}')
