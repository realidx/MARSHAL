"""Auditable native tool-call LM diagnostics for versioned online social packs.

Fixed-point B/P checks and optional real LM continuation are separate outputs.
No optimizer or oracle repair. One same-state retry; no missing-call PASS fallback.
"""
from collections import Counter
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from queue import Empty

from training.b_sft.online_social import OnlineSocial, VERSION
from training.b_sft.social_cases import p_input
from training.b_sft.social_holdout_expand import check_pack, read_rows
from training.b_sft.social_task import TASK_VERSION
from training.b_sft.social_presentation import present

EVAL_VERSION = 'social-lm-audit-v8'
PROMPT_VERSION = 'social-english-action-ids-v6'
SCORING_CONTRACT = dict(
    version='social-attempt-reward-v1', unit='one B or P generation attempt',
    task='B final-judgment score or P reference regret; available only for valid submissions with an available teacher.',
    format='-1 for format failure, 0 for a valid submission; masked for truncation and infrastructure failure.',
    truncation='-1 when finish_reason is length, 0 for other model responses; masked for infrastructure failure. No per-token or repetition penalty.',
    reward='Sum available task, format and truncation scores with coefficient 1 each. Mask the reward for infrastructure failure or a valid submission without a task teacher.',
    retry='Score each attempt separately. A successful retry never erases the failed attempt or supplies its task label. Never add a failed-attempt cost to the successful retry.',
    credit='The attempt reward supervises the generated reasoning and submission tokens of that attempt; no separate prose correctness score. This evaluator records signals only, not PPO advantages or optimizer updates.')

SYSTEM = '''Use only the supplied visible information. The input identifies the player and the current task.
State, history, offers and legal actions name committed actions explicitly, such as "action_0". An empty list means no commitments; multiple action IDs may be listed together. Goal preferences describe wanting or avoiding a whole goal. own_preferences.player identifies whose known preferences are in own_preferences.preferences_by_goal. These preferences belong only to that player. Each public_type_catalogues key identifies the player who owns every profile listed under that key. In B queries, player identifies the partner whose preference for the specified goal you must assess. A goal's required actions describe its satisfaction condition, not anyone's preference.
A goal is satisfied only when every action required by that goal has been committed to. Each player's terminal utility is the sum over all goals: a satisfied goal contributes that player's preference (+1 want, 0 neutral, -1 avoid); an unsatisfied goal contributes 0, including an unsatisfied wanted or avoided goal. Every player has a preference for every goal, whether or not that player has a required action in it. Goal requirements do not tell you who wants the goal.
Offers specify the complete commitments each party would have after acceptance. A pending offer is awaiting a response and has not changed public_state. Accepting makes these commitments binding and irreversible; rejecting leaves commitments unchanged. An OFFER contains one bundle, accepted with ACCEPT or declined with REJECT. A MENU contains two mutually exclusive binding offers: the partner may choose either offered bundle or reject both; only the chosen bundle binds. PASS or a resolved offer consumes one scheduled proposer turn.
For a MENU, CHOOSE_1 selects the first offered bundle and CHOOSE_2 selects the second. Use the response objects listed in legal_actions.
The proposer and responder are identified in decision. In offer objects, proposer_committed_action_ids belongs to proposer_id and responder_committed_action_ids belongs to partner_id. The readable state and offers list committed action IDs explicitly; any action not listed remains uncommitted. decision.proposers_after_current lists only turns after the current proposer turn. Resolving an offer on the final proposer turn ends the game whether it is accepted, rejected, or one MENU bundle is chosen. The proposer schedule does not restrict which partners can receive an offer; legal_actions lists the available choices.
Partner preferences persist. The catalogues are public to all players; each row is one complete possible preference profile. A singleton catalogue makes that player's profile publicly known. Setup and learner events are interventions independent of partner types. Only subsequent partner events can exclude types. The partner_policy explains how partner choices depend on preferences and public history.
Explain the key grounds for your answer in ordinary assistant text, then make exactly one provided tool call in the same response. Keep the explanation concise enough to complete the tool arguments within the output budget.'''

STAGE_INSTRUCTIONS = {
    'B': 'Your current task is B: infer partner preferences from the visible evidence. You are not choosing a game action in this stage. Answer every query in queries exactly once. '
         'First, briefly explain your judgment in natural language: how evidence from the public history supports retaining or excluding the relevant preferences, and what uncertainty remains. '
         'The answer is the full set of preferences still compatible with the evidence, rather than a required guess of one hidden true preference. Use the declared partner_policy and favored_rule. '
         'After the explanation, call SUBMIT_BELIEFS once in the same response. Its arguments must be a JSON object with exactly one key, "judgments", containing the list of query answers. '
         'Each judgment contains player, goal, possible_preferences, and favored. Retain every compatible preference in possible_preferences; favored follows favored_rule and can be undetermined even when one preference has been excluded.',
    'P': 'Your current task is P: choose a legal action to maximize your own expected terminal utility, accounting for the combined effects on all your goals. '
         'First, explain the evidence and analysis supporting your choice, including any partner responses or future opportunities it depends on and any remaining uncertainty. '
         'model_beliefs contains the preceding B stage\'s estimates of partner preferences, including its uncertainty; these estimates may be wrong. Use them together with the visible facts and partner_policy to assess responses and future opportunities. When the response ends the game, compare terminal goal utilities directly. '
         'Unavailable model_beliefs means no valid B submission was obtained; continue choosing an action using the visible facts and public catalogues. '
         'Your task now is choosing an action. SUBMIT_ACTION is the only available tool. '
         'After the explanation, call SUBMIT_ACTION once in the same response, submitting an exact action object from legal_actions directly as the tool arguments, with all its fields and no additional fields.',
}


