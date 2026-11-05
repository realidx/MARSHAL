"""Audit final-response B kernels and inventory existing response contrasts."""
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import numpy as np
from training.b_sft.debug.audit_readable_pretraining import reconstruct, VALUES, independent_backward
from training.b_sft.social_private_teacher import PrivateEpisode, audit_native

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'examples/social_bp/response_only_v1'
OUT=BASE/'kernels_v1/b1'
LABELS=list(VALUES)
NAMES={'strict':'自身收益严格区分','social_tie':'响应利他平局','random_tie':'残余随机响应的似然','net_payoff':'其他目标收益补偿或抵消','uninformative':'响应对被问偏好无区分力','joint':'联合偏好约束或隐藏收益组合'}
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(stable(x).encode()).hexdigest()[:20]
def rational(v):return str(Fraction(float(v)).limit_denominator(1000000))


def audit(t,cache):
    inp=t['input'];raw,own=reconstruct(inp);q=inp['queries'][0];facts=[(f['player'],f['goal'],VALUES[f['preference']]) for f in inp['private_results']]
    key=stable([raw,inp['imposed_setup']])
    if key not in cache:
        root=PrivateEpisode(raw,inp['imposed_setup'],seconds=30,max_nodes=100000)
        cache[key]=(root,audit_native(root.tree),independent_backward(root.tree))
    root,native,independent=cache[key];tree=root.tree;entry=tree.entries[0]
    assert entry.actor==q['player'] and entry.node.pending is not None
    assert all(tree.entries[c].actor is None for c in entry.children)
    assert all(g.get('binary',True) for g in raw['game']['goals'])
    assert tree.certificate['policy_sha256']==t['teacher']['policy_sha256']
    weights=root._weights(inp['observer'],own,facts)
    actions=[a.to_dict()['response'] for a in entry.actions];ia=actions.index('ACCEPT');ir=actions.index('REJECT')
    av=np.array([tree.values[c] for c in entry.children]);prior={};likelihood={};joint={};post={}
    observed=inp['voluntary_history'][0]['response'];observed_index=actions.index(observed)
    for label,v in VALUES.items():
        mask=np.array([w[q['player']][q['goal']]==v for w in tree.worlds]);mass=float(weights[mask].sum());prior[label]=mass
        likelihood[label]={a:float(np.dot(weights[mask],tree.policy[0][j,mask])/mass) if mass else None for j,a in enumerate(actions)}
        joint[label]=float(np.dot(weights[mask],tree.policy[0][observed_index,mask]))
    total=sum(joint.values());assert total>0
    post={v:p/total for v,p in joint.items()};possible=[v for v in LABELS if post[v]>0]
    leaders=[v for v in possible if post[v]>=max(post.values())-1e-9]
    gold=dict(possible_preferences=possible,favored=leaders[0] if len(leaders)==1 else 'undetermined')
    assert gold==t['teacher']['gold']
    np.testing.assert_allclose([post[v] for v in LABELS],[t['teacher']['preference_weights'][v] for v in LABELS],atol=1e-9)
    supported=[v for v in LABELS if prior[v]>0]
    pa=[likelihood[v]['ACCEPT'] for v in supported]
    uniform_likelihood=max(pa)-min(pa)<1e-9
    active=np.flatnonzero(weights>0)
    variable=[g for g in range(len(raw['game']['goals'])) if len({tree.worlds[i][q['player']][g] for i in active})>1]
    delta=av[ia]-av[ir]
    accepted_node=tree.entries[entry.children[ia]].node;rejected_node=tree.entries[entry.children[ir]].node
    done_delta=np.array(accepted_node.state.goal_satisfaction())-np.array(rejected_node.state.goal_satisfaction())
    query_contribution=np.array([w[q['player']][q['goal']]*done_delta[q['goal']] for w in tree.worlds])
    offset=delta[:,q['player']]-query_contribution
    social_tie=False;random_tie=False
    # Use actor information-set expectations, not another player's hidden truth.
    for ids in tree.information_groups[0]:
        ids=np.asarray(ids)
        if not np.any(weights[ids]>0):continue
        actor_weights=tree.world_weights[ids];actor_weights=actor_weights/actor_weights.sum()
        means=np.einsum('awp,w->ap',av[:,ids],actor_weights)
        if abs(means[ia,q['player']]-means[ir,q['player']])<1e-9:
            other=means.sum(axis=1)-means[:,q['player']]
            social_tie |= abs(other[ia]-other[ir])>1e-9
            random_tie |= abs(other[ia]-other[ir])<=1e-9
    tags=[]
    if social_tie:tags.append('social_tie')
    if random_tie:tags.append('random_tie')
    if np.any(np.abs(offset[active])>1e-9):tags.append('net_payoff')
    if len(variable)>1:tags.append('joint')
    if uniform_likelihood:category='uninformative'
    elif len(variable)>1:category='joint'
    elif 'net_payoff' in tags:category='net_payoff'
    elif social_tie:category='social_tie'
    elif random_tie:category='random_tie'
    else:category='strict'
    profile=dict(prior={v:rational(prior[v]) for v in LABELS},
                 response_likelihood={v:{a:None if p is None else rational(p) for a,p in ps.items()} for v,ps in likelihood.items()})
    return dict(id=t['id'],split=t['split'],family=t['family'],source=t['source'],category=category,
        mechanisms=tags,observed_response=observed,gold=gold,posterior={v:rational(post[v]) for v in LABELS},
        **profile,inference_profile_id=digest(profile),
        exact_pre_response_group=digest([raw,inp['imposed_setup'],q,facts]),
        supplied_previous='previous_belief' in inp,independent_backward=independent,native=native,
        note='Inference profile equivalence is not proof of identical causal reasoning or interchangeable structures.')


