"""Native800 D evaluation: eight independent resets, focal control to terminal.

No solver is run here. Entry Q and the certified frozen reference are inputs.
Only rendered messages/tools enter the model; annotations stay in local records.
"""
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from functools import lru_cache
import gzip
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np

# Establish BENAC's explicit source path before importing its dependent modules.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'third_party/negotiation_benchmark/src'))
from new.A2H2_structure_20261026 import IndexedReference
from training.strategic_slices.common import decode, digest, file_hash, seed_for, stable, write_json, write_rows
from training.strategic_slices.named_prompt_v7 import calls_for
from training.strategic_slices.terminal_d import HTTPGenerator, mean_interval
from .decision_v4 import Decision
from .prompt_v4 import request, VERSION as PROMPT_VERSION
from .scoring import CONTRACT, VERSION as SCORE_VERSION

VERSION = 'native800-terminal-D-v1'
REG = ROOT/'examples/strategic_slices/versions/native800_d_runner_v1_20261105/SNAPSHOT.json'
DEFAULT_CONFIG = ROOT/'examples/strategic_slices/native800/d_config_v1.json'


def atomic(path, value):
    path = Path(path)
    tmp = path.with_name(path.name+'.tmp')
    payload = (stable(value)+'\n').encode()
    if path.suffix == '.gz':
        with gzip.open(tmp, 'wb') as handle:
            handle.write(payload)
    else:
        tmp.write_bytes(payload)
    os.replace(tmp, path)


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    if cfg['replicas'] != 8 or cfg['temperature'] <= 0:
        raise ValueError('Eight stochastic independent replicas required')
    if cfg['workers'] < 1 or not 0 < cfg['top_p'] <= 1:
        raise ValueError('Invalid concurrency/sampling config')
    if not 0 < cfg['max_tokens'] < cfg['context']:
        raise ValueError('Invalid context or generation limit')
    if cfg['scheduler'] != 'completion-refill-v1' or cfg['control_end'] != 'NATIVE_TERMINAL':
        raise ValueError('Refusing a different scheduler/control boundary')
    if cfg['tensor_parallel_size'] != 1 or cfg['tool_call_parser'] != 'hermes':
        raise ValueError('This serving profile uses one GPU and Hermes')
    if not 0 < cfg['gpu_memory_utilization'] <= 1:
        raise ValueError('Invalid GPU memory fraction')
    return cfg


def pinned(path, checksum):
    path = Path(path)
    if file_hash(path) != checksum:
        raise ValueError(f'Input/source hash mismatch: {path}')
    return path


class Dataset:
    def __init__(self, data, pool, cfg):
        self.root, self.pool = Path(data).resolve(), Path(pool).resolve()
        pinned(self.root/'MANIFEST.json', cfg['dataset_manifest_sha256'])
        self.manifest = json.loads((self.root/'MANIFEST.json').read_text())
        pinned(self.pool/'MANIFEST.json', self.manifest['parent_pool']['sha256'])
        pinned(self.pool/'parents.jsonl', cfg['parents_sha256'])
        self.parents = {r['index']:r for r in map(json.loads, (self.pool/'parents.jsonl').read_text().splitlines())}
        self.rows = []
        for split in ('train', 'validation'):
            name = split+'.jsonl'
            pinned(self.root/name, self.manifest['files'][name]['sha256'])
            for row in map(json.loads, (self.root/name).read_text().splitlines()):
                if row['split'] != split:
                    raise ValueError('Split identity mismatch')
                if row['control']['end'] != 'NATIVE_TERMINAL':
                    raise ValueError('Wrong slice control contract')
                parent = self.parents[row['parent_index']]
                if row['parent_id'] != parent['id'] or row['source']['parent_raw_sha256'] != parent['source_raw_sha256']:
                    raise ValueError('Entry/parent binding mismatch')
                if row['source']['reference'] != parent['reference']:
                    raise ValueError('Entry/reference binding mismatch')
                self.rows.append(row)
        if len(self.parents) != 100 or len(self.rows) != 800 or len({r['id'] for r in self.rows}) != 800:
            raise ValueError('Expected the frozen 100-parent/800-entry pool')
        if Counter(r['split'] for r in self.rows) != {'train':600, 'validation':200}:
            raise ValueError('Expected 600 train/200 validation entries')
        if set(r['parent_index'] for r in self.rows) != set(self.parents):
            raise ValueError('Parent coverage mismatch')
        splits = defaultdict(set)
        for row in self.rows:
            splits[row['parent_index']].add(row['split'])
        if any(len(s) != 1 for s in splits.values()):
            raise ValueError('Train/validation parent overlap')

    def identity(self):
        return dict(manifest_sha256=file_hash(self.root/'MANIFEST.json'),
            parents_sha256=file_hash(self.pool/'parents.jsonl'),
            parent_manifest_sha256=file_hash(self.pool/'MANIFEST.json'),
            entry_ids=[r['id'] for r in self.rows],
            reference_assets={str(i):p['reference'] for i,p in self.parents.items()},
            admission_assets={str(i):p['admission'] for i,p in self.parents.items()})

    def runtime(self, index):
        parent = self.parents[index]
        admission = pinned(ROOT/parent['admission']['path'], parent['admission']['sha256'])
        job = json.loads(admission.read_text())['source']['job']
        if digest(job['raw']) != digest(parent['raw']):
            raise ValueError('Admission native game differs from selected parent')
        reference = pinned(self.pool/parent['reference']['path'], parent['reference']['sha256'])
        with np.load(reference, allow_pickle=False) as archive:
            flat = archive['probabilities'].copy()
        return ParentRuntime(IndexedReference(job, flat))