def system_for(stage):
    role = ('You are assessing partner preferences for the stated player. Your task is belief inference, not action selection.'
            if stage == 'B' else 'You are choosing an action for the stated player. Your objective is to maximize that player\'s expected terminal utility.')
    return role + '\n\n' + SYSTEM


def model_payload(stage, context):
    """Apply presentation instructions at request time, preserving frozen tasks."""
    return present(context,stage,STAGE_INSTRUCTIONS[stage])


def action_schema(actions):
    """Compact displayed-action schema; the parser additionally checks exact legality.

    Group by fields instead of enumerating every commitment combination twice
    (once in legal_actions and again in the schema).
    """
    def schema(values):
        first=values[0]
        if isinstance(first,dict):
            keys=list(dict.fromkeys(k for v in values for k in v))
            return dict(type='object',additionalProperties=False,
                        required=[k for k in keys if all(k in v for v in values)],
                        properties={k:schema([v[k] for v in values if k in v]) for k in keys})
        if isinstance(first,list):
            items=[x for v in values for x in v]
            return dict(type='array',minItems=min(map(len,values)),maxItems=max(map(len,values)),
                        items=schema(items) if items else {})
        return dict(type='integer' if type(first) is int else 'string',enum=sorted(set(values)))
    groups={}
    for action in actions:groups.setdefault(tuple(sorted(action)),[]).append(action)
    result=schema(actions)
    if len(groups)>1:result['oneOf']=[schema(values) for values in groups.values()]
    return result


def tool_for(stage, context):
    if stage=='B':
        label=dict(type='string',enum=['want','neutral','avoid'])
        item=dict(type='object',additionalProperties=False,required=['player','goal','possible_preferences','favored'],
            properties=dict(player=dict(type='integer',minimum=0),goal=dict(type='integer',minimum=0),
                possible_preferences=dict(type='array',minItems=1,maxItems=3,uniqueItems=True,items=label),
                favored=dict(type='string',enum=['want','neutral','avoid','undetermined'])))
        queries=context['queries']
        variants=[]
        for query in queries:
            variant=deepcopy(item)
            variant['properties']['player']=dict(type='integer',enum=[query['player']])
            variant['properties']['goal']=dict(type='integer',enum=[query['goal']])
            variants.append(variant)
        name='SUBMIT_BELIEFS'; props=dict(judgments=dict(type='array',minItems=len(queries),maxItems=len(queries),
            description='One judgment per listed query, each exactly once. Publicly known preferences are not output targets.',
            items=dict(oneOf=variants) if variants else item)); required=['judgments']
    else:
        return dict(type='function',function=dict(name='SUBMIT_ACTION',
            description='Submit the selected action object from legal_actions after explaining your choice.',
            parameters=action_schema(context['legal_actions'])))
    return dict(type='function',function=dict(name=name,
        description='Submit the final answer after giving a brief explanation in ordinary assistant text in this response.',
        parameters=dict(type='object',additionalProperties=False,properties=props,required=required)))


def call_model(client, stage, context, max_tokens, *, retry_feedback=None):
    native_actions=deepcopy(context['legal_actions'])
    context=model_payload(stage,context)
    if retry_feedback is not None:
        context['retry_feedback']=retry_feedback
    tool=tool_for(stage,context)
    messages=[dict(role='system',content=system_for(stage)),dict(role='user',content=json.dumps(context,ensure_ascii=False))]
    record=dict(stage=stage,prompt_version=PROMPT_VERSION,input=deepcopy(context),
        reasoning_text='',reasoning_chars=0,reasoning_words=0,explanation_status='unavailable',
        request=dict(messages=messages,tools=[tool],tool_choice='auto',
        parallel_tool_calls=False,max_tokens=max_tokens))
    start=time.monotonic()
    try:
        c=client.complete_with_tools(messages,tools=[tool],tool_choice='auto',parallel_tool_calls=False,max_tokens=max_tokens)
        calls=[dict(name=t.name,arguments=t.arguments,raw_arguments=t.raw_arguments) for t in c.tool_calls]
        reasoning=c.content.split('<tool_call',1)[0].strip()
        record.update(raw_message=dict(c.raw_message),raw_text=c.content,tool_calls=calls,usage=dict(c.usage),finish_reason=c.finish_reason,
            reasoning_text=reasoning,reasoning_chars=len(reasoning),reasoning_words=len(reasoning.split()),
            explanation_status='present' if reasoning else 'missing')
        if c.finish_reason=='length': raise ValueError('truncated')
        if len(calls)!=1: raise ValueError('expected_one_tool_call')
        if calls[0]['name']!=tool['function']['name']: raise ValueError('wrong_tool')
        args=calls[0]['arguments']
        if stage=='B':
            if not isinstance(args,dict) or set(args)!={'judgments'}:raise ValueError('malformed_arguments')
            # Semantic/schema validity is assessed by score_b, not repaired here.
            answer=args['judgments']
        else:
            if not isinstance(args,dict):raise ValueError('malformed_arguments')
            # Strict JSON equality also rejects booleans masquerading as integer commitments.
            canonical=lambda a:json.dumps(a,sort_keys=True,allow_nan=False)
            if canonical(args) not in {canonical(a) for a in context['legal_actions']}:
                raise ValueError('illegal_action')
            # Accept only an exact displayed legal object, then execute its native counterpart.
            # The model never supplies an action index or performs a bit-vector conversion.
            matches=[native for shown,native in zip(context['legal_actions'],native_actions)
                     if canonical(shown)==canonical(args)]
            if len(matches)!=1:raise ValueError('ambiguous_action_mapping')
            record['submitted_action']=deepcopy(args)
            answer=deepcopy(matches[0])
        record.update(status='ok',answer=answer)
    except ValueError as exc:
        if 'raw_message' not in record:
            record.update(status='request_error',error_type=type(exc).__name__,answer=None)
        else:
            record.update(status=str(exc),answer=None)
    except Exception as exc:
        # Client error strings can contain endpoint details; retain type, not credentials.
        record.update(status='request_error',error_type=type(exc).__name__,answer=None)
    record['seconds']=time.monotonic()-start
    return record


