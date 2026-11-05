"""Extend the frozen six-case diagnosis uniformly to its remaining25 cases."""
from pathlib import Path
from new import diagnose_H2_sparse_S_20261024 as diagnostic

assert diagnostic.VERSION=='H2-sparse-S-causes-v1'
assert diagnostic.EPS==1e-8
diagnostic.VERSION='H2-sparse-S-causes-full31-v2'
diagnostic.REG=diagnostic.ROOT/'examples/strategic_slices/versions/H2_sparse_S_causes_full31_v2_20261024/SNAPSHOT.json'

if __name__=='__main__':
    diagnostic.main()
