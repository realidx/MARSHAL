"""Named-addition teaching interface; native state and teacher stay local.

New exports use readable prompts and registered game-action tools. The three
legacy output arms are retained for scoring and replay of frozen experiments.
"""
from copy import deepcopy
import json
from jsonschema import validate, ValidationError

from training.b_sft.social_bp_curriculum_eval import score as native_score

PLAYERS = ('Alex', 'Blair', 'Casey', 'Drew')
GOALS = ('Orchard', 'Harbor', 'Library', 'Garden', 'Workshop', 'Market', 'Museum', 'Station', 'School', 'Bridge')
COMMITS = ('Cedar', 'Maple', 'Willow', 'Birch', 'Elm', 'Pine')
# Legacy arms remain readable for frozen experiment replay. New exports use
# action_tools only; text is no longer an active experimental condition.
ARMS = ('separate_tool', 'joint_tool', 'text')
ACTIVE_ARMS = ('action_tools',)
RULES = (
    'Goals specify outcomes, not anyone\'s preferences. Each goal is achieved only when ALL its '
    'listed commitments are binding. Achieving a goal gives each player +1 for want, 0 for neutral, '
    '-1 for avoid; unachieved goals give zero. Add across goals at the end of the game. '
    'A commitment can serve several goals; making that commitment alone need not achieve them. '
    'OFFER lists NEW named commitments for you and your partner. ACCEPT binds all listed additions; '
    'REJECT binds none. Existing commitments remain binding and cannot be removed. '
    'A proposal and its response use one proposal opportunity together. PASS uses that opportunity. '
    'INVESTIGATE uses your current proposal opportunity and your one investigation for this game. '
    'You choose another player and a goal. The environment returns that player\'s TRUE fixed preference '
    'only to you. Everyone sees who queried whom about which goal, but not the answer. '
    'Querying a known or irrelevant preference is legal and still spends the opportunity. '
    'Each player knows their own preferences. The remaining proposal order includes the current '
    'proposal opportunity (and its response, if pending). '
    'Give a brief decision-relevant explanation and one answer. Do not output numerical confidence.'
)
B_RULE = (
    'possible_preferences is the set of values STILL compatible with the available evidence, '
    'not a list of all preference words. A true revealed value leaves only that value. '
    'favored is the uniquely most supported remaining value, even when other values remain possible; '
    'use undetermined if the top support is tied. Undetermined does not mean all values are equally supported. '
    'Keep all three values when all three remain compatible; exclude a value only with a valid reason. '
    'Compare the observed voluntary behavior with what each candidate preference would lead the player to do. '
    'When a correct previous belief is supplied, carry it forward and apply the new evidence. '
    'Your answer must match the conclusion in your explanation.'
)


class Names:
    def __init__(self, inp, variant=0):
        game = inp['game']
        self.players = list(PLAYERS[:game['n_players']])
        self.goals = list(GOALS[:len(game['goals'])])
        # A semantic renaming control, not a reordering of native game actions.
        self.actions = [list(COMMITS[variant:]+COMMITS[:variant])[:n]
                        for n in game['n_actions_per_player']]
        if variant:
            self.players.reverse()
            self.goals.reverse()

    def pref(self, rows):
        result = {}
        for r in rows:
            result.setdefault(self.players[r['player']], {})[self.goals[r['goal']]] = r['preference']
        return result

    def bindings(self, vectors):
        return {self.players[p]: [self.actions[p][i] for i, bit in enumerate(row) if bit]
                for p, row in enumerate(vectors)}

    def action(self, action, actor, before):
        if 'response' in action:
            return dict(response=action['response'])
        kind = action['action']
        if kind == 'PASS':
            return dict(action=kind)
        if kind == 'INVESTIGATE':
            return dict(action=kind, player=self.players[action['player']], goal=self.goals[action['goal']])
        if kind != 'OFFER':
            raise ValueError('Unsupported teaching action')
        partner = action['partner_id']
        result = dict(action=kind, partner=self.players[partner])
        for key, p, vector in [('self_commitments', actor, action['proposer_action']),
                               ('partner_commitments', partner, action['partner_action'])]:
            if len(vector) != len(before[p]) or any(a < b for a, b in zip(vector, before[p])):
                raise ValueError('Cannot silently withdraw or truncate a native commitment')
            result[key] = [self.actions[p][i] for i, bit in enumerate(vector) if bit and not before[p][i]]
        return result


