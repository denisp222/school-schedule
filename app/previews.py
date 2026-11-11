"""Thread-safe bounded transient data. It never contains persistent state."""
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic


class PreviewStore:
    def __init__(self, limit=50, ttl=1800, clock=monotonic):
        self.limit, self.ttl, self.clock = limit, ttl, clock
        self._items = OrderedDict()
        self._lock = RLock()

    def _expire(self):
        now = self.clock()
        for key in list(self._items):
            if self._items[key][0] <= now:
                del self._items[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._expire()
            self._items.pop(key, None)
            self._items[key] = (self.clock() + self.ttl, deepcopy(value))
            while len(self._items) > self.limit:
                self._items.popitem(last=False)

    def get(self, key, default=None):
        if not isinstance(key, str):
            return default
        with self._lock:
            self._expire()
            row = self._items.get(key)
            return deepcopy(row[1]) if row is not None else default

    def __getitem__(self, key):
        sentinel=object()
        result=self.get(key,sentinel)
        if result is sentinel:raise KeyError(key)
        return result

    def clear(self):
        with self._lock:
            self._items.clear()

    def pop(self,key,default=None):
        with self._lock:
            self._expire()
            row=self._items.pop(key,None) if isinstance(key,str) else None
            return deepcopy(row[1]) if row is not None else default

    def __len__(self):
        with self._lock:
            self._expire()
            return len(self._items)
