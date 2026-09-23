"""Structural ordering within existing B/O/P interfaces, not a mastery estimate."""
VERSION = 'within-view-curriculum-v2'


def describe(task):
    i=task.get('input',{});g=i.get('game',{});s=i.get('current_state',{})
    view=task.get('paired_view',task.get('task'))
    # P source history is audit-only and MUST NOT set its difficulty.
    history=0 if view=='Pplus' else len(i.get('voluntary_history',[]))
    goals=g.get('goals',[])
    shared={}
    for goal in goals:
        for a in goal.get('required_actions',[]):
            key=(a['player_id'],a['action_id']);shared[key]=shared.get(key,0)+1
    remaining=max(0,len(g.get('round_robin',[]))-s.get('turn_index',0))
    # A structural proxy only. No gold support size, model correctness or validation scores.
    complexity=(remaining,history,len(goals),sum(n>1 for n in shared.values()),
                len(i.get('legal_actions',[])),g.get('n_players',0))
    # Explicit scene bands, not auxiliary questions or model-outcome filtering.
    # Terminal, small scenes precede longer chains and entangled goal structures.
    tier=0 if remaining<=1 and len(goals)<=2 and history<=2 else 1 if remaining<=2 and len(goals)<=3 and history<=4 else 2
    return dict(tier=tier,tier_name=('foundation','intermediate','compositional')[tier],version=VERSION,view=view,remaining_opportunities=remaining,
                visible_history_events=history,goals=len(goals),shared_commitments=sum(n>1 for n in shared.values()),
                legal_actions=len(i.get('legal_actions',[])),order=[tier]+list(complexity),
                status='structural_proxy_not_empirically_certified')
