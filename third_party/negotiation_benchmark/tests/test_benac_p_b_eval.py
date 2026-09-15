from copy import deepcopy

import pytest

from benac_p.b_eval import evaluate
from benac_p.b_data_validate import GROUNDED_SYSTEM, grounded_chat, revalidate_game
from benac_p.b_data_audit import audit_game
from benac_p.mcts_oracle import Budget


def test_protocol_failures_are_not_semantic_false_exclusions():
    gold = [dict(id=str(i), source_id='source', answer={'possible_preferences': ['want', 'neutral']}) for i in range(4)]
    predictions = [dict(id='0', answer={'possible_preferences': ['want']}),
                   dict(id='1', answer={'possible_preferences': []}),
                   dict(id='2', status='truncated', answer={'possible_preferences': ['want', 'neutral']})]
    score = evaluate(gold, predictions)['overall']
    assert score['valid'] == 1 and score['protocol_failures'] == 2 and score['missing'] == 1
    assert score['mean_false_exclusions_valid'] == 1
    assert score['mean_unsupported_possibilities_valid'] == 0


def test_set_order_and_update_pairs_scored_without_hidden_truth_guessing():
    gold = [dict(id='a', source_id='source', answer={'possible_preferences': ['want', 'neutral', 'avoid']}),
            dict(id='b', source_id='source', answer={'possible_preferences': ['want', 'neutral']})]
    predictions = [dict(id='a', answer={'possible_preferences': ['avoid', 'want', 'neutral']}),
                   dict(id='b', answer={'possible_preferences': ['neutral', 'want']})]
    result = evaluate(gold, predictions, [dict(before='a', after='b')])
    assert result['overall']['exact_rate_all'] == 1
    assert result['update_pairs']['both_exact'] == 1
    with pytest.raises(AssertionError):
        evaluate(gold, predictions + [predictions[0]])


def test_public_history_validator_detects_wrong_gold_and_prompt_grounding_is_explicit():
    budget = Budget(simulations=16)
    game, raw, _, _ = audit_game(63001, 'n4_k2_g12_r4', budget, backgrounds=3, max_branches=2, per_size=2)
    manifest = dict(configuration={'backgrounds': 3, 'focal_goals': 2}, fixed_policy_budget=vars(budget))
    # Nonempty-history counterfactual questions must also independently replay.
    sample = next(r for r in raw if any(o['kind'] == 'counterfactual' for o in r['origins'])
                  and len(r['answer']['possible_preferences']) < 3)
    verified = revalidate_game(game, [sample], manifest)
    assert verified['verified_questions'] == 1
    corrupted = deepcopy(sample)
    corrupted['answer']['possible_preferences'] = ['want', 'neutral', 'avoid']
    with pytest.raises(AssertionError, match='B answer failed'):
        revalidate_game(game, [corrupted], manifest)
    chat = grounded_chat(sample)
    assert '1 = want, 0 = neutral, -1 = avoid' in chat['messages'][0]['content']
    assert 'null' in GROUNDED_SYSTEM and 'NOT a neutral' in GROUNDED_SYSTEM
