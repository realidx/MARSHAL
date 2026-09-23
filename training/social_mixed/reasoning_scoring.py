"""Preserve binary training rewards; expose decision consequences separately."""
import json


def decision_metrics(task, completion):
    from training.b_sft import social_named_probe as named
    if task['task']=='B':return {}
    calls=completion.get('raw_message',{}).get('tool_calls') or []
    if completion.get('finish_reason')=='length' or len(calls)!=1:
        return dict(action_index=None,own_regret=None)
    try:
        call=calls[0]['function'];args=json.loads(call['arguments'])
        visible=named.present(task,task.get('name_variant',0))
        matches=[j for j,a in enumerate(visible['legal_actions']) if named.action_call(a)==(call['name'],args)]
        if len(matches)!=1:raise ValueError('Action is not uniquely legal')
        j=matches[0];p=task['input']['player'];values=[v[p] for v in task['teacher']['action_values']]
        return dict(action_index=j,own_regret=max(values)-values[j],own_value=values[j])
    except (KeyError,ValueError,TypeError):
        return dict(action_index=None,own_regret=None)


def score(task, completion):
    """Tri-state P semantics, independent of native protocol validity."""
    from training.b_sft.social_bp_training import reward
    result=reward(task,completion)
    if task.get('paired_view')=='B':
        from training.social_mixed.b_belief_contract import accepted_favored, VERSION
        result['strict_correct']=result.get('correct',False)
        result['b_contract_version']=VERSION
        if result.get('status')=='ok' and completion.get('finish_reason')!='length':
            call=completion['raw_message']['tool_calls'][0]['function']
            judgment=json.loads(call['arguments'])['judgments'][0]
            allowed=accepted_favored(task['teacher']['preference_weights'])
            result['favored_accepted']=judgment['favored'] in allowed
            result['correct']=bool(result.get('set_exact') and result['favored_accepted'])
            result['reward']=float(result['correct'])
        return result
    policy=task.get('p_supervision')
    if task.get('paired_view')!='Pplus' or policy is None:return result
    result.update(decision_metrics(task,completion))
    result['native_teacher_correct']=result.get('correct')
    index=result.get('action_index')
    if index is None:
        result.update(semantic_eligible=False,semantic_outcome='invalid')
        return result
    label=policy['action_states'][index]
    result.update(semantic_eligible=label!='masked',semantic_outcome=label,
                  correct=None if label=='masked' else label=='positive',reward=float(label=='positive'))
    return result