class ParentRuntime:
    def __init__(self, indexed):
        self.indexed = indexed
        self.rules = indexed.rules
        self.locate = lru_cache(maxsize=4096)(indexed.find)
        self.children = lru_cache(maxsize=4096)(self._children)

    def _children(self, index):
        node, offset = self.locate(index)
        actions = self.rules.actions(node)
        pos = index+1
        result = []
        for action in actions:
            result.append(pos)
            child = self.rules._apply(node, action)
            nodes, _ = self.indexed.stats(child)
            pos += nodes
        return tuple(result)

    def policy(self, index, world_index):
        node, offset = self.locate(index)
        count = len(self.rules.actions(node))
        probs = self.indexed.flat[offset:offset+count*self.indexed.w].reshape(count,self.indexed.w)[:,world_index]
        if not np.isfinite(probs).all() or np.any(probs < 0) or abs(float(probs.sum())-1) > 1e-7:
            raise ValueError('Invalid frozen reference distribution')
        return probs/probs.sum()  # floating-point normalization only; no off-path policy replacement


class Rollout:
    def __init__(self, parent, row, replica, cfg):
        self.parent, self.row, self.replica = parent, row, replica
        self.seed = seed_for(cfg['seed'], VERSION, row['id'], replica)
        self.oracle = row['oracle_annotation']
        weights = np.asarray(self.oracle['posterior'],dtype=float)
        if not np.isfinite(weights).all() or np.any(weights<0) or abs(float(weights.sum())-1)>1e-9:
            raise ValueError('Invalid conditional entrance posterior')
        self.wi = int(np.random.default_rng(seed_for(self.seed,'reset')).choice(self.oracle['world_ids'],p=weights/weights.sum()))
        self.world = parent.rules.worlds[self.wi]
        self.index = self.oracle['node']
        self.node, _ = parent.locate(self.index)
        self.ego = self.oracle['actor']
        # Bind root facts, legal actions and same-context protocol scoring to v4.
        self.entry = Decision(parent.indexed,self.index,self.world,self.oracle,seed_for(self.seed,'model',0),cfg['temperature'])
        self.rng = np.random.default_rng(seed_for(self.seed,'reference-actions'))
        self.status, self.utility = 'running', None
        self.calls, self.steps = [], []

    def request(self, cfg):
        req = request(self.parent.rules,self.node,self.world,seed_for(self.seed,'model',len(self.calls)),cfg['temperature'])
        req.update(max_tokens=cfg['max_tokens'],top_p=cfg['top_p'],top_k=cfg['top_k'],
            repetition_penalty=cfg['repetition_penalty'],tool_choice='auto',parallel_tool_calls=False)
        return req

    def step(self, ai, source):
        rules = self.parent.rules
        actions = rules.actions(self.node)
        native, _ = self.parent.locate(self.index)
        if [a.to_dict() for a in actions] != [a.to_dict() for a in rules.actions(native)]:
            raise ValueError('Live action menu differs from reference tree')
        child_index = self.parent.children(self.index)[ai]
        child = rules.step(self.node,actions[ai],realized_world=self.world)
        expected, _ = self.parent.locate(child_index)
        if child.state.public_state() != expected.state.public_state() or child.pending != expected.pending:
            raise ValueError('Native live/reference transition mismatch')
        self.steps.append(dict(node=self.index,actor=rules.actor(self.node),action_index=ai,source=source))
        self.node, self.index = child, child_index

    def advance(self):
        while self.status == 'running':
            actor = self.parent.rules.actor(self.node)
            if actor is None:
                self.utility = list(map(float,self.parent.rules.terminal_payoffs(self.node,self.world)))
                self.status = 'terminal'
                return
            if actor == self.ego:
                return
            ai = int(self.rng.choice(len(self.parent.rules.actions(self.node)),p=self.parent.policy(self.index,self.wi)))
            self.step(ai,'frozen-reference')

    def accept(self, output, req):
        if output.get('completion',{}).get('status') == 'infrastructure_failure':
            raise RuntimeError('Infrastructure failure is not a model outcome')
        actions = self.parent.rules.actions(self.node)
        ai, status = decode(output,actions,calls_for(self.parent.rules,self.node))
        root_score = self.entry.score(output) if not self.calls else None
        self.calls.append(dict(node=self.index,request=req,output=output,action_index=ai,
            protocol_status=status,prompt_sha256=digest({k:req[k] for k in ('messages','tools')}),
            entry_score=root_score,
            later_decision_score='NOT_COMPUTED' if root_score is None else None))
        if status != 'ok':
            self.status = status
            return
        self.step(ai,'model')
        self.advance()

    def record(self):
        own = self.world[self.ego]
        return dict(slice_id=self.row['id'],parent_id=self.row['parent_id'],parent_index=self.row['parent_index'],
            replica=self.replica,seed=self.seed,world_index=self.wi,ego=self.ego,status=self.status,
            controlled_decisions=len(self.calls),utility=None if self.utility is None else self.utility[self.ego],
            terminal_utilities=self.utility,utility_bounds=[sum(min(0,v)for v in own),sum(max(0,v)for v in own)],
            steps=self.steps,calls=self.calls)


