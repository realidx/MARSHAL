"""Reuse already-constructed native child nodes while replaying exact forests."""
from collections import OrderedDict
from new import candidate_qs_profiles_20261104_v2 as previous

base=previous.base


class SparseNative(previous.SparseNative):
    def __init__(self,indexed,cache_nodes):
        self.known=OrderedDict();self.known_limit=cache_nodes*4
        super().__init__(indexed,cache_nodes)

    def _expand(self,global_index):
        data=self.known.pop(global_index,None)
        node,offset=self.locate(global_index)if data is None else data
        actions=self.rules.actions(node)
        pos=global_index+1;off=offset+len(actions)*self.w;children=[]
        for action in actions:
            child=self.rules._apply(node,action);nn,nf=self.indexed.stats(child)
            children.append((child,pos,off));self.known[pos]=(child,off)
            if len(self.known)>self.known_limit:self.known.popitem(last=False)
            pos+=nn;off+=nf
        return node,offset,actions,children


base.SparseNative=SparseNative
base.VERSION='candidate-qs-profiles-sparse-v3'
base.REG=base.m.ROOT/'examples/strategic_slices/versions/candidate_qs_profiles_v3_20261104/SNAPSHOT.json'

if __name__=='__main__':base.main()
