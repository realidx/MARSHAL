import json
import random
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from examples.final_evaluation.c2c_local import ROOT,Transport,development_plan,load_routes


def test_four_seats_keep_same_environment_seeds():
    games=development_plan(100,2)['games']
    assert len(games)==8
    for board in (100,101):
        group=[g for g in games if g['board_seed']==board]
        assert len({g['shuffle_seed'] for g in group})==1
        assert {g['focal_seat'] for g in group}==set(range(4))
        for g in group:
            models=g['model_assignment'].copy();random.Random(g['shuffle_seed']).shuffle(models)
            assert models[g['focal_seat']]=='focal'
            assert models.count('q0')==3


def test_default_routing_is_all_local_and_rejects_unintended_remote(tmp_path):
    config=load_routes(ROOT/'examples/final_evaluation/c2c_local.json')
    config['endpoints']['q0']['base_url']='https://example.com/v1'
    path=tmp_path/'routes.json';path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='local_only'):load_routes(path)
    config['local_only']=False;path.write_text(json.dumps(config))
    assert load_routes(path)['endpoints']['q0']['base_url'].startswith('https:')


def test_auxiliary_summary_uses_local_q0_without_credentials_in_log(tmp_path):
    config=load_routes(ROOT/'examples/final_evaluation/c2c_local.json')
    transport=Transport(config,tmp_path/'calls.jsonl',10,'upstream-summary-model')
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps(dict(choices=[dict(message=dict(content='{}'),finish_reason='stop')])).encode()
    with patch('examples.final_evaluation.c2c_local.urlopen',return_value=Response()) as opener:
        assert transport('upstream-summary-model',[dict(role='user',content='private transcript')],response_format={'type':'json_object'})=='{}'
    request=opener.call_args.args[0]
    assert request.full_url=='http://127.0.0.1:18096/v1/chat/completions'
    assert json.loads(request.data)['model']=='social-q0'
    record=json.loads((tmp_path/'calls.jsonl').read_text())
    assert record['alias']=='summary' and record['status']=='ok'
    assert 'Authorization' not in record


def test_native_games_preserve_world_when_focal_seat_changes(tmp_path):
    sys.path.insert(0,str(ROOT/'third_party/cooperate-to-compete'))
    from c2c.experiments.run_batch import create_game
    games=development_plan(100,1)['games'];states=[]
    for g in games:
        game=create_game(g['game_id'],g['board_seed'],g['shuffle_seed'],str(tmp_path/g['game_id']),g['model_assignment'],comparison_target_index=g['focal_seat'])
        assert len(game.participants)==4
        states.append(([(a.display_id,a._win_condition) for a in game.participants],game.board.to_json()))
    assert all(s==states[0] for s in states)


def test_parallel_native_games_have_independent_transport_logs(tmp_path):
    from concurrent.futures import ProcessPoolExecutor
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import multiprocessing as mp
    import threading
    from examples.final_evaluation.c2c_local import run_game

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            text=json.dumps({'tool':'end_turn','parameters':{'rationale':'Transport test'}})
            body=json.dumps({'choices':[{'message':{'content':text},'finish_reason':'stop'}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=load_routes(ROOT/'examples/final_evaluation/c2c_local.json')
    for route in config['endpoints'].values():
        route['base_url']=f'http://127.0.0.1:{server.server_port}/v1'
    games=development_plan(100,1)['games'][:2]
    try:
        with ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
            futures=[pool.submit(run_game,ROOT/'third_party/cooperate-to-compete',config,tmp_path,g,1) for g in games]
            results=[f.result(timeout=30) for f in futures]
    finally:
        server.shutdown();server.server_close();thread.join()
    for game,result in zip(games,results):
        assert not result['worker_error']
        # Native rules reject end_turn before reinforcement, retrying three times per player.
        assert result['calls']==12
        calls=[json.loads(line) for line in (tmp_path/game['game_id']/'transport.jsonl').read_text().splitlines()]
        assert [c['call_index'] for c in calls if c['alias']=='q0']==list(range(9))
        assert [c['call_index'] for c in calls if c['alias']=='focal']==[0,1,2]
        assert all(c['status']=='ok' for c in calls)


def test_equivalent_replicas_balance_games_without_changing_default_routes():
    from examples.final_evaluation.c2c_local import game_routes
    config=load_routes(ROOT/'examples/final_evaluation/c2c_local.json')
    games=development_plan()['games']
    assert game_routes(config,games[0])==config
    config['equivalent_replicas']=[dict(config['endpoints'][k]) for k in ('focal','q0')]
    urls=[]
    for game in games:
        routed=game_routes(config,game)
        assert len({r['base_url'] for r in routed['endpoints'].values()})==1
        urls.append(routed['endpoints']['focal']['base_url'])
    assert urls.count(urls[0])==2
    assert config['endpoints']['focal']!=config['endpoints']['q0']
