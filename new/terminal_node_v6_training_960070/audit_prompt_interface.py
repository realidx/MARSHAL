"""Offline audit of historical/current model inputs, without changing training.

Run from the repository root. Uses existing numpy and tokenizer JSON files;
does not require transformers, vLLM, model weights, network, or a GPU.
"""
import ast
from bisect import bisect_right
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile
from zipfile import ZipFile

import numpy as np

from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.social_terminal_teacher import Investigate
from training.strategic_slices.common import digest
from training.social_mixed.frozen.bp_display import Names
from benac_p.endgame_diagnose import decode_action


ROOT=Path(__file__).resolve().parent
OUT=ROOT/'review_20261017/prompt_interface'
TOKENIZER=Path('new/local_data/social_tokenizer')


class OfflineDecoder:
    """Decode archived Qwen ByteLevel BPE IDs, checking against logged text."""
    def __init__(self):
        data=json.loads((TOKENIZER/'tokenizer.json').read_text())
        self.vocab={v:k for k,v in data['model']['vocab'].items()}
        self.vocab.update({r['id']:r['content'] for r in data['added_tokens']})
        bs=list(range(33,127))+list(range(161,173))+list(range(174,256))
        cs=bs[:];n=0
        for b in range(256):
            if b not in bs:bs.append(b);cs.append(256+n);n+=1
        inverse=dict(zip(map(chr,cs),bs))
        self.pieces={i:bytes(inverse[c] for c in token) for i,token in self.vocab.items()}
    def decode(self,ids):return b''.join(self.pieces[i] for i in ids).decode('utf-8',errors='replace')
    def instruction_distance(self,ids):
        text=self.decode(ids)
        matches=list(re.finditer(r'Give brief reasoning|Briefly explain',text))
        if not matches:return None
        start=len(text[:matches[-1].start()].encode())
        ends=[];total=0
        for i in ids:total+=len(self.pieces[i]);ends.append(total)
        return len(ids)-bisect_right(ends,start)


def native_menu(raw,visible):
    """Reconstruct only public native transitions; do not load/solve an oracle."""
    rules=PrivateInvestigationRules(raw);node=rules.initial()
    for event in visible['public_state']['transcript']:
        if rules.actor(node)!=event['proposer_id']:raise ValueError('Transcript actor mismatch')
        kind=event['action']
        if kind=='INVESTIGATE':action=Investigate(event['player'],event['goal'])
        elif kind=='OFFER':action=decode_action(dict(action='OFFER',**event['offer']))
        elif kind=='PASS':action=decode_action(dict(action='PASS'))
        else:raise ValueError('Unknown transcript action')
        node=rules._apply(node,action)
        if kind=='OFFER':node=rules._apply(node,decode_action(dict(response=event['response'])))
    if visible['pending_offer'] is not None:
        node=rules._apply(node,decode_action(dict(action='OFFER',**visible['pending_offer'])))
    if node.state.public_state()!=visible['public_state']:raise ValueError('Public state mismatch')
    if rules.actor(node)!=visible['player']:raise ValueError('Current actor mismatch')
    menu=[dict(index=i,action=a.to_dict()) for i,a in enumerate(rules.actions(node))]
    if menu!=visible['legal_actions']:raise ValueError('Legal action index mapping mismatch')


