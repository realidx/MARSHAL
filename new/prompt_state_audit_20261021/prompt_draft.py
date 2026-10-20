"""Review-only state-specific request builder. NOT connected to training.

Single handwritten user message + unchanged named tools. The draft explicitly
states the response social-tie rule that the current own-only scorer omits.
"""
import json
from pathlib import Path
from training.strategic_slices.named_prompt import (
    visible,game_rules,goal_requirements,preference_information,background_preferences,public_history,
    check_independent_preferences)
from training.social_mixed.frozen.bp_display import action_tools
from training.strategic_slices.common import file_hash,seed_for
from examples.strategic_slices.export_terminal_prompt_preview import rebuild

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/strategic_slices/versions/terminal_v9_state_draft_20261021'
VERSION='terminal-state-prompt-draft-v9'


def request(rules,node,world,seed,temperature=1.):
    check_independent_preferences(rules)
    obs,v,_=visible(rules,node,world[rules.actor(node)])
    rules_text=game_rules(obs['game'])+[
        '6. Response tie-breaking (for EVERY player): When responding to an offer, '
        'first maximize your own expected final score using the information available to you. '
        'If ACCEPT and REJECT give you the same expected final score, choose the response '
        'with the higher SUM of expected final scores for all other players. '
        'If both your score and the other-player sum are tied, either response is acceptable. '
        'Do not use other-player scores to break your own-score ties at proposal decisions.']
    goal_lines=goal_requirements(v)
    goal_lines=goal_lines[:next(i for i,line in enumerate(goal_lines) if line.startswith('Cells list'))]
    goal_lines+=['Each cell lists that player\'s commitments required for the goal; none means no requirement from that player.']
    lines=['YOUR TASK',f'You are {v["you"]}. Choose your next game action.',
        '',*rules_text,'',*goal_lines,'',*preference_information(v),
        '',*background_preferences(rules),'',*public_history(v),
        '', 'ALREADY ACCEPTED COMMITMENTS',
        'These commitments from earlier accepted offers are already binding and remain in force.',
        '| Player | Binding commitments |','| --- | --- |']
    lines += [f'| {p} | '+(', '.join(a) or 'none')+' |' for p,a in v['binding_commitments'].items()]
    lines += ['', 'PUBLIC TURN STATUS',
        'Remaining proposal order (including the current opportunity and its response): '+
        ' -> '.join(v['remaining_proposers'])+'.',
        'Investigations remaining: '+'; '.join(f'{p}={n}' for p,n in v['investigation_uses_remaining'].items())+'.',
        '', 'CURRENT DECISION']
    if v.get('pending_offer'):
        offer=v['pending_offer']
        lines += ['You are RESPONDING to an offer.',
            f'{offer["proposer"]} offers to {offer["partner"]}: '+
            f'{offer["proposer"]} would add '+(', '.join(offer['self_commitments']) or 'nothing')+'; '+
            f'{offer["partner"]} would add '+(', '.join(offer['partner_commitments']) or 'nothing')+'.',
            'These proposed additions are NOT yet binding. Choose ACCEPT or REJECT.',
            'Apply the response tie-breaking rule in GAME RULES when your own expected final scores are equal.']
    else:
        legal=list(dict.fromkeys(a['action'] for a in v['legal_actions']))
        lines += ['You are taking your PROPOSAL opportunity. There is no pending offer.',
            'Choose one of the currently legal actions: '+', '.join(legal)+'.']
    lines += ['', 'RESPONSE INSTRUCTIONS',
        'Briefly explain your decision using the visible information, then make exactly one '
        'registered game-action tool call. Keep the explanation outside the tool arguments. '
        'Use a legal argument combination from the registered tools.']
    return dict(messages=[dict(role='user',content='\n'.join(lines))],tools=action_tools(v),seed=seed,temperature=temperature)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'SNAPSHOT.json').exists():raise ValueError('Closed draft cannot be overwritten; use a new version')
    fixture=ROOT/'examples/strategic_slices/versions/terminal_v8_readable_20261018/input_fixtures.json'
    cases=json.loads(fixture.read_text())
    labels=('terminal_first','terminal_existing_commitments','terminal_response','terminal_private_new_answer')
    text=['# V9状态化题面草案：仅供审阅，未接入训练','',
        '**当前active仍为v8。此草案已写入response tie规则，但现有训练/评分尚未实现同一完整目标，不能作为训练就绪版本。**','',
        '人工内容为一个完整user消息；tools保持原接口。原生Qwen模板仍会自动生成工具system头。',
        '共享信息在proposal和response状态均完整给出；只切换CURRENT DECISION及合法tools。',
        '未包含窗口/参考策略接管等训练内部说明；此项只是输入层草案，尚未改采样/评分合同。','']
    files={}
    for i,label in enumerate(labels):
        case=next(c for c in cases if c['label']==label);rules,node,world=rebuild(case['raw'],case['visible'])
        req=request(rules,node,world,seed_for(42,'state-prompt-draft',i))
        target=OUT/(label+'.json');target.write_text(json.dumps(req,ensure_ascii=False,indent=2)+'\n');files[target.name]=file_hash(target)
        text+=['## '+label,'','### System','','没有手写system消息。工具说明由原生chat template生成。',
            '', '### User','','```text',req['messages'][0]['content'],'```','',
            '### Tools','','```json',json.dumps(req['tools'],ensure_ascii=False,indent=2),'```','']
    preview=OUT/'PROMPT_PREVIEW.md';preview.write_text('\n'.join(text)+'\n');files[preview.name]=file_hash(preview)
    record=dict(version=VERSION,record_kind='review-draft-not-a-training-version',status='NOT_TRAINING_READY_SCORE_MISMATCH',
        parent='terminal-node-regret-grpo-readable-v8',created_on='2026-10-21',
        production_code_changed=False,training_or_evaluation_submitted=False,
        source='new/prompt_state_audit_20261021/prompt_draft.py',source_sha256=file_hash(Path(__file__)),
        input_fixtures=str(fixture.relative_to(ROOT)),input_fixtures_sha256=file_hash(fixture),files=files,
        planned_changes=['Single handwritten user message + unchanged tools','Shared full disclosure + state-specific decision block',
            'Short goal-table explanation','Remove exercise-window text','Restore response-only own-first/other-sum tie rule'],
        unresolved=['Current own-only Q rewards/strict correctness omit response social tie',
            'Vector/lexicographic target and information-value contract require explicit alignment before activation'],
        data_and_hyperparameters='No changes; actual active configuration remains the registered v8 snapshot')
    (OUT/'SNAPSHOT.json').write_text(json.dumps(record,indent=2)+'\n')
    registry=OUT.parent/'index.json';index=json.loads(registry.read_text());assert index['active']=='terminal-node-regret-grpo-readable-v8'
    index.setdefault('drafts',{})[VERSION]=str((OUT/'SNAPSHOT.json').relative_to(OUT.parent))
    registry.write_text(json.dumps(index,indent=2)+'\n')
    print(preview)


if __name__=='__main__':main()