def history(inp, names):
    """Replay display facts only, preserving event ownership and intervention status."""
    setup = inp['imposed_setup']
    events = setup + inp['voluntary_history']
    counts = inp['game']['n_actions_per_player']
    starting = inp.get('initial_commitments', [[0]*n for n in counts])
    if len(starting) != len(counts) or any(len(row) != n or any(bit not in (0, 1) for bit in row) for row, n in zip(starting, counts)):
        raise ValueError('Invalid initial commitments for history rendering')
    vectors = [list(row) for row in starting]
    schedule = inp['game']['round_robin']
    turn = inp.get('initial_turn_index', 0)
    pending = None
    out = []
    boundary = len(events)-len(inp.get('new_history', []))
    for i, action in enumerate(events):
        proposer = schedule[turn]
        actor = pending['partner_id'] if 'response' in action else proposer
        shown = names.action(action, proposer, vectors)
        row = dict(actor=names.players[actor], source='imposed setup' if i < len(setup) else 'voluntary', **shown)
        if 'new_history' in inp:
            row['belief_period'] = 'new evidence' if i >= boundary else 'earlier history'
        out.append(row)
        if 'response' in action:
            if action['response'] == 'ACCEPT':
                vectors[proposer] = pending['proposer_action'][:]
                vectors[pending['partner_id']] = pending['partner_action'][:]
            pending = None
            turn += 1
        elif action['action'] == 'OFFER':
            pending = action
        else:
            turn += 1
    assert vectors == inp['current_state']['commitments']
    return out


def present(task, variant=0):
    inp = task['input']
    names = Names(inp, variant)
    state = inp['current_state']
    player = inp['player']
    visible = dict(
        you=names.players[player],
        commitments_available={names.players[p]: a for p, a in enumerate(names.actions)},
        max_new_commitments_per_player_per_offer=inp['game']['max_changes'],
        goals={names.goals[g['goal_id']]: {('ALL_OF' if g.get('binary',True) else 'LINEAR_FRACTION'):[
            names.players[a['player_id']]+'.'+names.actions[a['player_id']][a['action_id']]
            for a in g['required_actions']]} for g in inp['game']['goals']},
        public_preferences=names.pref(inp['public_preferences']),
        your_preferences={names.goals[int(g.split('_')[1])]: v for g, v in inp['own_preferences'].items()},
        your_private_investigation_answers=names.pref(inp['private_results']),
        binding_commitments=names.bindings(state['commitments']),
        remaining_proposers=[names.players[p] for p in state['round_robin'][state['turn_index']:]],
        investigation_uses_remaining={names.players[p]: n for p, n in enumerate(state['investigation_remaining_by_player'])},
        history=history(inp, names),
        preference_generation=inp['preference_generation'],
        partner_policy=inp['partner_policy'])
    if inp.get('background_prior'):visible['background_prior']=inp['background_prior']
    if inp.get('qualitative_ranges'):visible['qualitative_ranges']=inp['qualitative_ranges']
    if 'favored_margin' in inp:visible['favored_margin']=inp['favored_margin']
    visible['current_decision'] = ('assess the requested belief; do not take a game action' if task['task']=='B'
        else 'respond to the pending offer' if inp['pending_offer'] else 'make your proposal decision now')
    if inp['game'].get('forbidden_actions') is not None:
        visible['forbidden_commitments'] = names.bindings(inp['game']['forbidden_actions'])
    if inp['pending_offer']:
        visible['pending_offer'] = dict(proposer=names.players[state['current_proposer']],
            **names.action(dict(action='OFFER', **inp['pending_offer']), state['current_proposer'], state['commitments']))
    if task['task'] == 'B':
        q = inp['queries'][0]
        visible['belief_question'] = dict(player=names.players[q['player']], goal=names.goals[q['goal']])
        visible['belief_rules'] = B_RULE
        if 'previous_belief' in inp:
            visible['correct_previous_belief'] = inp['previous_belief']
        if 'new_evidence' in inp:
            visible['new_evidence'] = inp['new_evidence']
        visible['instruction'] = 'Infer the requested belief from the available evidence.'
    else:
        visible['legal_actions'] = [names.action(a, player, state['commitments']) for a in inp['legal_actions']]
        b = inp['supplied_belief']
        visible['your_current_belief'] = dict(known_preferences=names.pref(b['known_preferences']),
            unresolved_preferences=[dict(player=names.players[r['player']], goal=names.goals[r['goal']])
                                    for r in b['unresolved_preferences']], description=b['support'])
        if 'joint_distribution' in b:
            visible['your_current_belief']['joint_distribution'] = [dict(
                probability=r['probability'], preferences=names.pref(r['preferences']))
                for r in b['joint_distribution']]
        # Explicit supplied assessments can replace the generator prior for P.
        if 'qualitative' in inp:
            visible['your_current_belief']['description'] = inp['qualitative']['description']
            verbs = {'want':'wants', 'neutral':'is neutral about', 'avoid':'wants to avoid'}
            visible['your_current_belief']['assessments'] = [
                f'The claim "{names.players[r["player"]]} {verbs[r["preference"]]} '
                f'{names.goals[r["goal"]]}" {r["qualifier"]}.' for r in inp['qualitative']['assessments']]
        visible['instruction'] = ('Use your supplied CURRENT belief directly; do not reconstruct it from history. '
            'Prefer your expected final utility, then others total utility on own ties. Choose one legal action.')
    return visible


