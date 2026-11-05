"""Own-first continuous regret; switch axis ONLY at own-tied offer responses."""
import numpy as np
from training.b_sft.decision_policy import optimal_indices,is_offer_response

VERSION='native800-response-lexicographic-regret-v1'
TIE_TOLERANCE=1e-9
PROTOCOL_PENALTY=0.2
CONTRACT=dict(version=VERSION,tie_tolerance=TIE_TOLERANCE,
    own_Q='Unchanged full contingent own BR against saved reference to native terminal',
    others_Q='Saved sum of other-player expected terminal utilities under SAME continuation as ownQ',
    proposal='Own Q-max ownQ, never social tie-breaking',
    response='Own Q-max ownQ unless both responses own-optimal; then others Q-max othersQ',
    axis='Determined once from the node, not separately by sampled action',
    correctness='Own-first response-only social protocol, same1e-9 tolerance as saved optimal sets',
    invalid='Worst legal reward on the active axis; separate unchanged protocol penalty -0.2',
    GRPO='Not changed; original within-same-node sample-std advantages',
    D='Keep own terminal D distinct from protocol/social diagnostics; no mixed D ranking activated',
    S='Existing ownS unchanged; do not reinterpret it as social regret')


def values(row):
    own=np.asarray(row['Q'],dtype=float);others=np.asarray(row['Q_others'],dtype=float);actions=row['actions']
    if (own.ndim!=1 or len(own)!=len(actions)or others.shape!=own.shape or not len(own)
            or not np.isfinite(own).all()or not np.isfinite(others).all()):
        raise ValueError('Finite same-continuation own/others Q required for every legal action')
    response=is_offer_response(actions)
    if response and (len(actions)!=2 or {a['response']for a in actions}!={'ACCEPT','REJECT'}):
        raise ValueError('This response scorer requires native ACCEPT/REJECT')
    best=optimal_indices(np.column_stack([own,others]),0,actions,TIE_TOLERANCE)
    own_best=np.flatnonzero(own>=own.max()-TIE_TOLERANCE)
    social=response and len(own_best)==2
    active=others if social else own
    return own,others,own_best,best,active,'others_sum'if social else'own'


def score(row,action_index,status='ok'):
    own,others,own_best,best,axis,mode=values(row)
    valid=status=='ok'and type(action_index)is int and 0<=action_index<len(own)
    if status=='ok'and not valid:raise ValueError('Valid status requires one legal integer action index')
    reward=float(axis[action_index]-axis.max())if valid else float(axis.min()-axis.max())
    own_regret=float(own.max()-own[action_index])if valid else None
    secondary=(float(max(others[own_best])-others[action_index])
        if valid and action_index in own_best and is_offer_response(row['actions'])else None)
    return dict(version=VERSION,status=status,valid=valid,action_index=action_index,
        active_axis=mode,task_reward=reward,protocol_penalty=0. if valid else -PROTOCOL_PENALTY,
        correct=bool(valid and action_index in best),optimal_indices=best.tolist(),
        own_optimal_indices=own_best.tolist(),own_regret=own_regret,
        response_secondary_regret=secondary,protocol_regret=float(-reward)if valid else None,
        Q_own=own.tolist(),Q_others=others.tolist(),
        scope='Decision-local protocol score; not terminalD or a new mainS')