def diagnostic_view(call):
    """Expand native vectors for human review; this is NOT a replacement prompt."""
    v=json.loads(call['request']['messages'][-1]['content']);s=v['public_state'];names=Names(v)
    actions=[]
    for item in v['legal_actions']:
        action=item['action'];record=dict(index=item['index'],native=action,
            named_additions=names.action(action,v['player'],s['commitments']))
        if action.get('action')=='OFFER':
            record['resulting_commitments_if_accepted']={
                names.players[v['player']]:[names.actions[v['player']][i] for i,b in enumerate(action['proposer_action']) if b],
                names.players[action['partner_id']]:[names.actions[action['partner_id']][i] for i,b in enumerate(action['partner_action']) if b]}
        actions.append(record)
    return dict(note='Human audit expansion only. No model request uses this view.',
        task_id=call['task_id'],node=call['node'],player_id=v['player'],player_name=names.players[v['player']],
        commitments_native=s['commitments'],commitments_named=names.bindings(s['commitments']),
        own_preferences={names.goals[i]:p for i,p in enumerate(v['own_preferences'])},
        remaining_proposers=s['round_robin'][s['turn_index']:],
        current_decision='Respond to pending offer' if v['pending_offer'] else 'Proposal opportunity',
        actions=actions)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    decoder=OfflineDecoder()
    parents={p['id']:p for p in map(json.loads,Path('new/local_data/strategic_slices_oracle_consistent_candidates_v4/parents.jsonl').read_text().splitlines())}
    seen={};counts=Counter();conflicts=[];representatives={};generation={};template=None
    roots={};last_response_prefixes=Counter()
    with tarfile.open(ROOT/'raw/training-960070.tar.gz.part000','r|gz') as tar:
        for member in tar:
            if member.name.startswith('run/calls/'):
                step=int(Path(member.name).stem.split('-')[-1])
                if step>306:continue
                for line in tar.extractfile(member):
                    c=json.loads(line);counts['calls']+=1
                    key=c['prompt_sha256'];q=c['oracle_step']['Q'];posterior=c['oracle_step']['posterior']
                    if key in seen:
                        old=seen[key]
                        same_shape=len(q)==len(old['Q']) and len(posterior)==len(old['posterior'])
                        if not same_shape or not np.allclose(q,old['Q'],atol=1e-9,rtol=0) or not np.allclose(posterior,old['posterior'],atol=1e-10,rtol=0):
                            conflicts.append(dict(prompt_sha256=key,first=old,other=dict(Q=q,posterior=posterior,task_id=c['task_id'])))
                    else:
                        v=json.loads(c['request']['messages'][-1]['content']);s=v['public_state']
                        native_menu(parents[c['parent_id']]['raw'],v)
                        counts['native_menus_checked']+=1
                        for k in ('n_players','n_actions_per_player','max_changes','forbidden_actions','goals','round_robin'):
                            if v['game'][k]!=s[k]:counts['duplicated_field_mismatch/'+k]+=1
                        prompt=decoder.decode(c['prompt_ids'])
                        if not prompt.endswith('<|im_start|>assistant\n'):counts['unexpected_generation_prefix']+=1
                        if decoder.decode(c['response_ids'])!=c['text']:counts['raw_decode_mismatch']+=1
                        hidden={'teacher','realized_world','world_index','oracle_step','root_Q','private_preferences'}
                        def inspect(value):
                            if isinstance(value,dict):
                                if hidden.intersection(value):raise ValueError('Hidden scoring field in model request')
                                for child in value.values():inspect(child)
                            elif isinstance(value,list):
                                for child in value:inspect(child)
                        inspect(c['request'])
                        seen[key]=dict(Q=q,posterior=posterior,task_id=c['task_id'],
                            prompt_ids_sha256=digest(c['prompt_ids']),
                            brief_instruction_distance_tokens=decoder.instruction_distance(c['prompt_ids']))
                        if c['decision_index']==0:roots[c['task_id']]=seen[key]
                        if step==0 and 'terminal_first' not in representatives:representatives['terminal_first']=c
                        if any(any(row) for row in s['commitments']) and v['pending_offer'] is None and 'terminal_existing_commitments' not in representatives:
                            representatives['terminal_existing_commitments']=c
                        if s['n_players']==2 and v['pending_offer'] and 'terminal_response' not in representatives:representatives['terminal_response']=c
                    if step==0:
                        counts['first_collection_calls']+=1
                        counts['first_collection_with_text']+=bool(c['completion']['raw_message'].get('content'))
                    if step>=250:last_response_prefixes[decoder.decode(c['response_ids'][:1])]+=1
            elif member.name=='run/resolved_config.json':
                d=json.loads(tar.extractfile(member).read());generation['terminal_resolved']=d['actor_infer']['generating_args']
            elif member.name.endswith('chat_template.jinja'):template=tar.extractfile(member).read().decode()
    old_paths={
        'september_D':Path('new/d24_partner32_evidence_20260926/training/decomposed-seed42-881010/calls/step-0.jsonl'),
        'september_SP':Path('new/training_chain_evidence_20260921/new_sp/calls/866677-step-10.jsonl.gz')}
    old_stats={}
    for label,path in old_paths.items():
        blob=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
        rows=[json.loads(l) for l in blob.splitlines()];representatives[label]=rows[0]
        distances=[decoder.instruction_distance(c['prompt_ids']) for c in rows]
        old_stats[label]=dict(path=str(path),file_sha256=hashlib.sha256(blob).hexdigest(),calls=len(rows),
            with_content=sum(bool(c['completion']['raw_message'].get('content')) for c in rows),
            brief_instruction_distance_tokens=dict(min=min(distances),median=float(np.median(distances)),max=max(distances)),
            all_generation_prefix_plain=all(decoder.decode(c['prompt_ids']).endswith('<|im_start|>assistant\n') for c in rows),
            all_response_decodes_match=all(decoder.decode(c['response_ids'])==c['text'] for c in rows))
    for label,c in representatives.items():
        (OUT/(label+'_rendered_prompt.txt')).write_text(decoder.decode(c['prompt_ids']))
        (OUT/(label+'_request.json')).write_text(json.dumps(c['request'],ensure_ascii=False,indent=2)+'\n')
        if label.startswith('terminal'):(OUT/(label+'_expanded_audit.json')).write_text(json.dumps(diagnostic_view(c),ensure_ascii=False,indent=2)+'\n')
    with ZipFile('new/pro_final_training_review_20260922/full_evidence.zip') as archive:
        extracted={}
        for name in ('training/social_mixed/pipeline.py','training/social_mixed/workers.py'):
            text=archive.read(name).decode()
            for n in ast.walk(ast.parse(text)):
                if isinstance(n,ast.FunctionDef) and n.name in ('generate','generate_native'):
                    for c in ast.walk(n):
                        if isinstance(c,ast.Call) and ((isinstance(c.func,ast.Attribute) and c.func.attr=='apply_chat_template') or (isinstance(c.func,ast.Name) and c.func.id=='SamplingParams')):
                            extracted[name]=ast.unparse(c)
        generation['september_22_archived_source_calls']=extracted
    local_template=json.loads((TOKENIZER/'tokenizer_config.json').read_text())['chat_template']
    root_distances=[r['brief_instruction_distance_tokens'] for r in roots.values()]
    summary=dict(counts=dict(counts),unique_visible_contexts=len(seen),unique_training_root_questions=len(roots),
        visible_prompt_Q_or_posterior_conflicts=len(conflicts),conflict_examples=conflicts[:5],
        terminal_root_brief_instruction_distance_tokens=dict(min=min(root_distances),median=float(np.median(root_distances)),max=max(root_distances)),
        plain_assistant_suffix='<|im_start|>assistant\n',september_samples=old_stats,
        checkpoint_template_equals_existing_tokenizer=template==local_template,
        template_sha256=hashlib.sha256(local_template.encode()).hexdigest(),
        tokenizer_sha256={n:hashlib.sha256((TOKENIZER/n).read_bytes()).hexdigest() for n in ('tokenizer.json','tokenizer_config.json','config.json')},
        generation=generation,last_57_updates_first_decoded_token=dict(last_response_prefixes),
        limitations=['No GPU/base-model sampling; presentation changes are not causally isolated.',
            'September D first collection is base; retained September SP sample is a continuation.',
            'Q consistency uses archived values, not a new exhaustive value solve.'])
    (OUT/'audit.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