def call_stage(env, client, stage, context, max_tokens, on_call=None):
    """At most two attempts, with public protocol feedback and unchanged state.

    Failure categories are mutually exclusive. Hitting the cap is not evidence
    of a loop or a separately established format error. No correctness retry.
    """
    attempts=[];feedback=None
    for index in range(2):
        record=call_model(client,stage,context,max_tokens,retry_feedback=feedback)
        status=record['status']
        format_valid=(env.score_b(record['answer'])['format_valid']
                      if status=='ok' and stage=='B' else status=='ok')
        failure=('infrastructure' if status=='request_error' else
                 'truncation' if status=='truncated' else
                 'format' if not format_valid else None)
        record.update(attempt_index=index, failure_category=failure,
            format_valid=format_valid if failure not in ('infrastructure','truncation') else None,
            format_score=-1.0 if failure=='format' else 0.0 if failure is None else None,
            truncation_score=None if failure=='infrastructure' else -1.0 if failure=='truncation' else 0.0,
            retry_scheduled=failure is not None and index==0)
        attempts.append(record)
        if on_call:on_call(record)
        if failure is None:break
        feedback={
            'truncation': 'The previous attempt reached the output token limit without a completed submission. '
                'Start a fresh response. Keep the explanation concise and reserve room for the complete tool call within the same output budget.',
            'format': 'The previous attempt did not provide a valid submission for this task. '
                'Start a fresh response with a concise explanation and exactly one tool call matching the supplied schema. '
                + ('Answer each listed query exactly once.' if stage=='B' else 'Submit one exact legal action object.'),
            'infrastructure': 'The previous request failed at the service level. Answer the same task.'
        }[failure]
    result=deepcopy(attempts[-1])
    result.update(attempts=attempts,attempt_count=len(attempts),
                  recovered_on_retry=len(attempts)==2 and attempts[-1]['failure_category'] is None,
                  seconds=sum(a['seconds'] for a in attempts))
    return result


def actual_b(record):
    if record['status']=='ok': return deepcopy(record['answer'])
    # Raw failed text/tool instructions remain in the audit log, outside P's task.
    # Do not infer an answer from prose or replace it with a teacher label.
    return dict(submission_status=record['status'],judgments_available=False)


def supervision_signals(env, b, p, values):
    """Decision-local signals for auditing, not PPO advantages or token losses.

    Keep outcome scores separate from protocol failures. Legacy B accuracy
    metrics also count missing targets as errors and must not be used as a
    combined training reward. Unavailable scores stay None, never optimal zero.
    """
    result={}
    for stage,record in (('B',b),('P',p)):
        rows=[]
        for attempt in record['attempts']:
            score=None
            if attempt['failure_category'] is None:
                if stage=='B':
                    scored=env.score_b(attempt['answer'])
                    if scored['mask']:score=scored['score']
                elif values['mask']:
                    chosen=next(v['value'] for v in values['values'] if v['action']==attempt['answer'])
                    score=chosen-max(v['value'] for v in values['values'])
            failure=attempt['failure_category']
            reward_mask=score is not None or failure in ('format','truncation')
            reward=(sum(x for x in (score,attempt['format_score'],attempt['truncation_score']) if x is not None)
                    if reward_mask else None)
            rows.append(dict(attempt_index=attempt['attempt_index'],
                task_score=score,task_mask=score is not None,
                task_basis='B_final_judgments' if stage=='B' else 'P_reference_regret',
                format_score=attempt['format_score'],format_mask=attempt['format_score'] is not None,
                truncation_score=attempt['truncation_score'],
                truncation_mask=attempt['truncation_score'] is not None,
                reward=reward,reward_mask=reward_mask,
                truncated=attempt['failure_category']=='truncation',
                infrastructure_failure=attempt['failure_category']=='infrastructure'))
        result[stage]=rows
    return result