class CompressedHTTPGenerator(HTTPGenerator):
    def log(self, row):
        with self.lock, gzip.open(self.evidence,'at',encoding='utf-8') as handle:
            handle.write(stable(row)+'\n')


def summarize(row, games, seed):
    complete = [g for g in games if g['status']=='terminal']
    vstar = float(max(row['oracle_annotation']['Q']))
    span = float(np.ptp(row['oracle_annotation']['Q']))
    full = len(complete)==len(games)
    estimate = mean_interval([vstar-g['utility'] for g in complete],seed_for(seed,row['id']))
    lower = float(np.mean([g['utility'] if g['utility'] is not None else g['utility_bounds'][0] for g in games]))
    upper = float(np.mean([g['utility'] if g['utility'] is not None else g['utility_bounds'][1] for g in games]))
    scores = [g['calls'][0]['entry_score'] for g in games if g['calls']]
    valid = [s for s in scores if s['valid']]
    root_gaps = [s['own_regret'] for s in valid]
    protocol_gaps = [s['protocol_regret'] for s in valid]
    first_prompts = {g['calls'][0]['prompt_sha256'] for g in games if g['calls']}
    if len(first_prompts)!=1:
        raise ValueError('Replicas do not share the same visible entry question')
    return dict(slice_id=row['id'],entry_id=row['entry_id'],parent_id=row['parent_id'],parent_index=row['parent_index'],
        split=row['split'],primary_role=row['primary_role'],features=row['features'],
        focal_decisions_to_native_terminal=row['focal_decisions_to_native_terminal'],
        V_star=vstar,own_Q_span=span,replicas=len(games),completed=len(complete),statuses=dict(Counter(g['status'] for g in games)),
        D=estimate['mean'] if full else None,D_over_own_Q_span=estimate['mean']/span if full and span>1e-9 else None,
        D_completed_only=estimate,D_missing_outcome_bounds=[vstar-upper,vstar-lower],
        entry_active_axis=scores[0]['active_axis'],
        entry_protocol_accuracy=sum(s['correct'] for s in scores)/len(games),
        entry_own_regret_mean_valid=float(np.mean(root_gaps)) if valid else None,
        entry_protocol_regret_mean_valid=float(np.mean(protocol_gaps)) if valid else None,
        root_value_contrast=bool(valid and np.ptp(root_gaps)>1e-9),
        root_protocol_contrast=bool(valid and np.ptp(protocol_gaps)>1e-9),
        root_mixed_protocol_correct_incorrect=bool(valid and any(s['correct']for s in valid)and not all(s['correct']for s in valid)),
        sampled_terminal_reward_contrast=bool(full and np.ptp([g['utility']for g in complete])>1e-9),
        entry_valid_samples=len(valid),first_prompt_sha256=next(iter(first_prompts)),
        ranking='No combined own/social D; no automatic final100 selection')


