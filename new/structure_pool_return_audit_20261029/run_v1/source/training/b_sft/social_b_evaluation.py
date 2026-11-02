"""B evaluation adapters/diagnostics only. No client calls or optimizer rewards."""
from collections import Counter
from copy import deepcopy
import json

from jsonschema import validate, ValidationError
from training.b_sft.social_lm_eval import tool_for
from training.b_sft.favored_belief import score_belief

from training.b_sft.social_lm_eval import SYSTEM as LEGACY_SYSTEM, STAGE_INSTRUCTIONS
from training.b_sft.social_presentation import present
from training.b_sft.social_b_oracle import VERSION as ORACLE_VERSION

PROMPT_VERSION = 'social-b-readable-v3-weighted'
# Reuse the successful game's presentation/rules, replacing only the obsolete
# evidence convention (old teacher treated learner actions as interventions).
_OLD_EVIDENCE = ('Setup and learner events are interventions independent of partner types. '
                 'Only subsequent partner events can exclude types.')
assert _OLD_EVIDENCE in LEGACY_SYSTEM
_COMMON_SYSTEM = LEGACY_SYSTEM.replace(_OLD_EVIDENCE,
    'Only setup events are interventions independent of preferences. Every post-setup action is autonomous, '
    'including the observer actions, and can constrain compatible joint profiles under partner_policy.') + (
    '\nYour task is B only; do not choose an action or report utility numbers. '
    'Earlier answers from you may be wrong; reassess them using the actual public history. '
    'Later user messages give newly observed events and the current state; retain earlier events and the initial game description. '
    'For each query, possible_preferences is the complete remaining compatible set. ')
SYSTEM = _COMMON_SYSTEM + (
    'Favored is the uniquely most supported marginal preference under the declared partner_policy; '
    'other preferences may still remain possible. Use undetermined when the highest supports tie. '
    'Start from the stated initial joint reference and retain cumulative evidence from autonomous choices. '
    'Each actor knows its own profile, but the observer own_preferences is not automatically public: '
    'other players only know what their public catalogues and observed history establish. '
    'Do not report probabilities or counts. '
    'Explain briefly, then make exactly one native SUBMIT_BELIEFS call.')
_SUPPORT_ONLY_SYSTEM = _COMMON_SYSTEM + (
    'Set favored to its sole member only when that set has one member; otherwise use undetermined. '
    'Explain briefly, then make exactly one native SUBMIT_BELIEFS call.')


def require_current_tasks(tasks):
    """Old frozen gold may be audited, but never silently used for new training."""
    if any(t['input'].get('partner_model', {}).get('version') != ORACLE_VERSION for t in tasks):
        raise ValueError('Weighted B preparation requires newly generated v4 tasks; do not relabel or reuse old trajectories')


def payload(context):
    return present(context, 'B', STAGE_INSTRUCTIONS['B'],
                   policy_description=context['partner_model'], autonomous_observer=True)


def delta(context, previous_length):
    shown = payload(context)
    if previous_length < 0:
        return shown
    return dict(player=shown['player'], decision=shown['decision'],
                public_state=shown['public_state'], pending_offer=shown['pending_offer'],
                new_history=shown['history'][previous_length:],
                history_event_count=len(shown['history']), queries=shown['queries'])


def request(task, *, mode='independent', prior_turns=(), remaining_tokens=1024, retry_feedback=None):
    """Retain actual previous assistant messages, never previous gold labels.

    prior_turns contains {task: earlier task record, message: raw assistant API
    message}. The caller records/scores each retry separately. This function
    builds a native chat request; it does not send it or add a retry policy.
    """
    if mode not in ('independent','sequential'): raise ValueError('Unknown evaluation mode')
    if mode=='independent' and prior_turns: raise ValueError('Independent checkpoints have no previous model answers')
    if type(remaining_tokens) is not int or not 0<remaining_tokens<=1024:
        raise ValueError('Remaining generated-token budget must be 1..1024')
    version = task['input'].get('partner_model', {}).get('version')
    system = _SUPPORT_ONLY_SYSTEM if version in ('social-b-bounded-oracle-v2', 'social-b-bounded-oracle-v3') else SYSTEM
    messages=[dict(role='system',content=system)]
    previous_length=-1
    for turn in prior_turns:
        previous=turn['task']; history=previous['input']['history']; current=task['input']['history']
        if (previous['family']!=task['family'] or previous['input']['player']!=task['input']['player'] or
            previous['input']['queries']!=task['input']['queries'] or
            any(previous['input'].get(k)!=task['input'].get(k) for k in
                ('game','own_preferences','public_type_catalogues','public_setup','partner_model','favored_rule')) or
            len(history)<=previous_length or len(history)>=len(current) or current[:len(history)]!=history):
            raise ValueError('Previous answers must follow the same actual history in chronological order')
        messages.append(dict(role='user',content=json.dumps(delta(previous['input'],previous_length),ensure_ascii=False)))
        previous_length=len(history)
        message=deepcopy(turn['message'])
        if message.get('role')!='assistant': raise ValueError('Expected actual assistant response')
        messages.append(message)
        for call in message.get('tool_calls') or []:
            messages.append(dict(role='tool',tool_call_id=call['id'],content='Recorded.'))
    context=delta(task['input'],previous_length)
    if retry_feedback is not None: context['retry_feedback']=retry_feedback
    messages.append(dict(role='user',content=json.dumps(context,ensure_ascii=False)))
    return dict(messages=messages,tools=[tool_for('B',context)],tool_choice='auto',
                parallel_tool_calls=False,max_tokens=remaining_tokens)


