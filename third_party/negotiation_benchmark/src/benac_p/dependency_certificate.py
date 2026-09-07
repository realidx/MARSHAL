"""Oracle-only, tie-robust certificate for a useful judgment update.

Hold the first action, resulting history and physical state fixed. Compare
reference planning with the updated judgment against every action optimal under
the frozen root judgment. No LLM answer participates in admission.
"""
from benac_p.endgame_partner import InconsistentPartnerHistory

VERSION = 'strict-update-value-v2'


def certify(f):
    root_q=f.search.q_values(f.root)
    best=max(v for _,v in root_q)
    candidates=[a for a,v in root_q if best-v<1e-9]
    # All candidates maximize terminal utility. Prefer the first certifiable
    # native menu in this supplement; other utility-optimal choices remain valid.
    from benac_p.schema import OfferProposal, MenuOffer
    candidates.sort(key=lambda a:not (isinstance(a,OfferProposal) and isinstance(a.offer,MenuOffer)))
    for action in candidates:
        witnesses=[];gain=0.;defined=True
        for branch in f.window_step(f.root,action):
            n=branch.node
            if n.state.is_terminal:continue
            actual=f.search.q_values(n);value=max(v for _,v in actual)
            try:
                frozen=f.search.q_values(f.with_judgment(n,f.support(f.root)))
            except InconsistentPartnerHistory:
                defined=False;break
            frozen_best=max(v for _,v in frozen)
            frozen_optimal=[i for i,(_,v) in enumerate(frozen) if frozen_best-v<1e-9]
            gap=max(0.,value-max(actual[i][1] for i in frozen_optimal))
            gain+=branch.weight*gap
            if gap>1e-9:
                witnesses.append(dict(weight=branch.weight,history=f.history_text(n),
                    commitments=n.state.snapshot_commitments(),pending_offer=None if n.pending is None else n.pending.to_dict(),
                    initial_judgment=f.support(f.root),updated_judgment=f.support(n),
                    actions=[a.to_dict() for a,_ in actual],actual_q=[v for _,v in actual],frozen_q=[v for _,v in frozen],
                    frozen_optimal_indices=frozen_optimal,
                    updated_optimal_indices=[i for i,(_,v) in enumerate(actual) if value-v<1e-9],strict_gap=gap))
        if defined and gain>1e-9:
            return dict(version=VERSION,passed=True,first_action=action.to_dict(),terminal_value=best,
                expected_strict_update_gain=gain,witnesses=witnesses,
                tie_rule='First certifiable menu, otherwise first certifiable action, among terminal-utility maximizers. Other optimal actions receive zero regret.')
    return dict(version=VERSION,passed=False,reason='No terminal-utility-optimal action with a strictly valuable, well-defined update.')


def attach(suite, proofs=None):
    """Select the witnessed reference-action continuation as the primary case."""
    for f in suite.fixtures.values():
        proof=proofs[f.id] if proofs is not None else certify(f)
        cert=suite.certificates[f.id];cert['dependency']=proof
        if not proof['passed']:continue
        cert['root_condition']=cert['condition']
        cert['condition']='dependency'
        from benac_p.endgame_diagnose import decode_action
        suite.add_arm(f,'oracle',decode_action(proof['first_action']))
        cert['oracle_action_update_gain']=next(c['judgment_update_gain'] for c in cert['channels'] if c['action']==proof['first_action'])
        witness=max(proof['witnesses'],key=lambda w:w['weight']*w['strict_gap'])
        matches=[b['case'] for b in suite.arms[f.id]['oracle']['branches']
                 if f.history_text(suite.cases[b['case']]['node'])==witness['history']]
        if len(matches)!=1:raise AssertionError('Dependency witness must identify one measured oracle-action branch.')
        cert['primary_case']=matches[0]
        cert['primary_selection']='Strictly valuable posterior update at the reference-action continuation; selected without model answers.'
