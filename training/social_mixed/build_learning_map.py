"""Build an offline design candidate; never writes the live bank or samples models.

Feedback strata describe one training run, not intrinsic difficulty or Q0 mastery.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return [json.loads(line) for line in path.open() if line.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feedback(row):
    if row is None:
        return {'stratum': 'unobserved', 'exposures': 0}
    events = row['events']
    mixed = sum(e['counts'].get('correct', 0) > 0 and e['counts'].get('wrong', 0) > 0 for e in events)
    counts = Counter()
    for e in events:
        counts.update(e['counts'])
    if row['persistent_failure_observed']:
        tier = 'persistent_failure_review'
    elif len(events) < 2:
        tier = 'single_exposure_insufficient'
    elif mixed:
        tier = 'observed_semantic_contrast'
    elif counts['correct'] and not counts['wrong'] and not any(counts[k] for k in ('invalid', 'truncated', 'masked')):
        tier = 'observed_all_correct_recheck'
    else:
        tier = 'mixed_or_insufficient_evidence'
    return dict(stratum=tier, exposures=len(events), counts=dict(counts), mixed_groups=mixed,
                effective_groups=sum(e['effective'] for e in events),
                first_step=events[0]['step'], last_step=events[-1]['step'],
                events=events)


def operation(task):
    inp = task['input']
    view = task.get('paired_view', task['task'])
    if view == 'B':
        return 'belief_' + task['skill']
    if inp.get('pending_offer'):
        return 'offer_response'
    if task.get('skill') == 'result_use':
        return 'investigation_result_use'
    if task.get('skill') == 'information':
        return 'information_acquisition_choice'
    if task.get('skill') == 'history_planning':
        return 'history_action' if view != 'Pplus' else 'belief_conditioned_action'
    return 'known_state_action' if task.get('skill') == 'complete' else 'uncertain_state_action'


def build(out):
    files = {
        'old_bank': ROOT/'examples/social_mixed/data_reasoning_v5_candidate/bp_train.jsonl',
        'current_bank': ROOT/'examples/social_mixed/paired_bank_v2/tasks.jsonl',
        'old_feedback': ROOT/'new/task_learning_audit_20260924/old_BP_main.jsonl',
        'current_feedback': ROOT/'new/task_learning_audit_20260924/new_D.jsonl',
    }
    hashes = {k: sha(v) for k, v in files.items()}
    old = read(files['old_bank']); current = read(files['current_bank'])
    assert all(r['split'] == 'train' for r in old)
    allrows = []; review = []; pools = defaultdict(list)
    feedback_rows = {name: {r['task_id']: r for r in read(files[key])}
                     for name, key in [('old', 'old_feedback'), ('current', 'current_feedback')]}
    for bank_name, tasks in [('old', old), ('current', current)]:
        assert len({t['id'] for t in tasks}) == len(tasks)
        for t in tasks:
            obs = feedback(feedback_rows[bank_name].get(t['id']))
            inp = t['input']; view = t.get('paired_view', t['task'])
            public = dict(bank=bank_name, id=t['id'], split=t['split'], view=view,
                          parent=t.get('canonical_id', t.get('family')), operation=operation(t),
                          source_skill=t['skill'], kernel=t.get('source_kernel', t.get('kernel')),
                          operation_tags=[tag for tag, active in [
                              ('offer_response', bool(inp.get('pending_offer'))),
                              ('investigation_result_present_in_source', bool(inp.get('private_results'))),
                              ('voluntary_history_in_source', bool(inp.get('voluntary_history'))),
                              ('investigation_available', any(a.get('action')=='INVESTIGATE' for a in inp.get('legal_actions', []))),
                              ('previous_belief_auxiliary', bool(inp.get('previous_belief'))),
                              ('history_free_qualitative_planning', bool(t.get('p_information_contract'))),
                          ] if active],
                          completion_mode=t.get('completion_mode'), feedback=obs,
                          response_decision=bool(inp.get('pending_offer')),
                          previous_belief_auxiliary=bool(inp.get('previous_belief')),
                          stored_history_events=len(inp.get('voluntary_history', [])),
                          stored_private_results=len(inp.get('private_results', [])),
                          history_fields_are_audit_only=bool(t.get('source_input_is_audit_only')),
                          p_information_contract=t.get('p_information_contract'),
                          p_train_eligible=t.get('p_train_eligible'),
                          acceptable_count=len(t.get('teacher', {}).get('acceptable_actions', [])),
                          gold_support_size=len(t.get('teacher', {}).get('gold', {}).get('possible_preferences', [])),
                          label_status='source_label_not_reproved')
            allrows.append(public)
            if t['split'] != 'train':
                continue
            if view == 'Pplus' and not t.get('p_train_eligible', False):
                slot = 'retain_existing_P_ineligibility'
            else:
                slot = obs['stratum']
            pools[bank_name+'/'+view+'/'+slot].append(t['id'])
            if obs['stratum'] == 'persistent_failure_review':
                review.append(dict(bank=bank_name, id=t['id'], operation=operation(t),
                                   source_task=t, feedback=obs,
                                   questions=['Can the gold be derived from the rendered visible prompt?',
                                              'Does the label depend on an unspecified selected continuation policy?',
                                              'Which prerequisite operation fails before the final answer?'],
                                   disposition='review_pending_not_deleted'))
    # Identity links establish provenance only, never semantic equivalence or permission to move splits.
    indexes = {key: defaultdict(list) for key in ('native_task_id', 'semantic_id', 'origin_id')}
    for t in current:
        for key, ix in indexes.items():
            if t.get(key):ix[t[key]].append(t)
    links = []
    for t in old:
        matches = {}
        for key, ix in indexes.items():
            value = t['id'] if key == 'native_task_id' else t.get(key)
            for target in ix.get(value, []):
                entry = matches.setdefault(target['id'], {'id':target['id'], 'view':target['paired_view'],
                                                          'split':target['split'], 'matched_fields':[]})
                entry['matched_fields'].append(key)
        links.append(dict(old_id=t['id'], old_operation=operation(t), candidates=list(matches.values()),
                          equivalence_verified=False))
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in [('task_map', allrows), ('review_queue', review), ('provenance_links', links)]:
        (out/(name+'.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    # These are current-renderer previews, not the archived requests sent in the old run.
    from training.social_mixed.prompt_clarification import request as old_request
    from training.social_mixed.paired_requests import request as current_request
    previews = []
    for item in review:
        render = old_request if item['bank'] == 'old' else current_request
        previews.append(dict(bank=item['bank'], id=item['id'],
                             request=render(item['source_task']), teacher=item['source_task']['teacher'],
                             status='current_renderer_preview_not_archived_request_not_certified'))
    (out/'review_requests.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in previews))
    manifest = dict(status='offline_design_candidate_not_training_ready', sources=hashes,
                    pools=dict(pools), validation_moved_to_train=False,
                    labels_changed=False, live_sampler_changed=False,
                    strata_are_checkpoint_history_not_intrinsic_difficulty=True)
    (out/'candidate_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    summary = dict(task_counts=dict(Counter(r['bank']+'/'+r['split']+'/'+r['view'] for r in allrows)),
                   candidate_counts={k:len(v) for k,v in pools.items()},
                   review_count=len(review), old_tasks_with_provenance_link=sum(bool(r['candidates']) for r in links))
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    assert hashes == {k:sha(v) for k,v in files.items()}
    assert all(r['source_task']['split']=='train' for r in review)
    return summary


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'new/dataset_redesign_20260924')
    print(json.dumps(build(parser.parse_args().output), ensure_ascii=False, indent=2))