def answer_schema(task, visible):
    if task['task'] == 'P':
        return dict(type='object', enum=visible['legal_actions'])
    q = visible['belief_question']
    judgment = dict(type='object', additionalProperties=False,
        required=['player', 'goal', 'possible_preferences', 'favored'], properties=dict(
            player=dict(type='string', enum=[q['player']]), goal=dict(type='string', enum=[q['goal']]),
            possible_preferences=dict(type='array', minItems=1, maxItems=3, uniqueItems=True,
                description='Only preferences still compatible with the evidence.',
                items=dict(type='string', enum=['want', 'neutral', 'avoid'])),
            favored=dict(type='string', enum=['want', 'neutral', 'avoid', 'undetermined'])))
    return dict(type='object', additionalProperties=False, required=['judgments'],
        properties=dict(judgments=dict(type='array', minItems=1, maxItems=1, items=judgment)))


def action_call(action):
    """Lossless game action -> registered function name and arguments."""
    key = 'response' if 'response' in action else 'action'
    return action[key], {k:v for k,v in action.items() if k != key}


def action_tools(visible):
    groups = {}
    for action in visible['legal_actions']:
        name, args = action_call(action)
        groups.setdefault(name, []).append(args)
    descriptions = {
        'OFFER': 'Propose NEW commitments for yourself and your partner. Acceptance binds both sets of additions.',
        'PASS': 'Spend the current proposal opportunity without adding commitments.',
        'INVESTIGATE': 'Spend the current proposal opportunity and your investigation use to privately learn the selected player\'s true preference for the selected goal.',
        'ACCEPT': 'Accept the pending offer and bind its additions.',
        'REJECT': 'Reject the pending offer without binding its additions.',
    }
    tools = []
    for name, choices in groups.items():
        properties = {}
        for key in choices[0]:
            if key in ('self_commitments', 'partner_commitments'):
                choices_for_field = sorted({x for c in choices for x in c[key]})
                items = dict(type='string')
                if choices_for_field: items['enum'] = choices_for_field
                properties[key] = dict(type='array', items=items, uniqueItems=True,
                    maxItems=max(len(c[key]) for c in choices),
                    description=('Your own NEW commitments.' if key=='self_commitments' else 'Your partner\'s NEW commitments.'))
            else:
                properties[key] = dict(type='string', enum=sorted({c[key] for c in choices}))
        # enum preserves the exact legal combinations, not their Cartesian product.
        schema = dict(type='object', properties=properties, required=list(properties),
                      additionalProperties=False, enum=choices)
        tools.append(dict(type='function', function=dict(name=name,
            description=descriptions[name], parameters=schema)))
    return tools