def make_protocol(dataset, cfg, identity, endpoint):
    registration = json.loads(REG.read_text())
    for name, checksum in registration['source_hashes'].items():
        pinned(ROOT/name,checksum)
    return dict(version=VERSION,prompt_version=PROMPT_VERSION,scoring_version=SCORE_VERSION,
        registration_sha256=file_hash(REG),source_identity=registration['source_hashes'],
        config=cfg,model_identity=identity,input_identity=dataset.identity(),endpoint=endpoint,
        reset='Independent posterior world draw per replica; no reset to parent prior; same visible entry across replicas',
        control='Focal player at every subsequent decision to native terminal; opponents frozen certified reference',
        D='Unclipped Vstar minus mean native terminal own utility; null if any incomplete sample',
        diagnostics='Entry own regret and response-only protocol/social regret separate; no mixed D ranking',
        scoring_contract=CONTRACT,retry='No automatic generation retry; explicit resume repeats unfinished replicas',
        memory='Rebuild full public state/history and own cumulative direct answers each decision; no assistant explanation history',
        validation='Implementation only; CPU/GPU/model verification waived by user before remote execution',
        training='NOT_STARTED_NOT_MIGRATED',selection='NOT_PERFORMED; validation is diagnostic only')


def open_run(output, protocol, resume, argv):
    output = Path(output)
    if output.exists():
        if not resume or not (output/'protocol.json').is_file():
            raise FileExistsError('Use a fresh output or explicit resume of a native800 run')
        if json.loads((output/'protocol.json').read_text()) != protocol:
            raise ValueError('Resume model/data/config/source/endpoint mismatch')
    else:
        output.mkdir(parents=True)
        atomic(output/'protocol.json',protocol)
        for name in protocol['source_identity']:
            target = output/'source'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        shutil.copyfile(REG,output/'registered_snapshot_at_start.json')
        snapshot = dict(protocol,actual_argv=argv,resolved_config=protocol['config'],
            date_at_implementation='2026-11-05',runtime_clock_unix=time.time(),
            environment=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),
                threads={key:os.environ.get(key,'NOT_RECORDED') for key in
                    ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','TOKENIZERS_PARALLELISM')}))
        atomic(output/'pipeline_snapshot.json',snapshot)
    for name, checksum in protocol['source_identity'].items():
        pinned(output/'source'/name,checksum)
    (output/'replicas').mkdir(exist_ok=True)
    (output/'parents').mkdir(exist_ok=True)


def run_evaluation(dataset, cfg, output, generate, identity, endpoint, *, resume=False, argv=None):
    output = Path(output)
    protocol = make_protocol(dataset,cfg,identity,endpoint)
    open_run(output,protocol,resume,list(sys.argv) if argv is None else argv)
    protocol_hash = digest(protocol)
    all_rows = []
    def saved_path(row, replica):
        return output/'replicas'/f'{row["id"]}-{replica}.json.gz'
    def save(job):
        record = job.record()
        result = dict(protocol_sha256=protocol_hash,record=record)
        atomic(saved_path(job.row,job.replica),dict(sha256=digest(result),result=result))
        return record
    def read(row, replica):
        with gzip.open(saved_path(row,replica),'rt') as handle:
            wrapper = json.load(handle)
        result = wrapper['result'];record=result['record']
        if wrapper['sha256']!=digest(result) or result['protocol_sha256']!=protocol_hash:
            raise ValueError('Saved replica integrity/protocol mismatch')
        if (record['slice_id'],record['parent_id'],record['replica'])!=(row['id'],row['parent_id'],replica):
            raise ValueError('Saved replica identity mismatch')
        if record['status']=='running':
            raise ValueError('Unfinished replica cannot be reused')
        return record
    try:
        # One loaded reference at a time; requests within the parent refill on completion.
        for number,index in enumerate(sorted(dataset.parents),1):
            rows = sorted((r for r in dataset.rows if r['parent_index']==index),key=lambda r:r['id'])
            missing = [(row,replica) for row in rows for replica in range(cfg['replicas']) if not saved_path(row,replica).exists()]
            if missing:
                parent = dataset.runtime(index)
                ready = deque(Rollout(parent,row,replica,cfg) for row,replica in missing)
                pending = {}
                with ThreadPoolExecutor(max_workers=cfg['workers']) as pool:
                    while ready or pending:
                        while ready and len(pending)<cfg['workers']:
                            job = ready.popleft();req=job.request(cfg)
                            pending[pool.submit(generate.one,req)] = (job,req)
                        done,_ = wait(pending,return_when=FIRST_COMPLETED)
                        for future in done:
                            job,req = pending.pop(future)
                            job.accept(future.result(),req)
                            if job.status=='running':
                                ready.append(job)
                            else:
                                save(job)
            result_rows = [summarize(row,[read(row,i) for i in range(cfg['replicas'])],cfg['seed']) for row in rows]
            atomic(output/'parents'/f'{index}.json',dict(protocol_sha256=protocol_hash,parent_index=index,slices=result_rows))
            all_rows.extend(result_rows)
            print(f'parents {number}/100; entries {len(all_rows)}/800; parent {index}',flush=True)
        summary = dict(version=VERSION,prompt_version=PROMPT_VERSION,scoring_version=SCORE_VERSION,
            status='COMPLETED_REAL_MODEL_D',model=identity,slices=len(all_rows),trajectories=len(all_rows)*cfg['replicas'],
            complete_slices=sum(r['D'] is not None for r in all_rows),
            entry_protocol_contrast_slices=sum(r['root_protocol_contrast']for r in all_rows),
            splits={},strata=[],interpretation=protocol['diagnostics'],training='NOT_STARTED',final100='NOT_SELECTED')
        for field in ('split','primary_role','parent_index'):
            groups = defaultdict(list)
            for row in all_rows:
                groups[str(row[field])].append(row)
            for label,cohort in sorted(groups.items()):
                ds = [r['D'] for r in cohort if r['D'] is not None]
                group = dict(slices=len(cohort),complete_slices=len(ds),mean_D_completed=float(np.mean(ds)) if ds else None,
                    protocol_contrast=sum(r['root_protocol_contrast'] for r in cohort),
                    mean_entry_protocol_accuracy=float(np.mean([r['entry_protocol_accuracy']for r in cohort])))
                if field=='split':summary['splits'][label]=group
                else:summary['strata'].append(dict(dimension=field,value=label,**group))
        for name,checksum in protocol['source_identity'].items():
            pinned(ROOT/name,checksum)
        write_rows(output/'slices.jsonl',all_rows)
        write_rows(output/'train_signal_candidates.jsonl',[r for r in all_rows if r['split']=='train'and r['D'] is not None and r['root_protocol_contrast']])
        atomic(output/'summary.json',summary)
        (output/'REPORT.md').write_text('# Native800 D\n\n'+f'{len(all_rows)} entries; {summary["trajectories"]} independent trajectories; {summary["complete_slices"]} entries with complete terminal D.\n\n'+
            'Own terminal D and entry protocol/social diagnostics are separate. No final100 selection or training. '
            'Incomplete entries have D=null and explicit missing-outcome bounds. Later decisions have native validity records, not newly computed oracle scores.\n')
        paths = [output/'protocol.json',output/'pipeline_snapshot.json',output/'slices.jsonl',output/'summary.json',output/'train_signal_candidates.jsonl',output/'REPORT.md',
                 *sorted((output/'replicas').glob('*.json.gz')),*sorted((output/'parents').glob('*.json'))]
        atomic(output/'COMPLETE.json',dict(protocol_sha256=protocol_hash,files={str(p.relative_to(output)):file_hash(p) for p in paths}))
        return summary
    except BaseException as exc:
        atomic(output/f'FAILED-{time.time_ns()}.json',dict(error=repr(exc),protocol_sha256=protocol_hash,
            recovery='Explicit --resume preserves completed replica files; unfinished replicas restart with identical seeds. No automatic retry.'))
        raise