def b_metrics(env, answer, submission_ok=True):
    score=env.score_b(answer); table=env.belief_table() or []
    gold={(b['player'],b['goal']):b['answer'] for b in table}
    usable=not(env.invalid_reason or env.fragile)
    informative={k for k,g in gold.items() if len(g['possible_preferences'])<3}
    chosen={}; details=[]
    assessments={(x['player'],x['goal']):x['assessment'] for x in score['selected']}
    if isinstance(answer,list):
        for x in answer:
            if isinstance(x,dict) and type(x.get('player')) is int and type(x.get('goal')) is int:
                chosen[(x['player'],x['goal'])]=x
    for target,g in gold.items():
        x=chosen.get(target); selected=x is not None; valid=False
        if selected:
            valid=assessments[target]['format_valid'] and submission_ok
        exact=bool(valid and set(x['possible_preferences'])==set(g['possible_preferences']) and x['favored']==g['favored']) if usable else None
        details.append(dict(player=target[0],goal=target[1],selected=selected,valid=valid,
            informative=target in informative,gold=g,prediction=x,exact=exact,
            set_exact=(set(x['possible_preferences'])==set(g['possible_preferences'])) if usable and valid else None,
            favored_exact=(x['favored']==g['favored']) if usable and valid else None,
            false_exclusions=len(set(g['possible_preferences'])-set(x['possible_preferences'])) if usable and valid else None,
            extra_possibilities=len(set(x['possible_preferences'])-set(g['possible_preferences'])) if usable and valid else None))
    return dict(score=score,submission_ok=submission_ok,teacher_available=usable and bool(table),
        eligible_targets=len(table),selected_eligible_targets=sum(d['selected'] for d in details),
        informative_targets=len(informative),selected_informative_targets=sum(d['selected'] and d['informative'] for d in details),
        target_details=details,
        target_usefulness='Fixed initial-catalogue queries. Every query is required; per-target semantics and whole-submission protocol are separate.')


def inspect_decision(env, client, *, b_tokens=1024,p_tokens=1024,p_rollouts=512,p_seconds=20,on_call=None):
    started=time.monotonic();t=time.monotonic();env.ensure_teacher();teacher_setup=time.monotonic()-t
    context=env.context();b=call_stage(env,client,'B',context,b_tokens,on_call)
    answer=actual_b(b)
    t=time.monotonic();bs=b_metrics(env,answer,b['status']=='ok');btime=time.monotonic()-t
    # Target/field validation is public protocol validation, independent of gold
    # correctness. Wrong but well-formed beliefs still pass through unchanged.
    handoff='as_submitted' if b['status']=='ok' else 'unavailable'
    if b['status']=='ok' and not bs['score']['format_valid']:
        answer=dict(submission_status='invalid_judgments',judgments_available=False)
        handoff='unavailable'
    pc=p_input(context,answer);p=call_stage(env,client,'P',pc,p_tokens,on_call)
    t=time.monotonic();values=env.p_reference_values(max_rollouts=p_rollouts,seconds=p_seconds);ptime=time.monotonic()-t
    selected=None;regret=None;best=None;opts=[];social_opts=[];social_regret=None
    if values['mask']:
        best=max(r['value'] for r in values['values']);opts=[r['action'] for r in values['values'] if abs(r['value']-best)<1e-8]
        if values.get('others_mask',True):
            best_other=max(r['others_value'] for r in values['values'] if r['action'] in opts)
            social_opts=[r['action'] for r in values['values'] if r['action'] in opts and abs(r['others_value']-best_other)<1e-8]
        if p['status']=='ok':
            selected=next(r['value'] for r in values['values'] if r['action']==p['answer']);regret=selected-best
            if p['answer'] in opts and values.get('others_mask',True):
                social_regret=next(r['others_value'] for r in values['values'] if r['action']==p['answer'])-best_other
    return dict(input=context,B=b,P=p,actual_model_B=answer,B_metrics=bs,teacher_B=env.belief_table(),
        supervision=supervision_signals(env,b,p,values),
        P_metrics=dict(legal=p['status']=='ok',reference=values,chosen_reference_value=selected,
            best_reference_value=best,reference_regret=regret,acceptable_actions=opts,
            social_tie_acceptable_actions=social_opts,others_regret_when_own_optimal=social_regret,
            reference_optimal=(regret>=-1e-8) if regret is not None else None,
            reference_discriminates=(len(opts)<len(values['values'])) if values['mask'] else None),
        B_passthrough_exact=pc['model_beliefs']==answer,B_handoff_status=handoff,
        timings=dict(teacher_setup_seconds=teacher_setup,B_call_seconds=b['seconds'],P_call_seconds=p['seconds'],
            B_scoring_seconds=btime,P_scoring_seconds=ptime,total_seconds=time.monotonic()-started),
        teacher_unavailable=env.invalid_reason,fragile_evidence=env.fragile)


def load_pack(path, cohort='planning'):
    if cohort=='both':
        summary,a=load_pack(path,'planning');_,b=load_pack(path,'belief')
        points={}
        for name,rows in [('planning',a),('belief',b)]:
            for point in rows:
                rid=point['row']['id']
                if rid in points:
                    if any(points[rid][k]!=point[k] for k in ('row','raw','events')):
                        raise ValueError('Overlapping cohort point differs')
                    points[rid]['cohorts'].append(name)
                else:points[rid]=dict(point,cohorts=[name])
        return summary,list(points.values())
    check_pack(path)
    summary=json.loads((path/'summary.json').read_text())
    if summary.get('protocol')!=VERSION or not (path/'questions.jsonl').exists():
        raise ValueError('Requires a versioned online pack. Legacy static 83-point labels must not be silently reused.')
    filename=summary.get('cohorts',{}).get(cohort, 'questions.jsonl' if cohort=='planning' else None)
    if filename is None:raise ValueError('Pack has no requested cohort')
    rows=read_rows(path/filename);traces=read_rows(path/'trajectories.jsonl')
    games={p.stem:json.loads(p.read_text())['fixture'] for p in (path/'games').glob('*.json')}
    points=[]
    for row in rows:
        n=len(row['input']['history'])
        matches=[t for t in traces if t['source']==row['source'] and row['id'] in t['snapshots'] and t['history'][:n]==row['input']['history']]
        if not matches:raise ValueError('Missing versioned history provenance')
        events=matches[0]['events'][:n]
        if any(t['events'][:n]!=events for t in matches):raise ValueError('Ambiguous event provenance')
        points.append(dict(row=row,raw=games[row['source']],events=events,cohorts=[cohort]))
    return summary,points