def request(task, arm='separate_tool', variant=0):
    if arm not in ARMS + ACTIVE_ARMS:
        raise ValueError('Unknown output arm')
    visible = present(task, variant)
    if arm == 'action_tools':
        from training.b_sft.review_prompt import SYSTEM, render
        registered = (action_tools(visible) if task['task']=='P' else
                      [dict(type='function', function=dict(name='SUBMIT_BELIEFS',
                        description='Submit the requested belief judgment.', parameters=answer_schema(task, visible)))])
        return dict(messages=[dict(role='system', content=SYSTEM),
            dict(role='user', content=render(visible, task['task'], task['skill']))],
            tools=registered, tool_choice='auto', parallel_tool_calls=False, max_tokens=1024)
    answer = answer_schema(task, visible)
    joint = dict(type='object', additionalProperties=False, required=['reasoning', 'answer'],
        properties=dict(reasoning=dict(type='string', minLength=1), answer=answer))
    payload = dict(messages=[dict(role='system', content=RULES),
                             dict(role='user', content=json.dumps(visible, ensure_ascii=False))], max_tokens=1024)
    if arm == 'text':
        payload['messages'][0]['content'] += (' Return one JSON object with keys reasoning (brief text) and answer. '
            'Do not use tools or Markdown fences. The answer schema is: '+json.dumps(answer))
    else:
        name = 'SUBMIT_BELIEFS' if task['task'] == 'B' else 'SUBMIT_ACTION'
        if arm == 'separate_tool':
            payload['messages'][0]['content'] += ' Explain briefly in ordinary text, then call the submission tool exactly once.'
        else:
            payload['messages'][0]['content'] += ' Put the brief explanation and matching answer together inside one submission tool call.'
        payload.update(tools=[dict(type='function', function=dict(name=name,
            description='Submit your evidence-based answer.', parameters=answer if arm == 'separate_tool' else joint))],
            tool_choice='auto', parallel_tool_calls=False)
    return payload


def gold_answer(task, variant=0):
    visible = present(task, variant)
    if task['task'] == 'B':
        return dict(judgments=[dict(**visible['belief_question'], **task['teacher']['gold'])])
    indices = [task['input']['legal_actions'].index(a) for a in task['teacher']['acceptable_actions']]
    return visible['legal_actions'][indices[0]]


def score(task, completion, arm='separate_tool', variant=0):
    if completion.get('status') == 'infrastructure_failure':
        return dict(status='infrastructure_failure', reward=None, correct=None)
    if completion.get('finish_reason') == 'length':
        return dict(status='truncated', reward=-1, correct=False)
    try:
        msg = completion['raw_message']
        if arm == 'action_tools':
            if task['task'] == 'B':
                return score(task, completion, 'separate_tool', variant)
            calls = msg.get('tool_calls') or []
            if len(calls) != 1: raise ValueError('Expected one game-action call')
            call = calls[0]['function']
            specifications = {t['function']['name']:t['function']['parameters']
                              for t in action_tools(present(task, variant))}
            if call['name'] not in specifications: raise ValueError('Unregistered action tool')
            args = json.loads(call['arguments'])
            validate(args, specifications[call['name']])
            key = 'response' if call['name'] in ('ACCEPT', 'REJECT') else 'action'
            action = {key:call['name'], **args}
            # The same strict legal-action and teacher scoring below is reused;
            # legacy submissions are never repaired by this new-arm decoder.
            return score(task, dict(raw_message=dict(tool_calls=[dict(function=dict(
                name='SUBMIT_ACTION', arguments=json.dumps(action)))])), 'separate_tool', variant)
        if arm == 'text':
            if msg.get('tool_calls'):
                raise ValueError('Text arm must not call tools')
            obj = json.loads(msg['content'])
        else:
            calls = msg.get('tool_calls') or []
            if len(calls) != 1 or calls[0]['function']['name'] != ('SUBMIT_BELIEFS' if task['task'] == 'B' else 'SUBMIT_ACTION'):
                raise ValueError('Wrong submission tool')
            obj = json.loads(calls[0]['function']['arguments'])
        if arm != 'separate_tool':
            if set(obj) != {'reasoning', 'answer'} or not isinstance(obj['reasoning'], str) or not obj['reasoning'].strip():
                raise ValueError('Expected one explanation and answer')
            obj = obj['answer']
        visible = present(task, variant)
        validate(obj, answer_schema(task, visible))
        if task['task'] == 'B':
            q = task['input']['queries'][0]
            judgment = dict(obj['judgments'][0], **q)
            native = dict(judgments=[judgment])
        else:
            native = task['input']['legal_actions'][visible['legal_actions'].index(obj)]
        if task['teacher'].get('qualitative_certificate', {}).get('status') == 'ambiguous_information':
            return dict(status='ambiguous_information', reward=None, correct=None)
        return native_score(task, dict(raw_message=dict(tool_calls=[dict(function=dict(
            name='SUBMIT_BELIEFS' if task['task']=='B' else 'SUBMIT_ACTION', arguments=json.dumps(native)))])))
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        # jsonschema failures and strict decoding failures are both protocol errors.
        return dict(status='format_failure', reward=-1, correct=False, reason=type(exc).__name__)
