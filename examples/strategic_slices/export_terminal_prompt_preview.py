"""Export exact new named prompts for archived public states; no model calls."""
import json
from pathlib import Path
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.social_terminal_teacher import Investigate
from training.strategic_slices.named_prompt import request,VERSION
from training.strategic_slices.common import seed_for
from benac_p.endgame_diagnose import decode_action

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/strategic_slices/versions/terminal_v8_readable_20261018'


def rebuild(raw,v):
    rules=PrivateInvestigationRules(raw);rules.background_prior=v['background_prior'];node=rules.initial()
    for e in v['public_state']['transcript']:
        if e['action']=='INVESTIGATE':a=Investigate(e['player'],e['goal'])
        else:a=decode_action(dict(action=e['action'],**(e['offer'] if e['action']=='OFFER' else {})))
        node=rules._apply(node,a)
        if e['action']=='OFFER':node=rules._apply(node,decode_action(dict(response=e['response'])))
    if v['pending_offer']:node=rules._apply(node,decode_action(dict(action='OFFER',**v['pending_offer'])))
    results=tuple((r['player'],r['goal'],{'want':1,'neutral':0,'avoid':-1}[r['preference']]) for r in v['private_results'])
    node.state.private_results=tuple(results if p==v['player'] else () for p in range(rules.spec.n_players))
    own=tuple({'want':1,'neutral':0,'avoid':-1}[p] for p in v['own_preferences'])
    world=next(w for w in rules.worlds if w[v['player']]==own and all(w[p][g]==a for p,g,a in results))
    return rules,node,world


def main():
    if (OUT/'SNAPSHOT.json').exists():raise ValueError('Frozen preview cannot be overwritten; use a new version directory')
    OUT.mkdir(parents=True,exist_ok=True)
    parents={r['id']:r for r in map(json.loads,(ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4/parents.jsonl').read_text().splitlines())}
    cases=OUT/'input_fixtures.json'
    if cases.exists():fixtures=json.loads(cases.read_text())
    else:
        source=ROOT/'new/terminal_node_v6_training_960070/review_20261017/prompt_interface'
        fixtures=[]
        for label in ('terminal_first','terminal_existing_commitments','terminal_response'):
            old=json.loads((source/(label+'_request.json')).read_text())
            audit=json.loads((source/(label+'_expanded_audit.json')).read_text())
            candidates=[r for r in map(json.loads,(ROOT/'new/local_data/strategic_slices_terminal_selected_v4/candidates.jsonl').read_text().splitlines()) if r['id']==audit['task_id']]
            fixtures.append(dict(label=label,raw=parents[candidates[0]['parent_id']]['raw'],visible=json.loads(old['messages'][1]['content'])))
        cases.write_text(json.dumps(fixtures,ensure_ascii=False,indent=2)+'\n')
    text=['# 当前完整模型输入预览：'+VERSION,'',
        '以下直接由正式request函数生成；包括完整system、user和tools，无省略。这里只导出文本，没有调用模型。',
        'System沿用9月原文；tools与v7完全相同。计分规则集中在GAME RULES，目标表紧随其后。',
        '公开与私有事实分表，不再标注来源或谁由调查知道什么；自己的调查答案保留。',
        '所有当前父游戏已核验可用公开固定偏好+其他偏好独立抽样表达，不再枚举support。',
        '实际窗口与终局目标保持原定义，改用普通语言描述；没有调用模型或改变Oracle。','']
    for i,case in enumerate(fixtures):
        v=case['visible'];rules,node,world=rebuild(case['raw'],v)
        req=request(rules,node,world,seed_for(42,'prompt-preview',i),remaining_decisions=v['evaluation_window']['remaining_controlled_decisions'])
        req.update(max_tokens=1024,top_p=1.,top_k=-1,repetition_penalty=1.,tool_choice='auto',parallel_tool_calls=False)
        (OUT/(case['label']+'.json')).write_text(json.dumps(req,ensure_ascii=False,indent=2)+'\n')
        text+=['## '+case['label'],'','### System','','```text',req['messages'][0]['content'],'```',
            '','### User','','```text',req['messages'][1]['content'],'```',
            '','### Tools','','```json',json.dumps(req['tools'],ensure_ascii=False,indent=2),'```','']
    (OUT/'PROMPT_PREVIEW.md').write_text('\n'.join(text)+'\n')
    print(OUT/'PROMPT_PREVIEW.md')


if __name__=='__main__':main()