def restore(point, **budgets):
    env=OnlineSocial.replay_events(point['raw'],point['events'],protocol=VERSION,**budgets)
    if env.context()!=point['row']['input']:raise ValueError('Replayed visible input differs from frozen point')
    # Budget failure is a masked observation, not a reason to reuse saved labels.
    saved=point['row']['teacher']['B_by_target']
    if env.belief_table() is not None and env.belief_table()!=saved:raise ValueError('Replayed B differs from frozen teacher')
    return env


def temporal_pair(before, after, before_id=None, after_id=None):
    a={(d['player'],d['goal']):d for d in before['B_metrics']['target_details']}
    b={(d['player'],d['goal']):d for d in after['B_metrics']['target_details']}
    details=[]
    if before['B_metrics']['teacher_available'] and after['B_metrics']['teacher_available']:
        for k in a.keys() & b.keys():
            x,y=a[k],b[k];category='maintain' if x['gold']==y['gold'] else 'update'
            both_selected=x['selected'] and y['selected'];both_valid=both_selected and x['valid'] and y['valid']
            pred=lambda d: (frozenset(d['prediction']['possible_preferences']),d['prediction']['favored'])
            details.append(dict(player=k[0],goal=k[1],category=category,both_selected=both_selected,
                both_valid=both_valid,both_exact=bool(both_valid and x['exact'] and y['exact']),
                prediction_changed=(pred(x)!=pred(y)) if both_valid else None,
                correct_before=x['exact'],correct_after=y['exact']))
    return dict(before=before_id,after=after_id,targets=details)


def continue_episode(env, world, client, first, on_record, on_event=None, **options):
    records=[];status='terminal';started=time.monotonic();start_index=len(env.events)
    while not env.terminal:
        if env.actor==env.raw['ego']:
            r=deepcopy(first) if not records else inspect_decision(env,client,**options)
            r['event_index']=len(env.events);records.append(r);on_record(r)
            if r['P']['status']!='ok':status='model_action_failure';break
            t=time.monotonic();env.step(r['P']['answer'],kind='learner')
        else:
            t=time.monotonic();action=env.reference_action(world[env.actor]);env.step(action,kind='partner')
        if on_event:on_event(dict(event=env.events[-1],seconds=time.monotonic()-t,
            public_state=env.node.state.public_state(),teacher_B=env.belief_table()))
    utilities=env.outcome(world) if env.terminal else None
    return dict(status=status,terminal=env.terminal,utilities=utilities,ego_utility=utilities[env.raw['ego']] if utilities is not None else None,
        environment_world=world,history=env.history,events=env.events,start_event_index=start_index,records=records,
        pairs=[temporal_pair(a,b,i,i+1) for i,(a,b) in enumerate(zip(records,records[1:]))],
        teacher_unavailable=env.invalid_reason,usable_for_training=env.terminal and env.invalid_reason is None,
        seconds=time.monotonic()-started,first_decision_reused=True)