def main():
    rows={t['id']:t for t in map(json.loads,(BASE/'tasks.jsonl').read_text().splitlines())}
    ids=[r['id'] for r in map(json.loads,(BASE/'kernels_v1/assignments.jsonl').read_text().splitlines()) if r['kernel']=='B1']
    cache={};records=[audit(rows[i],cache) for i in ids];assert len(records)==135
    groups=defaultdict(list)
    for r in records:groups[r['exact_pre_response_group']].append(r)
    contrasts=[]
    for key,group in groups.items():
        assert len({r['split'] for r in group})==1
        feasible=[a for a in ('ACCEPT','REJECT') if any(p[a] is not None and Fraction(p[a])>0 for p in group[0]['response_likelihood'].values())]
        present=sorted({r['observed_response'] for r in group})
        contrasts.append(dict(group=key,split=group[0]['split'],ids=[r['id'] for r in group],
            observed=present,feasible=feasible,missing=sorted(set(feasible)-set(present)),
            complete=set(feasible)<=set(present)))
    # Compact train review representatives only; never select using model scores.
    chosen={}
    for r in sorted(records,key=lambda r:(not r['supplied_previous'],len(stable(rows[r['id']]['input'])),r['id'])):
        if r['split']=='train':chosen.setdefault((r['category'],r['inference_profile_id'],r['observed_response']),r['id'])
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'assignments.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    (OUT/'contrasts.json').write_text(json.dumps(contrasts,ensure_ascii=False,indent=2)+'\n')
    summary=dict(total=135,binary_only=True,categories={k:dict(name=NAMES[k],counts=dict(Counter(r['split'] for r in records if r['category']==k))) for k in NAMES},
        pre_response_groups=len(groups),complete_response_groups=sum(c['complete'] for c in contrasts),
        incomplete_response_groups=sum(not c['complete'] for c in contrasts),inference_profiles=len({r['inference_profile_id'] for r in records}),
        train_review_representatives=list(chosen.values()),source_sha256=hashlib.sha256((BASE/'tasks.jsonl').read_bytes()).hexdigest(),
        independent_backward=sum(r['independent_backward'] for r in records),
        scope='No new tasks, relabelling, split changes, training quotas or model calls. Complementary observed responses are existing branches, not manipulated player preferences.')
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    lines=['# B1：binary响应逆推的内核与对照','',
        '统一最短链：接受/拒绝分别完成哪些目标 → 各候选偏好的自身净收益 → 自身平局时考虑他人收益 → 得到响应似然 → 更新possible与favored。数字表只用于研究者审核，不写进模型题面。','',
        '| 内核分支 | 必须辨认的差别 |','| --- | --- |',
        '| 自身收益严格区分 | 候选偏好使响应的自身收益正负不同，行为直接排除候选 |',
        '| 响应利他平局 | neutral自身收益为0，但帮助/损害他人改变接受还是拒绝 |',
        '| 随机响应似然 | 双方收益都并列时随机；“仍可能”不等于“同样可能” |',
        '| 净收益补偿或抵消 | 不能只看被问目标；其他目标收益可使avoid仍接受 |',
        '| 无区分力的响应 | 所有候选下响应似然相同，应保留先验；不一定是全集 |',
        '| 联合偏好约束/隐藏收益组合 | 先在联合情形上推断，再边缘化；不能把各goal看作独立 |','',
        '前五项先形成短链，联合情形作为组合层。分类可重叠：净收益例也可能包含随机平局。主归属用于整理，不意味只需一种运算。','',
        '## 五个核心真值表','',
        '下面q表示被问目标偏好，Δ是ACCEPT相对REJECT的收益变化。每行保留全部其他条件后列出响应策略；先验由合法偏好生成规则决定。','',
        r'| 条件 | P(ACCEPT\|want) | P(ACCEPT\|neutral) | P(ACCEPT\|avoid) | 接受后的标签（均匀三值先验时） |','| --- | ---: | ---: | ---: | --- |',
        '| Δ自身=q，Δ他人=+1 | 1 | 1 | 0 | want/neutral，undetermined |',
        '| Δ自身=q，Δ他人=-1 | 1 | 0 | 0 | want |',
        '| Δ自身=q，Δ他人=0 | 1 | 1/2 | 0 | want/neutral，favored=want |',
        '| Δ自身=q+1，Δ他人=0 | 1 | 1 | 1/2 | 全集，undetermined；posterior为2/5、2/5、1/5 |',
        '| Δ自身=1，与q无关 | 1 | 1 | 1 | 保留先验 |','',
        '这些关系均能在现有train证书中找到实例。最后一行若先验只有want/avoid，就只保留二值；不是固定输出全集。严格二值样例的neutral由共同知识先验排除，不应杜撰为行为排除。','',
        '## 已有题目的映射','', '| 分支 | Train | Validation | Test |','| --- | ---: | ---: | ---: |']
    for k,c in summary['categories'].items():
        n=c['counts'];lines.append(f"| {c['name']} | {n.get('train',0)} | {n.get('validation',0)} | {n.get('test',0)} |")
    lines+=['',f"135题对应{len(groups)}个完全相同的响应前状态/查询/私有事实组，其中{summary['complete_response_groups']}组覆盖全部有正概率的响应，{summary['incomplete_response_groups']}组缺少可行响应分支。详见contrasts.json。",
        f"归并得到{summary['inference_profiles']}种prior＋两种响应似然分布。这个数字是推断分布的去重，不是已经证明只有这么多因果内核。",
        '', '## 整理后的保留原则','',
        '- 同一场景的formation与提供旧belief的update仅算呈现/支架变体，不额外占一个内核配额。',
        '- ACCEPT与REJECT是同一响应前场景的互补观察题；跨利他/冲突条件还需要核对除他人收益外的结构与先验是否相同，不能仅凭标签不同称为单变量对照。',
        '- 无信息且保留全集，必须与有信息但仍保留全集、以及应排除候选的题配套。净收益接受题本身不能检验“没调查就全集”的解释。',
        '- 先验约束、响应随机和联合收益分别解释支持变化，不把所有favored题合并成“选最多的”。',
        '- 名称变化可后做；增加player/goal/commitment须重验上述收益与似然关系。linear当前未覆盖，不算binary同内核的自动改名变体。',
        '', '本轮仅重算、归档和列出已有互补分支；未新增题、删题、设置配额或调用模型。train代表ID保存在summary.json，不能直接当作最终训练集。']
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='train_review_representatives'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