def score_attempt(task, completion):
    """Only parse native tool arguments. Natural-language JSON is never accepted."""
    base=dict(checkpoint=task['id'],query_count=len(task['input']['queries']),gold_unchanged=True)
    if completion.get('status') in ('request_error','infrastructure_failure'):
        return dict(base,status='infrastructure_failure',exact=None,judgments=[])
    if completion.get('finish_reason')=='length':
        return dict(base,status='truncated',exact=False,judgments=[])
    try:
        # Accept the existing social_lm_eval call record without a new log format.
        message=completion.get('raw_message',completion.get('message'))
        if not isinstance(message,dict): raise ValueError('Missing assistant message')
        calls=message.get('tool_calls') or []
        if len(calls)!=1 or calls[0]['function']['name']!='SUBMIT_BELIEFS':
            raise ValueError('Expected one native SUBMIT_BELIEFS call')
        args=json.loads(calls[0]['function']['arguments'])
        validate(args,tool_for('B',task['input'])['function']['parameters'])
        answers={(r['player'],r['goal']):r for r in args['judgments']}
        expected={(q['player'],q['goal']) for q in task['input']['queries']}
        if len(answers)!=len(args['judgments']) or set(answers)!=expected:
            raise ValueError('Each query must occur exactly once')
        rows=[]
        for gold in task['gold']['judgments']:
            answer=answers[gold['player'],gold['goal']]
            pred={k:answer[k] for k in ('possible_preferences','favored')}
            target={k:gold[k] for k in ('possible_preferences','favored')}
            if not score_belief(pred,target)['format_valid']: raise ValueError('Invalid belief structure')
            ps,gs=set(pred['possible_preferences']),set(target['possible_preferences'])
            rows.append(dict(player=gold['player'],goal=gold['goal'],prediction=pred,
                set_exact=ps==gs,favored_exact=pred['favored']==target['favored'],
                false_exclusions=len(gs-ps),extra_possibilities=len(ps-gs),
                gold_possible_count=len(gs),gold_excluded_count=3-len(gs)))
        return dict(base,status='ok',exact=all(r['set_exact'] and r['favored_exact'] for r in rows),judgments=rows)
    except (KeyError,TypeError,ValueError,ValidationError) as exc:
        return dict(base,status='format_failure',exact=False,judgments=[],detail=str(exc))


def score_transition(before_task, after_task, before_score, after_score, query):
    key=(query['player'],query['goal'])
    find=lambda rows: next(r for r in rows if (r['player'],r['goal'])==key)
    a=find(before_task['gold']['judgments']);b=find(after_task['gold']['judgments'])
    expected_set_change=set(a['possible_preferences'])!=set(b['possible_preferences'])
    expected_favored_change=a['favored']!=b['favored']
    expected_change=expected_set_change or expected_favored_change
    if before_score['status']!='ok' or after_score['status']!='ok':
        return dict(comparable=False,expected_change=expected_change)
    x=find(before_score['judgments']);y=find(after_score['judgments'])
    changed=(set(x['prediction']['possible_preferences'])!=set(y['prediction']['possible_preferences']) or
             x['prediction']['favored']!=y['prediction']['favored'])
    old_ok=x['set_exact'] and x['favored_exact'];new_ok=y['set_exact'] and y['favored_exact']
    return dict(comparable=True,expected_change=expected_change,
                expected_set_change=expected_set_change,expected_favored_change=expected_favored_change,
                unnecessary_update=not expected_change and changed,
                missed_update=expected_change and not changed,
                previous_error=not old_ok,error_recovered=not old_ok and new_ok,
                error_persisted=not old_ok and not new_ok)


def summarize(scores):
    """All supplied attempts remain visible; never erase failures after retry.

    Call separately for first attempts and selected final attempts; do not mix
    independent and sequential modes or count retries as independent examples.
    """
    usable=[s for s in scores if s['exact'] is not None]
    rows=[r for s in usable for r in s['judgments']]
    q=sum(s['query_count'] for s in usable)
    ratio=lambda a,b: a/b if b else None
    return dict(attempts=len(scores),statuses=dict(Counter(s['status'] for s in scores)),
        evaluable_checkpoints=len(usable),
        checkpoint_exact_rate=ratio(sum(s['exact'] for s in usable),len(usable)),
        query_set_exact_rate=ratio(sum(r['set_exact'] for r in rows),q),
        false_exclusions=sum(r['false_exclusions'] for r in rows),
        extra_possibilities=sum(r['extra_possibilities'] for r in rows),
        conditional_false_exclusion_rate=ratio(sum(r['false_exclusions'] for r in rows),sum(r['gold_possible_count'] for r in rows)),
        conditional_extra_possibility_rate=ratio(sum(r['extra_possibilities'] for r in rows),sum(r['gold_excluded_count'] for r in rows)),
        valid_queries_for_error_rates=len(rows),scheduled_evaluable_queries=q)


SPEC = dict(modes=['independent','sequential'],baselines=[],
    generated_tokens_per_checkpoint_path=1024,max_retries_per_checkpoint=1,
    attempt_accounting='Keep every attempt; report first-attempt and final-attempt results separately. Truncation, format and infrastructure failures are distinct.',
    sequential='Previous actual model answers remain in context, without gold feedback. Every checkpoint is scored against actual-history gold.',
    metrics=['set exactness','false exclusions','extra possibilities','unnecessary update','missed update','error recovery and persistence'],
    grouping='Report by topology family, formation/maintain/update and proposal/response phase; include counts and unavailable comparisons.',
    credit='Per-checkpoint diagnostics only; no cross-time advantage, extra repetition penalty or optimizer reward defined.')
