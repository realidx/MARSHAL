"""Readable public facts; no posterior, action values or training metadata."""
from copy import deepcopy

LABELS = {1: 'want', 0: 'neutral', -1: 'avoid'}


def commitment_ids(vector):
    return [f'action_{a}' for a, bit in enumerate(vector) if bit == 1]


def readable_action(action, proposer):
    """Lossless commitment-ID view shared by observations and submissions."""
    if 'response' in action or action.get('action') == 'PASS':
        return deepcopy(action)
    result = dict(proposer_id=proposer, partner_id=action['partner_id'])
    if 'offers' in action:
        result.update(action='MENU', offers=[readable_action(a, proposer) for a in action['offers']])
    else:
        result.update(action='OFFER',
            proposer_committed_action_ids=commitment_ids(action['proposer_action']),
            responder_committed_action_ids=commitment_ids(action['partner_action']))
    return result


def partner_policy(context):
    """Preserve the public policy's horizon, information and selection convention."""
    from training.b_sft.shared_teacher import specification
    original = context['partner_model']; turns = original['window_proposal_turns']
    if original != specification(turns):
        raise ValueError('Unrecognized partner policy; update its presentation before use')
    return dict(
        information='Each player in the shared plan uses its own complete preference profile and public history, without seeing other players\' private profiles.',
        prior='Initially give equal weight to each distinct joint combination of catalogue profiles. Keep combinations consistent with observed partner choices. Each player additionally conditions on its own profile.',
        planning_window=f'Plan for {turns} completed proposer turns, or until the game ends if earlier. Compare goal utilities at that window end. This is the partner planning horizon, not full-game foresight.',
        choice='First maximize expected own window-end utility. Among equal own utilities, maximize the expected sum of other players\' window-end utilities using the acting player\'s information. If both are equal, use native legal-action order.',
        shared_plan='Compute one deterministic plan specifying a choice at every possible decision history for every acting-player profile. All players in this plan use the same plan, conditioned on their own information.',
        plan_selection='Initially assign the first native legal action at every decision. Update players in increasing player ID order, replacing each player\'s plan with its best response to the others. Use a plan only when the entire plan is stable and no player with any private profile can improve by changing its complete plan within the window. This convention selects a plan; it does not assert that only one stable plan exists.',
        hypothetical_histories='At hypothetical histories unreachable under the plan, use the window-start prior conditioned on the acting player\'s own profile. An actual partner history with zero likelihood has no compatible interpretation under this mechanism.',
        execution='Keep the plan fixed throughout its window, then compute a new one. After each learner action, restart the common window from the resulting public state and surviving profile combinations.',
        evidence='Setup events are imposed independently of private profiles. Learner actions also do not exclude partner profiles. Filter profiles only by observed partner choices under the fixed plan.')


def present(context, stage, instruction, *, policy_description=None, autonomous_observer=False):
    state = context['public_state']; proposer = state['current_proposer']
    pending = context['pending_offer']; remaining = state['round_robin'][state['turn_index']:]
    decision = dict(acting_player=context['player'], phase='response' if pending else 'proposal',
        proposer=proposer, responder=pending['partner_id'] if pending else None,
        proposers_after_current=remaining[1:], current_proposer_turn_is_last=len(remaining) == 1,
        pending_offer_type=('MENU' if 'offers' in pending else 'OFFER') if pending else None,
        pending_offer_status='awaiting_response_not_binding' if pending else None)
    if stage == 'B':
        decision['requested_decision'] = 'Assess the listed partner-preference queries. The game is paused for this assessment.'
    elif pending:
        decision['requested_decision'] = f'Player {context["player"]} must now respond to the pending offer from Player {proposer}.'
    else:
        decision['requested_decision'] = f'Player {proposer} must now choose a proposal or PASS from legal_actions.'
    catalogues = {str(p): [{f'goal_{g}': LABELS[v] for g, v in enumerate(row)} for row in rows]
                  for p, rows in context['public_type_catalogues'].items()}
    game = deepcopy(context['game'])
    game.pop('seed', None)
    current = dict(committed_action_ids={str(p): commitment_ids(row)
                   for p, row in enumerate(state['commitments'])})
    events = []; turn = 0; offered_to = None; offered_kind = None
    setup_length = len(context['public_setup']['intervention_prefix'])
    for i, action in enumerate(context['history']):
        current_proposer = state['round_robin'][turn]
        actor = offered_to if 'response' in action else current_proposer
        kind = 'setup' if i < setup_length else 'autonomous' if autonomous_observer else 'learner' if actor == context['player'] else 'partner'
        if 'response' in action:
            verb = {'ACCEPT': 'accepted the offer',
                    'REJECT': 'rejected the offer' if offered_kind == 'OFFER' else 'rejected both menu bundles',
                    'CHOOSE_1': 'selected the first menu bundle', 'CHOOSE_2': 'selected the second menu bundle'}[action['response']]
            event = f'Player {actor} {verb} from Player {current_proposer}.'
        elif action.get('action') == 'PASS':
            event = f'Player {actor} passed their proposer turn.'
        else:
            event = f'Player {actor} proposed {"a menu" if "offers" in action else "an offer"} to Player {action["partner_id"]}.'
        events.append(dict(actor=actor, kind=kind, event=event, action=readable_action(action, current_proposer)))
        if 'response' in action or action.get('action') == 'PASS':
            turn += 1; offered_to = None; offered_kind = None
        else:
            offered_to = action['partner_id']; offered_kind = 'MENU' if 'offers' in action else 'OFFER'
    payload = dict(player=context['player'], task=instruction, decision=decision,
        game=game, own_preferences=dict(player=context['player'],
            preferences_by_goal={f'goal_{g}': LABELS[v] for g,v in enumerate(context['own_preferences'])}),
        public_type_catalogues=catalogues, partner_policy=(partner_policy(context) if policy_description is None else deepcopy(policy_description)),
        public_state=current, pending_offer=readable_action(pending, proposer) if pending else None,
        history=events)
    if stage == 'B':
        rule = deepcopy(context['favored_rule'])
        if isinstance(rule, dict):
            rule['rule'] = rule['rule'].removesuffix(' Do not output counts or probabilities.')
        payload.update(queries=deepcopy(context['queries']), favored_rule=rule)
    elif 'model_beliefs' in context:
        payload['model_beliefs'] = deepcopy(context['model_beliefs'])
    if 'legal_actions' in context:
        payload['legal_actions'] = [readable_action(a, proposer) for a in context['legal_actions']]
    return payload