def aggregate(records):
    def mean(xs):return sum(xs)/len(xs) if xs else None
    details=[d for r in records if r['B_metrics']['teacher_available'] for d in r['B_metrics']['target_details']]
    selected=[d for d in details if d['selected']];info=[d for d in details if d['informative']]
    info_selected=[d for d in info if d['selected']];valid=[d for d in selected if d['valid']]
    support_groups={}
    for d in details:
        support_groups.setdefault('/'.join(d['gold']['possible_preferences']),[]).append(d)
    p=[r['P_metrics'] for r in records];available=[x for x in p if x['reference']['mask']]
    regrets=[x['reference_regret'] for x in available if x['reference_regret'] is not None]
    attempts={s:[a for r in records for a in r[s].get('attempts',[r[s]])] for s in ('B','P')}
    return dict(n=len(records),attempts={s:dict(
        total=len(rows),retries=sum(a.get('attempt_index',0)>0 for a in rows),
        recovered=sum(r[s].get('recovered_on_retry',False) for r in records),
        failure_categories=dict(Counter(a.get('failure_category') or 'none' for a in rows)),
        format_failures=sum(a.get('failure_category')=='format' for a in rows),
        truncations=sum(a.get('failure_category')=='truncation' for a in rows)) for s,rows in attempts.items()},
        B_submission_statuses=dict(Counter(r['B']['status'] for r in records)),
        P_submission_statuses=dict(Counter(r['P']['status'] for r in records)),
        B_handoff_statuses=dict(Counter(r.get('B_handoff_status','legacy') for r in records)),
        B_format_success_rate=mean([r['B']['status']=='ok' and r['B_metrics']['score']['format_valid'] for r in records]),
        B_teacher_available=sum(r['B_metrics']['teacher_available'] for r in records),
        B_aux_scored=sum(r['B_metrics']['score']['mask'] for r in records),
        B_eligible_targets=len(details),B_selected_targets=len(selected),B_target_coverage=mean([d['selected'] for d in details]),
        B_selected_exact_rate=mean([bool(d['exact']) for d in selected]),
        B_required_exact_rate=mean([bool(d['exact']) for d in details]),
        B_by_support={s:dict(n=len(ds),exact_rate=mean([bool(d['exact']) for d in ds])) for s,ds in sorted(support_groups.items())},
        B_support_macro_exact_rate=mean([mean([bool(d['exact']) for d in ds]) for ds in support_groups.values()]),
        B_complete_exact_rate=mean([bool(r['B_metrics']['submission_ok'] and r['B_metrics']['score']['format_valid']
            and all(d['exact'] for d in r['B_metrics']['target_details'])) for r in records if r['B_metrics']['teacher_available']]),
        B_protocol_errors=dict(Counter(e for r in records for e in r['B_metrics']['score'].get('protocol_errors',[]))),
        B_mean_protocol_score=mean([r['B_metrics']['score'].get('protocol_score',0) for r in records]),
        B_selected_set_exact_rate=mean([bool(d['set_exact']) for d in selected]),
        B_selected_favored_exact_rate=mean([bool(d['favored_exact']) for d in selected]),
        B_mean_false_exclusions_valid=mean([d['false_exclusions'] for d in valid]),
        B_mean_extra_possibilities_valid=mean([d['extra_possibilities'] for d in valid]),
        B_informative_targets=len(info),B_selected_informative=len(info_selected),
        B_informative_coverage=mean([d['selected'] for d in info]),
        B_selected_informative_exact_rate=mean([bool(d['exact']) for d in info_selected]),
        B_informative_set_exact_rate_valid=mean([bool(d['set_exact']) for d in info_selected if d['valid']]),
        B_informative_favored_exact_rate_valid=mean([bool(d['favored_exact']) for d in info_selected if d['valid']]),
        B_correct_informative_fraction_of_all=mean([bool(d['selected'] and d['exact']) for d in info]),
        B_all_possible_undetermined_baseline=mean([len(d['gold']['possible_preferences'])==3 and d['gold']['favored']=='undetermined' for d in details]),
        B_empty_selection=sum(r['B']['status']=='ok' and r['B']['answer']==[] for r in records),
        P_legal_rate=mean([x['legal'] for x in p]),P_reference_available=len(available),
        P_reference_discriminating=sum(bool(x['reference_discriminates']) for x in available),
        P_optimal_rate_discriminating=mean([x['reference_optimal'] is True for x in available if x['reference_discriminates']]),
        P_optimal_rate_discriminating_legal=mean([x['reference_optimal'] is True for x in available if x['reference_discriminates'] and x['legal']]),
        P_optimal_rate_all_reference_available=mean([x['reference_optimal'] is True for x in available]),
        P_mean_reference_regret_legal=mean(regrets),
        P_unavailable_reasons=dict(Counter(x['reference'].get('reason') for x in p if not x['reference']['mask'])),
        B_reasoning_present_rate=mean([r['B']['reasoning_chars']>0 for r in records]),
        P_reasoning_present_rate=mean([r['P']['reasoning_chars']>0 for r in records]),
        B_explanation_statuses=dict(Counter(r['B']['explanation_status'] for r in records)),
        P_explanation_statuses=dict(Counter(r['P']['explanation_status'] for r in records)),
        mean_timing_seconds={k:mean([r['timings'][k] for r in records]) for k in records[0]['timings']} if records else {},
        B_passthrough_all=all(r['B_passthrough_exact'] for r in records))


def write_summary(out, records, episodes, pairs, actual_lm):
    sources=sorted({r['source'] for r in records})
    pair_targets=[d for p in pairs for d in p['targets']]
    errors=read_rows(out/'errors.jsonl') if (out/'errors.jsonl').exists() else []
    summary=dict(version=EVAL_VERSION,prompt_version=PROMPT_VERSION,actual_LM=actual_lm,errors=errors,fixed=aggregate(records),
        by_cohort={c:aggregate([r for r in records if c in r.get('cohorts',[])])
                   for c in sorted({c for r in records for c in r.get('cohorts',[])})},
        by_source={s:aggregate([r for r in records if r['source']==s]) for s in sources},
        by_phase={phase:aggregate([r for r in records if ('response' if r['input']['pending_offer'] else 'proposal')==phase])
                  for phase in ('proposal','response')},
        by_value_basis={basis:aggregate([r for r in records if r['P_metrics']['reference'].get('basis')==basis])
                        for basis in ('direct_terminal','reference_continuation')},
        planning_discriminating=aggregate([r for r in records if r['P_metrics']['reference'].get('basis')=='reference_continuation'
                                           and r['P_metrics']['reference_discriminates']]),
        post_evidence_planning=aggregate([r for r in records if r['P_metrics']['reference'].get('basis')=='reference_continuation'
            and r['P_metrics']['reference_discriminates'] and r['B_metrics']['teacher_available']
            and r['B_metrics']['informative_targets']>0]),
        pairs={kind:dict(n=sum(d['category']==kind for d in pair_targets),
            both_selected=sum(d['category']==kind and d['both_selected'] for d in pair_targets),
            both_exact=sum(d['category']==kind and d['both_exact'] for d in pair_targets)) for kind in ['maintain','update']},
        continuations=dict(n=len(episodes),terminal=sum(e['terminal'] for e in episodes),
            usable=sum(e['usable_for_training'] for e in episodes),
            statuses=dict(Counter(e['status'] for e in episodes)),
            outcomes=[dict(id=e['id'],world_index=e['world_index'],utilities=e['utilities'],usable=e['usable_for_training']) for e in episodes]),
        limitations=['All fixed queries are required. Per-target semantic accuracy does not erase protocol failures.',
            'Explanation presence checks visible text only, not reasoning correctness; answer validity is scored separately.',
            'Reference regret is not LM advantage. Actual terminal payoff is recorded separately.',
            'No causal B-to-P claim from passthrough or accuracy alone.',
            'Favored uses the existing teacher margin convention; inspect disagreements separately from support errors.',
            'Static point scores use declared teacher histories; online continuation uses actual model actions.'])
    (out/'summary.tmp').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');(out/'summary.tmp').replace(out/'summary.json')
    return summary


