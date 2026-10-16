"""Byte-budgeted process-local LRU; estimates retained objects, not process RSS."""
from collections import OrderedDict,deque
from collections.abc import MutableMapping
import sys
import types
import numpy as np


def estimated_bytes(value):
    seen=set();pending=[value];total=0
    while pending:
        item=pending.pop();identity=id(item)
        if identity in seen:continue
        seen.add(identity)
        if isinstance(item,(type,types.ModuleType,types.FunctionType,types.MethodType)):continue
        total+=sys.getsizeof(item)
        if isinstance(item,np.ndarray):
            if item.base is not None:pending.append(item.base)
        elif isinstance(item,dict):pending.extend(item.keys());pending.extend(item.values())
        elif isinstance(item,(tuple,list,set,frozenset,deque)):pending.extend(item)
        elif hasattr(item,'__dict__'):pending.append(vars(item))
    return total


class ByteLRU:
    def __init__(self,budget):
        if type(budget) is not int or budget<0:raise ValueError('Cache byte budget must be a nonnegative integer')
        self.budget=budget;self.items=OrderedDict();self.bytes=0;self.hits=self.misses=self.evictions=0
    def __contains__(self,key):return key in self.items
    def __getitem__(self,key):
        if key not in self.items:self.misses+=1;raise KeyError(key)
        self.hits+=1;self.items.move_to_end(key);return self.items[key][0]
    def get(self,key,default=None):
        try:return self[key]
        except KeyError:return default
    def put(self,key,value):
        size=estimated_bytes((key,value))
        if key in self.items:self.bytes-=self.items.pop(key)[1]
        if size>self.budget:return
        while self.items and self.bytes+size>self.budget:
            _,(_,old)=self.items.popitem(last=False);self.bytes-=old;self.evictions+=1
        self.items[key]=(value,size);self.bytes+=size
    def stats(self):return dict(bytes=self.bytes,budget_bytes=self.budget,entries=len(self.items),hits=self.hits,misses=self.misses,evictions=self.evictions)


class CacheNamespace(MutableMapping):
    def __init__(self,cache,prefix):self.cache,self.prefix=cache,prefix
    def __contains__(self,key):return (self.prefix,key) in self.cache
    def __getitem__(self,key):return self.cache[self.prefix,key]
    def __setitem__(self,key,value):self.cache.put((self.prefix,key),value)
    def __delitem__(self,key):
        _,size=self.cache.items.pop((self.prefix,key));self.cache.bytes-=size
    def __iter__(self):return (key for prefix,key in self.cache.items if prefix==self.prefix)
    def __len__(self):return sum(prefix==self.prefix for prefix,_ in self.cache.items)
