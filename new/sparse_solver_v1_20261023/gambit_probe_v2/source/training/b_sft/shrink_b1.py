"""Select a compact binary B1 train core; preserve held-out and source banks."""
from collections import Counter,defaultdict
import hashlib,json
from pathlib import Path
from training.b_sft.build_b_response_bridges import verify_task
from training.b_sft.social_named_probe import request,present
from training.b_sft.b_chronological_prompt import render
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'examples/social_bp/response_only_v1'
OUT=BASE/'kernels_v1/b1/core_v1'
# Select reviewed causal mechanisms, not model successes or task counts.
SPECS=[('strict','isolated_response','target'),('helpful_tie','altruistic','target'),
       ('harmful_tie','conflict','target'),('random_tie','favored','target'),
       ('net_compensation','net_payoff','target'),
       ('joint_prior','favored_disappears','joint_constraint'),
       ('joint_payoff','favored_appears','target'),
       ('no_information_binary','isolated_response','unrelated'),
       ('no_information_full','altruistic','unrelated')]


def main():
    payload=(BASE/'tasks.jsonl').read_bytes();bank={t['id']:t for t in map(json.loads,payload.splitlines())}
    audit={r['id']:r for r in map(json.loads,(BASE/'kernels_v1/b1/assignments.jsonl').read_text().splitlines())}
    selected=[];groups=[];checks=[];requests=[];cards=[]
    for name,lesson,relation in SPECS:
        pool=[t for t in bank.values() if t['id'] in audit and t['split']=='train'
              and t.get('b_lesson')==lesson and t.get('evidence_relation')==relation
              and 'previous_belief' in t['input']]
        pool.sort(key=lambda t:t['input']['voluntary_history'][0]['response'])
        expected={'ACCEPT'} if relation=='unrelated' else {'ACCEPT','REJECT'}
        assert len(pool)==len(expected) and {t['input']['voluntary_history'][0]['response'] for t in pool}==expected,name
        assert len({audit[t['id']]['exact_pre_response_group'] for t in pool})==1
        possible={action for probs in audit[pool[0]['id']]['response_likelihood'].values()
                  for action,p in probs.items() if p is not None and float(__import__('fractions').Fraction(p))>0}
        assert possible==expected,(name,possible)
        groups.append(dict(name=name,ids=[t['id'] for t in pool],feasible_responses=sorted(possible),
                           complete=True,group_sampling_note='Pick mechanism group before variant; no sampling weights wired yet.'))
        for t in pool:
            checks.append(verify_task(t))
            req=request(t,'action_tools',t.get('name_variant',0));req['messages'][1]['content']=render(present(t,t.get('name_variant',0)))
            assert req['max_tokens']==1024
            requests.append(dict(task_id=t['id'],condition='chronological_tables',request=req))
            selected.append(t)
            cards += [f"## {name} / {t['input']['voluntary_history'][0]['response']}",'',f"ID: {t['id']}",'',
                      '### 模型题面','',req['messages'][1]['content'],'','### 审核标签（不发送给模型）','',
                      json.dumps(dict(gold=t['teacher']['gold'],prior=audit[t['id']]['prior'],
                                      response_likelihood=audit[t['id']]['response_likelihood'],posterior=audit[t['id']]['posterior']),ensure_ascii=False),'']
    assert len(selected)==len({t['id'] for t in selected})==16
    assert {audit[t['id']]['category'] for t in selected}=={'strict','social_tie','random_tie','net_payoff','joint','uninformative'}
    selected_ids={t['id'] for t in selected}
    reserve=[t for t in bank.values() if t['id'] in audit and t['split']=='train' and t['id'] not in selected_ids]
    held=[t for t in bank.values() if t['id'] in audit and t['split']!='train']
    assert len(reserve)==88 and Counter(t['split'] for t in held)=={'validation':15,'test':16}
    assert not {t['family'] for t in selected}&{t['family'] for t in held}
    # Explicit downstream candidate bank: only B1 train is reduced. Nothing is enabled for training.
    candidate=[t for t in bank.values() if t['id'] not in audit or t['split']!='train' or t['id'] in selected_ids]
    assert len(candidate)==315
    OUT.mkdir(parents=True,exist_ok=True)
    files={}
    def write(name,rows):
        data=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows).encode();(OUT/name).write_bytes(data)
        files[name]=dict(count=len(rows),sha256=hashlib.sha256(data).hexdigest())
    write('train_tasks.jsonl',selected);write('train_requests.jsonl',requests)
    write('reserve_tasks.jsonl',reserve);write('heldout_tasks.jsonl',held)
    write('bp_candidate_tasks.jsonl',candidate)
    decisions=[dict(id=t['id'],split=t['split'],role='core_train' if t['id'] in selected_ids else 'heldout_unchanged' if t['split']!='train' else 'reserve_train',
                    reason='One supplied-prior instance per feasible response in selected mechanism' if t['id'] in selected_ids else 'Preserve original held-out split' if t['split']!='train' else 'Not needed in compact core; retained as alternate structure or presentation, not claimed semantically identical') for t in bank.values() if t['id'] in audit]
    write('selection.jsonl',decisions)
    manifest=dict(version='b1-binary-core-v1',source_sha256=hashlib.sha256(payload).hexdigest(),
                  original_b1_train=104,core_train=16,reserve_train=88,validation_unchanged=15,test_unchanged=16,
                  groups=groups,checks=checks,files=files,merged=False,training_ready=False,model_tested=False,
                  note='Review selection. Preserve all source fields/labels/splits. Core requests use reviewed chronological renderer. No reward-based selection, linear expansion, or sampling weight change.')
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (OUT/'cards.md').write_text('# 16道B1核心题：完整题面及审核标签\n\n'+'\n'.join(cards))
    lines=['# B1已实际缩减：104道train → 16道核心＋88道备用','',
           '原始403题不改写。此目录提供实际独立核心文件与备用文件；15道B1 validation及16道test完整保留。全部仍为binary。未调用模型、未启用训练。','',
           '| 对照组 | 题数 | 作用 |','| --- | ---: | --- |',
           '| 自身收益严格区分 | 2 | 接受与拒绝分别支持want/avoid；neutral由合法先验排除 |',
           '| 自身平局，帮助他人 | 2 | 接受保留want/neutral；拒绝只保留avoid |',
           '| 自身平局，损害他人 | 2 | 接受只保留want；拒绝保留neutral/avoid |',
           '| 双方平局、随机响应 | 2 | 候选仍可能但支持不等，检查favored |',
           '| 净收益补偿 | 2 | 接受也可能是avoid；拒绝需考虑净收益 |',
           '| 联合先验约束 | 2 | 无关目标的响应通过联合约束改变被问偏好 |',
           '| 联合隐藏收益 | 2 | 在联合情形上计算收益后边缘化，不能独立逐goal判断 |',
           '| 无信息：二值先验 | 1 | 保留want/avoid，而不是输出全集 |',
           '| 无信息：三值先验 | 1 | 合法保留全集，与净收益接受的全集作区分 |','',
           '共9组、16题。前7组均完整保留ACCEPT/REJECT；后2组REJECT在所有合法候选下概率为0，不能伪造拒绝题以凑平衡。', '',
           '这些是现有短教学场景的紧凑核心，不宣称已通过逐元素删除证明数学意义上的最小。六类分支覆盖已检查；联合推断组应视为组合层，不能与严格二值题视作同等难度。','',
           '## 去掉了什么','',
           '不再给同一场景“有旧belief/无旧belief”两种写法各占一个核心位置；本版统一选提供正确旧belief的短链版本。其余场景和呈现进入备用库，不删除，也不声称88题全部语义等价。', '',
           '未为了达到原先估计的20–30题而补重复题。16题已覆盖上述对照，后续若发现明确缺口再补。','',
           '## 文件','',
           '- train_tasks.jsonl：16道真实任务，原ID、标签和split。',
           '- train_requests.jsonl：16道时序表格呈现，1024预算、原生工具；收益表和答案不进入模型题面。',
           '- reserve_tasks.jsonl：88道备用train。',
           '- heldout_tasks.jsonl：原15 validation＋16 test。',
           '- bp_candidate_tasks.jsonl：只应用这次B1缩减后的315题候选库，其他B/P题完整保留，包括暂置P。不是已就绪训练包。',
           '- selection.jsonl：135题逐题保留/备用决定。',
           '- cards.md：16题完整题面与分开的审核标签。','',
           '## 验证与尚未执行','',
           '16题重新通过solver、独立响应收益/似然和标签核验；9组可行响应分支完整，六种分支全部覆盖；训练与heldout family无交叉。原403题hash保持不变。没有改训练入口、采样配额或reward。', '',
           '核心集不意味着均匀按16题抽样就是最终均衡策略。下一步应评审9组的关系和组合层占比；B2/B3及P尚未精简，不能声称整个B/P题库已经完成压缩。']
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')
    assert hashlib.sha256((BASE/'tasks.jsonl').read_bytes()).hexdigest()==manifest['source_sha256']
    print(json.dumps({k:manifest[k] for k in ('original_b1_train','core_train','reserve_train','validation_unchanged','test_unchanged')},ensure_ascii=False))

if __name__=='__main__':main()
