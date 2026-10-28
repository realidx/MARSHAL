"""Exact cached continuation values versus the original exhaustive terminal solver."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import numpy as np

from training.social_mixed.cache import ByteLRU,CacheNamespace,estimated_bytes
from .values import extreme_value,cached_extreme_value
from .terminal_training import TrainingData


class CPUReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from .test_terminal_training import TrainingTests
        TrainingTests.setUpClass();cls.tree,cls.rows=TrainingTests.tree,TrainingTests.rows
    def compare(self,tree,row,cache):
        for m in row['members']:
            for maximize in (True,False):
                original=extreme_value(tree,row['ego'],m['root_index'],m['world_weights'],row['k'],maximize)
                fast=cached_extreme_value(tree,row['ego'],m['root_index'],m['world_weights'],row['k'],maximize,cache)
                np.testing.assert_allclose(original['root_Q'],fast['root_Q'],atol=1e-12,rtol=0)
                self.assertAlmostEqual(original['value'],fast['value'],places=12)
                self.assertEqual(original['policy'].keys(),fast['policy'].keys())
                for index in original['policy']:np.testing.assert_array_equal(original['policy'][index],fast['policy'][index])
    def test_all_fixture_entrances_k_players_and_both_extremes(self):
        cache={};before=self.tree.reference_identity()[0]
        for row in self.rows:self.compare(self.tree,row,cache)
        self.assertEqual(self.tree.reference_identity()[0],before)
        self.assertEqual({r['k'] for r in self.rows},{1,2,3})
        # A separate native two-player fixture, including terminal before k.
        from .build import sample_parent
        from .bounded import BoundedPrivateWindow
        from .oracle_consistent import measure_parent
        from training.b_sft.social_private_teacher import PrivateInvestigationRules
        raw=sample_parent(2026100703,2,rounds=1);rules=PrivateInvestigationRules(raw)
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,lookahead_rr=3,max_joint_cells=8192,
            large_tree_ordered_sweeps=8,seconds=20).solve()
        rows,_=measure_parent(tree,'two-player',cap=8)
        for row in rows:self.compare(tree,row,{})
    def test_same_reference_tail_reuses_across_posterior_and_k_without_point_mass(self):
        row=next(r for r in self.rows if sum(w>0 for w in r['members'][0]['world_weights'])>1)
        member=row['members'][0];weights=np.asarray(member['world_weights']);cache={}
        a=cached_extreme_value(self.tree,row['ego'],member['root_index'],weights,1,cache=cache)
        b=cached_extreme_value(self.tree,row['ego'],member['root_index'],weights,1,cache=cache)
        self.assertGreater(a['tail_nodes_computed'],0);self.assertEqual(b['tail_nodes_computed'],0)
        self.assertEqual(a['root_Q'],b['root_Q'])
        ids=np.flatnonzero(weights);altered=weights.copy();altered[ids[0]]*=2;altered/=altered.sum()
        for k in (1,2,3,10):
            original=extreme_value(self.tree,row['ego'],member['root_index'],altered,k)
            fast=cached_extreme_value(self.tree,row['ego'],member['root_index'],altered,k,cache=cache)
            np.testing.assert_allclose(original['root_Q'],fast['root_Q'],atol=1e-12,rtol=0)
    def test_lru_namespaces_and_memory_eviction_do_not_change_values(self):
        v=np.arange(10,dtype=float);size=estimated_bytes((('r',1),v));lru=ByteLRU(size*2+100)
        a,b=CacheNamespace(lru,'a'),CacheNamespace(lru,'b')
        a[1]=v;b[1]=v+1
        np.testing.assert_equal(a[1],v);np.testing.assert_equal(b[1],v+1)
        for i in range(20):a[i]=v+i
        self.assertLessEqual(lru.bytes,lru.budget);self.assertGreater(lru.evictions,0)
        self.assertNotIn(1,b)
        row=self.rows[0];m=row['members'][0]
        fast=cached_extreme_value(self.tree,row['ego'],m['root_index'],m['world_weights'],row['k'],cache=a)
        original=extreme_value(self.tree,row['ego'],m['root_index'],m['world_weights'],row['k'])
        np.testing.assert_allclose(fast['root_Q'],original['root_Q'],atol=1e-12,rtol=0)
        self.assertLessEqual(lru.bytes,lru.budget)
    def test_reference_eviction_preserves_independent_oracle_cache(self):
        # Run the actual training adapter retention code with small native trees.
        data=TrainingData.__new__(TrainingData)
        data.tree_cache=ByteLRU(1);data.oracle_cache=ByteLRU(4096);data.reference_restore_seconds=0.
        restored=[];loader_cache={}
        def reference(row):restored.append(row['reference_id']);loader_cache[row['reference_id']]=self.tree;return self.tree
        data.pool=NS(reference=reference,cache=loader_cache)
        tree,a=data.reference(dict(reference_id='r'));a[('Q',1)]=[1.,2.]
        _,b=data.reference(dict(reference_id='other'));b[('Q',1)]=[3.,4.]
        tree,again=data.reference(dict(reference_id='r'))
        self.assertEqual(again[('Q',1)],[1.,2.]);self.assertEqual(b[('Q',1)],[3.,4.])
        self.assertFalse(loader_cache);self.assertEqual(restored,['r','other','r'])
        data.tree_cache=ByteLRU(estimated_bytes(('r',self.tree))+100)
        data.reference(dict(reference_id='r'));data.reference(dict(reference_id='r'))
        self.assertEqual(restored,['r','other','r','r'])
        self.assertGreater(data.cache_metrics()['tree_cache_hits'],0)


if __name__=='__main__':unittest.main()