def _evaluate_point(point,client,args,roots,emit):
    """An isolated game/solver per task; only the parent writes shared output files."""
    rid=point['row']['id'];start=time.monotonic()
    options=dict(b_tokens=args.b_max_tokens,p_tokens=args.p_max_tokens,
                 p_rollouts=args.p_rollouts,p_seconds=args.p_seconds)
    try:
        env=restore(point,**point['row'].get('solver_budgets',{}))
        def fixed_call(c):emit('calls.jsonl',dict(id=rid,mode='fixed',call=c))
        r=inspect_decision(env,client,on_call=fixed_call,**options)
        r.update(id=rid,source=point['row']['source'],cohorts=point.get('cohorts',[]),
                 worker_pid=os.getpid(),replay_seconds=time.monotonic()-start-r['timings']['total_seconds'])
        emit('decisions.jsonl',r)
        if args.continue_game and (not args.roots_only or rid in roots):
            worlds=env.worlds if args.max_worlds==0 else env.worlds[:args.max_worlds]
            for wi,world in enumerate(worlds):
                def event(record):emit('continuation_decisions.jsonl',dict(id=rid,world_index=wi,record=record))
                def call(c):emit('calls.jsonl',dict(id=rid,world_index=wi,mode='continuation',call=c))
                def transition(e):emit('events.jsonl',dict(id=rid,world_index=wi,**e))
                e=continue_episode(env.fork(),world,client,r,event,on_event=transition,on_call=call,**options)
                e.update(id=rid,source=r['source'],world_index=wi)
                emit('episodes.jsonl',e)
    except Exception as exc:
        emit('errors.jsonl',dict(id=rid,error_type=type(exc).__name__,reason=str(exc)))
    finally:emit('_done',dict(id=rid,seconds=round(time.monotonic()-start,2)))


def _init_worker(client,endpoints,dry_run,slots,messages):
    global _worker_client, _worker_messages
    _worker_client=deepcopy(client);_worker_messages=messages
    slot=slots.get()
    if endpoints and not dry_run:_worker_client.base_url=endpoints[slot%len(endpoints)].rstrip('/')


def _worker_point(point,args,roots):
    def emit(name,row):_worker_messages.put((name,row))
    _evaluate_point(point,_worker_client,args,roots,emit)


def run(args, client):
    summary,points=load_pack(args.data_dir,cohort=getattr(args,'cohort','planning'))
    if summary.get('B_task_version')!=TASK_VERSION:
        raise ValueError('This runner requires a regenerated fixed-query pack. Use social_dataset_v3; preserve the old run as its original baseline.')
    if args.source:points=[p for p in points if p['row']['source']==args.source]
    if args.limit:points=points[:args.limit]
    if not points:raise ValueError('No selected points')
    if args.output_dir.exists():raise ValueError('Use a new output directory')
    out=args.output_dir;out.mkdir(parents=True)
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    config.update(version=EVAL_VERSION,prompt_version=PROMPT_VERSION,protocol=VERSION,B_task_version=TASK_VERSION,actual_LM=not args.dry_run,point_ids=[p['row']['id'] for p in points],
        dataset_checksums_sha256=hashlib.sha256((args.data_dir/'checksums.json').read_bytes()).hexdigest(),
        implementation_sha256={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
            for name in ['social_lm_eval.py','social_presentation.py','online_social.py','shared_teacher.py','favored_belief.py','social_task.py']},
        tool_choice='auto',max_retries_per_stage=1,repetition_penalty=None,
        scoring_contract=deepcopy(SCORING_CONTRACT),
        reasoning='Visible explanation before the tool. At most one same-state retry with public failure feedback and unchanged token budget. Every attempt retained; truncation, format and infrastructure failures separated. No optimizer or repetition penalty.',
        continuation_world_selection='All compatible worlds' if args.max_worlds==0 else 'First N compatible catalogue worlds; not an unbiased outcome estimate')
    (out/'run_config.json').write_text(json.dumps(config,indent=2)+'\n')
    records=[];episodes=[];pairs=[];index={}
    def append(name,row):
        with (out/name).open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
    (out/'review').mkdir()
    def consume(name,row):
        if name=='_done':
            write_summary(out,records,episodes,pairs,not args.dry_run)
            r=index.get(row['id'])
            print(json.dumps(dict(row,completed=len(records),episodes=len(episodes),
                                  timings=r['timings'] if r else None)),flush=True)
            return
        append(name,row)
        if name=='decisions.jsonl':
            records.append(row);index[row['id']]=row
            (out/'review'/f"{row['id']}.json").write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
            write_summary(out,records,episodes,pairs,not args.dry_run)
        elif name=='episodes.jsonl':episodes.append(row)
    workers=getattr(args,'workers',1)
    if workers==1:
        if getattr(args,'base_urls',None) and not args.dry_run:
            client=deepcopy(client);client.base_url=args.base_urls[0].rstrip('/')
        for point in points:_evaluate_point(point,client,args,summary['root_questions'],consume)
    else:
        ctx=multiprocessing.get_context('spawn')
        messages=ctx.Queue();slots=ctx.Queue()
        try:
            for i in range(workers):slots.put(i)
            with ProcessPoolExecutor(max_workers=workers,mp_context=ctx,initializer=_init_worker,
                    initargs=(client,getattr(args,'base_urls',None),args.dry_run,slots,messages)) as executor:
                futures=[executor.submit(_worker_point,p,args,summary['root_questions']) for p in points]
                done=0
                while done<len(points):
                    try:name,row=messages.get(timeout=.5)
                    except Empty:
                        for f in futures:
                            if f.done():f.result()  # Surface crashed workers instead of waiting forever.
                        continue
                    consume(name,row)
                    if name=='_done':done+=1
                for f in futures:f.result()
        finally:
            messages.close();slots.close()
    # Completion order may vary; saved aggregate/review order remains the dataset order.
    order={p['row']['id']:i for i,p in enumerate(points)}
    records.sort(key=lambda r:order[r['id']])
    episodes.sort(key=lambda e:(order[e['id']],e['world_index']))
    for pair in read_rows(args.data_dir/'pairs.jsonl'):
        if pair['before'] in index and pair['after'] in index:
            p=temporal_pair(index[pair['before']],index[pair['after']],pair['before'],pair['after']);pairs.append(p);append('pairs.jsonl',p)
    final=write_summary(out,records,episodes,pairs,not args.dry_run)
    final['requested_points']=len(points);final['failed_points']=len(points)-len(records)
    (out/'summary.json').write_text(json.dumps(final,indent=2)+'\n')
    lines=['# LM 决策点审查','',f'真实 LM：{not args.dry_run}。实际输出、输入、教师标签和耗时见逐点链接；完整后续见 episodes.jsonl。',
        '', '| 决策点 | B 有信息目标：选择/可选 | B 局部评分 | P 状态 | P 参考 regret |', '|---|---:|---:|---|---:|']
    for r in records:
        b=r['B_metrics'];q=r['P_metrics']
        lines.append(f"| [{r['id']}](review/{r['id']}.json) | {b['selected_informative_targets']}/{b['informative_targets']} | {b['score']['score']} | {r['P']['status']} | {q['reference_regret']} |")
    (out/'REVIEW.md').write_text('\n'.join(lines)+'\n')
    return final


