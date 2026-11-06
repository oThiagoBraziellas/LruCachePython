"""O(1) LRU cache built from a dict and a doubly linked list."""

import threading
import time
from typing import Any, Callable, Dict, Hashable, Iterator, Optional, Tuple

_MISSING = object()


class _Node:
    __slots__ = ("key", "value", "expires_at", "prev", "next")

    def __init__(self, key: Hashable = None, value: Any = None, expires_at: Optional[float] = None):
        self.key = key
        self.value = value
        self.expires_at = expires_at
        self.prev: "_Node" = self
        self.next: "_Node" = self


class LRUCache:
    """Least-recently-used cache.

    ``get`` and ``put`` run in O(1): a dict maps keys to nodes and a doubly
    linked list keeps nodes ordered from most to least recently used. A
    sentinel node removes every edge case for empty/one-element lists.

    ``default_ttl`` (seconds) applies to every ``put`` unless overridden.
    Expired entries are dropped lazily on access and never count as hits.
    All public methods take one re-entrant lock, so the cache can be shared
    between threads.
    """

    def __init__(
        self,
        capacity: int,
        default_ttl: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if default_ttl is not None and default_ttl <= 0:
            raise ValueError("default_ttl must be positive")
        self._capacity = capacity
        self._default_ttl = default_ttl
        self._clock = clock
        self._map: Dict[Hashable, _Node] = {}
        self._head = _Node()  # sentinel: head.next is MRU, head.prev is LRU
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # -- linked list helpers -------------------------------------------------

    def _unlink(self, node: _Node) -> None:
        node.prev.next = node.next
        node.next.prev = node.prev

    def _push_front(self, node: _Node) -> None:
        first = self._head.next
        node.prev = self._head
        node.next = first
        first.prev = node
        self._head.next = node

    def _expired(self, node: _Node) -> bool:
        return node.expires_at is not None and self._clock() >= node.expires_at

    def _remove(self, node: _Node) -> None:
        self._unlink(node)
        del self._map[node.key]

    # -- public API ----------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            node = self._map.get(key)
            if node is None:
                self._misses += 1
                return default
            if self._expired(node):
                self._remove(node)
                self._misses += 1
                return default
            self._unlink(node)
            self._push_front(node)
            self._hits += 1
            return node.value

    def put(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        ttl = self._default_ttl if ttl is None else ttl
        expires_at = None if ttl is None else self._clock() + ttl
        with self._lock:
            node = self._map.get(key)
            if node is not None:
                node.value = value
                node.expires_at = expires_at
                self._unlink(node)
                self._push_front(node)
                return
            if len(self._map) >= self._capacity:
                self._make_room()
            node = _Node(key, value, expires_at)
            self._map[key] = node
            self._push_front(node)

    def _make_room(self) -> None:
        # Only the LRU end is inspected, so insertion stays O(1). If that
        # entry already expired, dropping it is not counted as an eviction.
        lru = self._head.prev
        if not self._expired(lru):
            self._evictions += 1
        self._remove(lru)

    def delete(self, key: Hashable) -> bool:
        with self._lock:
            node = self._map.get(key)
            if node is None:
                return False
            self._remove(node)
            return True

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """Read without changing recency or statistics."""
        with self._lock:
            node = self._map.get(key)
            if node is None or self._expired(node):
                return default
            return node.value

    def get_or_set(self, key: Hashable, factory: Callable[[], Any], ttl: Optional[float] = None) -> Any:
        """Return the cached value or compute, store and return it.

        The factory runs under the lock, so it runs once per missing key.
        """
        with self._lock:
            value = self.get(key, _MISSING)
            if value is _MISSING:
                value = factory()
                self.put(key, value, ttl)
            return value

    def purge_expired(self) -> int:
        with self._lock:
            dead = [n for n in self._map.values() if self._expired(n)]
            for node in dead:
                self._remove(node)
            return len(dead)

    def clear(self) -> None:
        with self._lock:
            self._map.clear()
            self._head.next = self._head.prev = self._head

    def items(self) -> Iterator[Tuple[Hashable, Any]]:
        """Snapshot of live entries, most recently used first."""
        with self._lock:
            out = []
            node = self._head.next
            while node is not self._head:
                if not self._expired(node):
                    out.append((node.key, node.value))
                node = node.next
            return iter(out)

    def stats(self) -> Dict[str, float]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._map),
                "capacity": self._capacity,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": self._hits / total if total else 0.0,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._map)

    def __contains__(self, key: Hashable) -> bool:
        return self.peek(key, _MISSING) is not _MISSING
