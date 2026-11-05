"""Implementation-only fix: a forest with no zero-mass stubs reports count0."""
from new import candidate_qs_profiles_20261104 as base


class SparseNative(base.SparseNative):
    def forest(self,*args,**kwargs):
        tree,roots,mapping,counts=super().forest(*args,**kwargs)
        counts.setdefault('exact_zero_mass_stubs',0)
        return tree,roots,mapping,counts


base.SparseNative=SparseNative
base.VERSION='candidate-qs-profiles-sparse-v2'
base.REG=base.m.ROOT/'examples/strategic_slices/versions/candidate_qs_profiles_v2_20261104/SNAPSHOT.json'

if __name__=='__main__':base.main()