class DryClient:
    """Visible-catalogue all-possible baseline plus first legal action. Not an LM."""
    def complete_with_tools(self,messages,*,tools,**kwargs):
        from methods.vllm_client import VLLMChatCompletion,VLLMToolCall
        ctx=json.loads(messages[-1]['content']);name=tools[0]['function']['name']
        if name=='SUBMIT_ACTION':answer=deepcopy(ctx['legal_actions'][0])
        else:
            judgments=[]
            for player,types in ctx['public_type_catalogues'].items():
                if int(player)==ctx['player']:continue
                for goal in range(len(types[0])):
                    values={row[f'goal_{goal}'] for row in types}
                    if len(values)>1:
                        labels=[label for label in ('want','neutral','avoid') if label in values]
                        judgments.append(dict(player=int(player),goal=goal,possible_preferences=labels,favored='undetermined'))
            answer=dict(judgments=judgments)
        return VLLMChatCompletion('',(VLLMToolCall(name,answer,raw_arguments=json.dumps(answer)),),
            dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(answer)))]),{},'tool_calls')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=Path('new/local_data/social_generalization_v4'))
    p.add_argument('--cohort',choices=['planning','belief','both'],default='planning',
                   help='Task-specific cohort, or both with shared points evaluated once and reported in both cohorts')
    p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--base-url');p.add_argument('--model')
    p.add_argument('--workers',type=int,default=1,help='Independent CPU/game workers; B then P remains sequential within each game')
    p.add_argument('--base-urls',nargs='+',help='Replica API URLs ending in /v1; workers bind round-robin to endpoints')
    p.add_argument('--dry-run',action='store_true');p.add_argument('--source');p.add_argument('--limit',type=int,default=0)
    p.add_argument('--continue-game',action='store_true');p.add_argument('--roots-only',action='store_true')
    p.add_argument('--max-worlds',type=int,default=0,help='0 = all compatible worlds')
    p.add_argument('--b-max-tokens',type=int,default=1024);p.add_argument('--p-max-tokens',type=int,default=1024)
    p.add_argument('--temperature',type=float,default=0);p.add_argument('--timeout',type=float,default=180)
    p.add_argument('--p-rollouts',type=int,default=512);p.add_argument('--p-seconds',type=float,default=20)
    args=p.parse_args()
    if min(args.limit,args.max_worlds)<0 or min(args.b_max_tokens,args.p_max_tokens,args.p_rollouts,args.timeout,args.p_seconds)<=0:p.error('Invalid budget')
    if args.workers<1:p.error('--workers must be positive')
    if args.base_url and args.base_urls:p.error('Use --base-url or --base-urls, not both')
    if args.base_urls:
        if any(not u.rstrip('/').endswith('/v1') for u in args.base_urls):p.error('--base-urls must end in /v1')
        if len(args.base_urls)>args.workers:p.error('Provide at least one worker per endpoint')
        args.base_url=args.base_urls[0]
    if args.dry_run:client=DryClient()
    else:
        if not(args.base_url and args.model):p.error('Supply --base-url and --model, or --dry-run')
        from methods.vllm_client import OpenAICompatibleNegotiationClient
        client=OpenAICompatibleNegotiationClient(args.base_url,args.model,api_key=os.environ.get('BENAC_P_VLLM_API_KEY','EMPTY'),
            temperature=args.temperature,timeout=args.timeout)
    print(json.dumps(run(args,client),indent=2))


if __name__=='__main__':main()
