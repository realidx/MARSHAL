import json
from training.b_sft.train_probe import select_probe
from training.b_sft.test_semantic import example


def test_probe_keeps_pairs_and_covers_answer_sizes():
    rows, pairs = [], []
    for n in (3, 4):
        for size in (1, 2, 3):
            source = f'{n}-{size}'
            for i in (0, 1):
                r = example(f'{source}-{i}', source=source, values=('want', 'neutral', 'avoid')[:size])
                payload = json.loads(r['messages'][1]['content'])
                payload['game'] = {'n_players': n}
                r['messages'][1]['content'] = json.dumps(payload)
                rows.append(r)
            pairs.append(dict(source_id=source, before=f'{source}-0', after=f'{source}-1'))
    selected, selected_pairs = select_probe(rows, pairs, max_pairs=6)
    assert len(selected) == 12 and len(selected_pairs) == 6
    assert {r['source_id'] for r in selected} == {r['source_id'] for r in rows}
    assert select_probe(rows, list(reversed(pairs)), max_pairs=6) == (selected, selected_pairs)


def test_matched_probe_preserves_strata_and_rejects_leakage():
    import pytest
    from training.b_sft.matched_probe import match_pairs, signature
    def rows(source):
        result=[]
        for i in range(2):
            r=example(source+str(i), source=source, values=('neutral',))
            d=json.loads(r['messages'][1]['content'])
            d['game']={'n_players':3,'goals':[{'binary':True}]}
            d['history']=[] if i==0 else [{'player_id':0,'action':{'action':'PASS'}}]
            r['messages'][1]['content']=json.dumps(d)
            result.append(r)
        return result
    a,b=rows('a'),rows('b')
    pa=[dict(source_id='a',before='a0',after='a1')]
    pb=[dict(source_id='b',before='b0',after='b1')]
    selected,pairs,mapping=match_pairs(a,pa,b,pb)
    assert selected==b and pairs==pb and len(mapping)==1
    assert signature(pa[0],{r['id']:r for r in a})==signature(pb[0],{r['id']:r for r in b})
    with pytest.raises(ValueError, match='overlap'):
        match_pairs(a,pa,a,pa)
    with pytest.raises(ValueError, match='No disjoint'):
        match_pairs(a,pa,b,[])
