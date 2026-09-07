import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from benac_p.endgame_diagnose import Suite, preflight, preflight_policy_resume_allowed


def control_suite():
    suite=Suite([])
    suite.tasks=[dict(id='root/belief',kind='semantic_belief',parent=None,
                      belief_options=['want','neutral','avoid'],
                      input=dict(initially_possible_preferences=['want','neutral','avoid'],history=[]))]
    return suite


def test_protocol_gate_keeps_semantic_failure_without_requery(tmp_path,monkeypatch):
    calls=[]
    def generate(client,task,payload,*args):
        calls.append(task['id'])
        values=['want','neutral','avoid'] if task['id']=='preflight/known_0' else payload['initially_possible_preferences']
        return dict(status='ok',answer=dict(possible_preferences=values))
    monkeypatch.setattr('benac_p.endgame_diagnose.generate',generate)
    args=SimpleNamespace(oracle_check=False,finalization_tokens=128,preflight_policy='strict')
    assert not preflight(control_suite(),object(),tmp_path,args)
    before=(tmp_path/'belief_preflight_answers.json').read_text()
    args.preflight_policy='protocol'
    assert preflight(control_suite(),object(),tmp_path,args)
    assert len(calls)==4
    assert (tmp_path/'belief_preflight_answers.json').read_text()==before
    summary=json.loads((tmp_path/'belief_preflight_summary.json').read_text())
    assert summary['correct']==3 and not summary['semantic_passed'] and not summary['passed']
    assert summary['protocol_passed'] and summary['gate_passed']


@pytest.mark.parametrize('failure',['transport_error','invalid'])
def test_protocol_gate_still_blocks_nonsemantic_failures(tmp_path,monkeypatch,failure):
    def generate(client,task,payload,*args):
        if task['id']=='preflight/known_0':
            if failure=='transport_error':return dict(status=failure,error='service unavailable')
            return dict(status='ok',answer=dict(possible_preferences=['want','want']))
        return dict(status='ok',answer=dict(possible_preferences=payload['initially_possible_preferences']))
    monkeypatch.setattr('benac_p.endgame_diagnose.generate',generate)
    args=SimpleNamespace(oracle_check=False,finalization_tokens=128,preflight_policy='protocol')
    assert not preflight(control_suite(),object(),tmp_path,args)
    summary=json.loads((tmp_path/'belief_preflight_summary.json').read_text())
    assert not summary['protocol_passed'] and not summary['gate_passed']


def test_gate_migration_cannot_mix_prompts_or_formal_answers(tmp_path):
    old=dict(model='fixed',task_hash='same',max_tokens=1024)
    new=dict(old,preflight_policy='protocol')
    assert not preflight_policy_resume_allowed(old,new,tmp_path,True)
    (tmp_path/'belief_preflight_answers.json').write_text('{}')
    assert preflight_policy_resume_allowed(old,new,tmp_path,True)
    assert not preflight_policy_resume_allowed(old,new,tmp_path,False)
    assert not preflight_policy_resume_allowed(old,dict(new,task_hash='different'),tmp_path,True)
    assert not preflight_policy_resume_allowed(old,dict(new,max_tokens=2048),tmp_path,True)
    (tmp_path/'answers.json').write_text('{}')
    assert not preflight_policy_resume_allowed(old,new,tmp_path,True)


def test_resume_stopped_run_reports_failed_control_and_completes(tmp_path):
    from benac_p.endgame_diagnose import main
    fixtures=Path(__file__).resolve().parents[3]/'examples/benac_p/fixtures/native_smoke.json'
    out=tmp_path/'run'
    args=['--fixtures',str(fixtures),'--output-dir',str(out),'--oracle-check']
    main(args)
    # Recreate a preflight-only stop with the reported valid-but-wrong answer.
    (out/'answers.json').unlink()
    path=out/'belief_preflight_answers.json'
    records=json.loads(path.read_text())
    records['preflight/known_0']['answer']['possible_preferences']=['want','neutral','avoid']
    path.write_text(json.dumps(records))
    before=path.read_text()
    with pytest.raises(SystemExit):main(args+['--resume'])
    main(args+['--resume','--preflight-policy','protocol'])
    assert path.read_text()==before
    summary=json.loads((out/'summary.json').read_text())
    assert summary['preflight']['correct']==3
    assert summary['coverage']['valid']==summary['coverage']['requested']
    assert (out/'preflight_policy_change.json').exists()
