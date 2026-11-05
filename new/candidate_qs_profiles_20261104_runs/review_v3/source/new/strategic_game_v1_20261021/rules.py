"""User-approved native game variant; not yet connected to production prompts."""
from itertools import product

from new.game_design_feasibility_20261021.design import BudgetRules

VERSION = 'native-private-unknown-query-offer-quota-v1'


class StrategicRules(BudgetRules):
    """Legality uses public fixed cells and direct query history, never a world.

    Preferences must have independent Cartesian support. We do not remove a
    target because it is inferred likely/certain from strategic behavior, or
    because a solver assigns zero information value to it.
    """
    def __init__(self, raw):
        game=raw['game']
        self.raw=raw
        for rows in raw['type_catalogues'].values():
            supports=[sorted({row[g] for row in rows}) for g in range(len(game['goals']))]
            if {tuple(row) for row in rows} != set(product(*supports)):
                raise ValueError('This version requires independent preference support')
            if any(len(values) not in (1,3) for values in supports):
                raise ValueError('Cells must be public fixed or support all three preferences')
        super().__init__(raw,query_limit=game['investigation_budget'],
            offer_limit=game['offer_budget'],query_targets='hidden-unobserved')

    def public_game(self):
        game=super().public_game()
        game['variant']=VERSION
        game['investigate'].update(
            public_preferences_eligible=False,
            already_directly_investigated_eligible=False,
            inference_or_utility_used_for_legality=False,
            hidden_world_used_for_legality=False)
        return game
