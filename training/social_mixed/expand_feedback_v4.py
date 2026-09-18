"""Mine decision-relevant on-policy OFFER feedback from training/dev sources."""
from copy import copy
import json
from training.social_mixed.prepare_reasoning_v4 import *


def main():
    packs={s:read(OUT/('bp_'+s+'.jsonl')) for s in ('train','validation')};log=[]
    for split,rows in packs.items():
        rows[:]=[t for t in rows if not t.get('offer_feedback_source')]
        seen=set();new=[]
        bases=[t for t in read(SOURCE/('bp_'+split+'.jsonl')) if t['kernel']=='P4' and t['background_profile']=='balanced' and not t['input']['private_results']]
        for base in sorted(bases,key=lambda t:t['id']):
            key=(geometry_id(base['input']['game']),base['completion_mode'])
            if key in seen:continue
            seen.add(key)
            try:
                raw,own=reconstruct(base['input']);raw['background_prior']=base['input']['background_prior'];setup=base['input']['imposed_setup']
                root,_=root_episode(stable([raw,setup]));found=[]
                for a in root.tree.entries[0].actions:
                    action=a.to_dict()
                    if action.get('action')!='OFFER':continue
                    e=copy(root);e.weights=root.weights.copy()
                    try:e.observe(action);e._weights(0,own,[])
                    except ValueError:continue
                    frontier=[(e,[action])]
                    for depth in range(4):
                        nxt=[]
                        for node,events in frontier:
                            entry=node.tree.entries[node.index]
                            if entry.actor is None:continue
                            if entry.actor==0:
                                p=task_at(base,node,setup,events,[],'P')
                                if p and p['teacher']['history_changes_acceptable']:
                                    p['offer_feedback_source']=base['id'];found.append(p)
                                continue
                            for response in entry.actions:
                                if response.to_dict().get('action')=='INVESTIGATE':continue
                                child=copy(node)
                                try:child.observe(response.to_dict());child._weights(0,own,[])
                                except ValueError:continue
                                nxt.append((child,events+[response.to_dict()]))
                        frontier=nxt
                # Bounded by distinct actual acceptable sets, not by model outcomes.
                signatures=set()
                for p in sorted(found,key=lambda p:p['id']):
                    if p['answer_signature'] in signatures:continue
                    signatures.add(p['answer_signature']);new.append(p)
                    if len(signatures)>=4:break
                event=dict(id=base['id'],split=split,found=len(found),retained=len(signatures),status='ok')
            except Exception as exc:event=dict(id=base['id'],split=split,status='unavailable',error=repr(exc))
            print(json.dumps(event),flush=True);log.append(event);root_episode.cache_clear()
        rows.extend(new)
        (OUT/('bp_'+split+'.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in rows))
    (OUT/'offer_feedback_audit.json').write_text(json.dumps(log,indent=2))

if __name__=='__main__':main()
