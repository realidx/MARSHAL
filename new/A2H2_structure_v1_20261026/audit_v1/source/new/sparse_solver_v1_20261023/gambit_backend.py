"""Optional pinned independent solver on a losslessly reduced extensive game."""
from fractions import Fraction
import importlib.metadata
import multiprocessing as mp
from pathlib import Path
import time

import numpy as np


def export(game,path):
    tree=game.tree;red=game.red;counts=[0,0];mapping={};outcomes={}
    def visit(f,i,w):
        if red.known[i,w]:
            payoff=tuple(float(v) for v in red.payoffs[i,w])
            oid=outcomes.setdefault(payoff,len(outcomes)+1)
            numbers=' '.join(str(Fraction(v).limit_denominator(10**12)) for v in payoff)
            f.write(f't "" {oid} "" {{ {numbers} }}\n');return
        e=tree.entries[i];key=(i,int(red.cell_ids[i][w]));actions=tuple(red.allowed(i,w))
        if len(actions)==1:visit(f,e.children[actions[0]],w);return
        if key not in mapping:
            counts[e.actor]+=1;mapping[key]=counts[e.actor]
        label=f'i{i}c{key[1]}'
        names=' '.join(f'"a{a}"' for a in actions)
        f.write(f'p "" {e.actor+1} {mapping[key]} "{label}" {{ {names} }} 0\n')
        for a in actions:visit(f,e.children[a],w)
    prior=[Fraction(float(v)).limit_denominator(10**12) for v in tree.world_weights]
    total=sum(prior);prior=[v/total for v in prior]
    with path.open('w') as f:
        f.write('EFG 2 R "Dominance reduced native terminal" { "P0" "P1" }\n')
        f.write('c "world" 1 "" { '+' '.join(f'"w{w}" {v}' for w,v in enumerate(prior))+' } 0\n')
        for w in range(tree.w):visit(f,0,w)
    return mapping


def _worker(path,connection):
    try:
        import pygambit as gbt
        game=gbt.read_efg(Path(path));start=time.monotonic()
        assert game.is_perfect_recall
        result=gbt.nash.lcp_solve(game,rational=False,use_strategic=False)
        if not result.equilibria:
            connection.send(dict(status='no_equilibrium_returned'));return
        profile=result.equilibria[0]
        probs={info.label:[float(profile[a]) for a in info.actions]
               for p in game.players for info in p.infosets}
        connection.send(dict(status='candidate',probabilities=probs,
            pygambit=gbt.__version__,search_seconds=time.monotonic()-start,
            perfect_recall=bool(game.is_perfect_recall),
            gambit_max_regret=float(profile.max_regret())))
    except BaseException as exc:
        connection.send(dict(status='error',error=f'{type(exc).__name__}: {exc}'))
    finally:connection.close()


def solve(game,folder,seconds=30.,max_dimension=12000):
    dimension=sum(game.counts)+sum(len(c)+1 for c in game.cells)
    info=dict(dense_dimension=dimension,single_matrix_bytes=8*dimension*(dimension+1),
              max_dimension=max_dimension,backend='pygambit16.7.0-float-sequence-lcp')
    if dimension>max_dimension:
        return None,dict(info,status='preflight_memory_guard')
    path=Path(folder)/'reduced.efg';mapping=export(game,path)
    ctx=mp.get_context('spawn');parent,child=ctx.Pipe(False)
    process=ctx.Process(target=_worker,args=(str(path.resolve()),child))
    process.start();child.close()
    if parent.poll(seconds):result=parent.recv()
    else:result=dict(status='hard_timeout')
    if process.is_alive():process.terminate()
    process.join(timeout=5);parent.close()
    info.update(result)
    if info['status']!='candidate':return None,info
    probs=info.pop('probabilities');game.red.install()
    for (i,cell) in mapping:
        ids=game.tree.information_groups[i][cell]
        p=np.asarray(probs[f'i{i}c{cell}'])
        if not np.isfinite(p).all() or p.min() < -1e-8:
            return None,dict(info,status='invalid_probabilities')
        p=np.maximum(p,0.);p/=p.sum()
        game.tree.policy[i][:,ids]=p[:,None]
    return [game.realization(game.tree.policy,p) for p in range(2)],info
