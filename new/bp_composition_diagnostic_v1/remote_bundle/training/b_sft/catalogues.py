"""Admissible independent public preference catalogues for native datasets."""


def validate_catalogues(raw):
    n=raw['game']['n_players'];g=len(raw['game']['goals'])
    types={int(p):rows for p,rows in raw['type_catalogues'].items()}
    if set(types)!=set(range(n)) or len(types)!=len(raw['type_catalogues']):
        raise ValueError('Provide exactly one catalogue for every player')
    if list(raw['own_preferences']) not in types.get(raw['ego'], []):
        raise ValueError('The observer own row must belong to its public catalogue')
    for rows in types.values():
        if not rows or any(len(r)!=g or any(v not in (-1,0,1) for v in r) for r in rows):
            raise ValueError('Nonempty preference rows must match goals and use -1/0/1')
        if len({tuple(r) for r in rows})!=len(rows) or any(1 not in r for r in rows):
            raise ValueError('Every unique candidate profile must retain a positive goal')
    for goal in range(g):
        if all(any(row[goal]==0 for row in rows) for rows in types.values()):
            raise ValueError(f'Independent catalogues permit all-neutral goal {goal}')
