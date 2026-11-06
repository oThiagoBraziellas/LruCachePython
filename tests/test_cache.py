import threading
import unittest

from lru_cache import LRUCache


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class BasicTests(unittest.TestCase):
    def test_put_get(self):
        c = LRUCache(2)
        c.put("a", 1)
        self.assertEqual(c.get("a"), 1)
        self.assertIsNone(c.get("missing"))
        self.assertEqual(c.get("missing", 7), 7)

    def test_evicts_least_recently_used(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.get("a")  # a becomes most recent
        c.put("c", 3)
        self.assertNotIn("b", c)
        self.assertIn("a", c)
        self.assertIn("c", c)

    def test_update_refreshes_recency_and_value(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("a", 10)
        c.put("c", 3)
        self.assertEqual(c.get("a"), 10)
        self.assertNotIn("b", c)
        self.assertEqual(len(c), 2)

    def test_capacity_one(self):
        c = LRUCache(1)
        c.put("a", 1)
        c.put("b", 2)
        self.assertEqual(list(c.items()), [("b", 2)])

    def test_invalid_capacity(self):
        for bad in (0, -3):
            with self.assertRaises(ValueError):
                LRUCache(bad)

    def test_delete_and_clear(self):
        c = LRUCache(3)
        c.put("a", 1)
        c.put("b", 2)
        self.assertTrue(c.delete("a"))
        self.assertFalse(c.delete("a"))
        c.clear()
        self.assertEqual(len(c), 0)
        c.put("z", 26)  # still usable after clear
        self.assertEqual(c.get("z"), 26)

    def test_items_order_is_mru_first(self):
        c = LRUCache(3)
        for k in "abc":
            c.put(k, k)
        c.get("a")
        self.assertEqual([k for k, _ in c.items()], ["a", "c", "b"])

    def test_peek_does_not_change_order(self):
        c = LRUCache(2)
        c.put("a", 1)
        c.put("b", 2)
        c.peek("a")
        c.put("c", 3)
        self.assertNotIn("a", c)

    def test_none_and_falsy_values_are_cached(self):
        c = LRUCache(2)
        c.put("n", None)
        c.put("z", 0)
        self.assertIn("n", c)
        self.assertEqual(c.get("z", "default"), 0)

    def test_stats(self):
        c = LRUCache(1)
        c.put("a", 1)
        c.get("a")
        c.get("b")
        c.put("b", 2)
        s = c.stats()
        self.assertEqual((s["hits"], s["misses"], s["evictions"]), (1, 1, 1))
        self.assertAlmostEqual(s["hit_rate"], 0.5)

    def test_get_or_set_calls_factory_once(self):
        c = LRUCache(2)
        calls = []
        factory = lambda: calls.append(1) or "v"
        self.assertEqual(c.get_or_set("k", factory), "v")
        self.assertEqual(c.get_or_set("k", factory), "v")
        self.assertEqual(len(calls), 1)

    def test_linked_list_integrity_after_many_operations(self):
        c = LRUCache(4)
        for i in range(200):
            c.put(i % 7, i)
            if i % 3 == 0:
                c.get((i * 5) % 7)
            if i % 11 == 0:
                c.delete(i % 7)
        forward = [k for k, _ in c.items()]
        self.assertEqual(len(forward), len(c))
        self.assertEqual(len(set(forward)), len(forward))
        self.assertLessEqual(len(c), 4)


class TtlTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()

    def test_entry_expires(self):
        c = LRUCache(2, default_ttl=10, clock=self.clock)
        c.put("a", 1)
        self.clock.now = 9.9
        self.assertEqual(c.get("a"), 1)
        self.clock.now = 10.0
        self.assertIsNone(c.get("a"))
        self.assertEqual(len(c), 0)

    def test_per_key_ttl_overrides_default(self):
        c = LRUCache(2, default_ttl=100, clock=self.clock)
        c.put("short", 1, ttl=1)
        c.put("long", 2)
        self.clock.now = 5
        self.assertNotIn("short", c)
        self.assertIn("long", c)

    def test_put_resets_ttl(self):
        c = LRUCache(2, default_ttl=10, clock=self.clock)
        c.put("a", 1)
        self.clock.now = 8
        c.put("a", 2)
        self.clock.now = 15
        self.assertEqual(c.get("a"), 2)

    def test_expired_lru_entry_is_not_counted_as_eviction(self):
        c = LRUCache(2, clock=self.clock)
        c.put("dying", 1, ttl=1)       # LRU, will expire
        c.put("live", 2)
        self.clock.now = 5
        c.put("new", 3)
        self.assertNotIn("dying", c)
        self.assertIn("live", c)
        self.assertEqual(c.stats()["evictions"], 0)

    def test_purge_expired(self):
        c = LRUCache(5, default_ttl=1, clock=self.clock)
        for k in "abc":
            c.put(k, k)
        self.clock.now = 2
        self.assertEqual(c.purge_expired(), 3)
        self.assertEqual(len(c), 0)

    def test_expired_get_counts_as_miss(self):
        c = LRUCache(2, default_ttl=1, clock=self.clock)
        c.put("a", 1)
        self.clock.now = 3
        c.get("a")
        self.assertEqual(c.stats()["misses"], 1)

    def test_invalid_ttl(self):
        with self.assertRaises(ValueError):
            LRUCache(2, default_ttl=0)
        with self.assertRaises(ValueError):
            LRUCache(2).put("a", 1, ttl=-1)


class ThreadSafetyTests(unittest.TestCase):
    def test_concurrent_access_keeps_invariants(self):
        c = LRUCache(50)
        errors = []

        def worker(seed):
            try:
                for i in range(2000):
                    k = (i * seed) % 120
                    c.put(k, k)
                    v = c.get((k + 1) % 120)
                    if v is not None and v != (k + 1) % 120:
                        errors.append("wrong value")
                    if i % 17 == 0:
                        c.delete(k)
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(s,)) for s in (1, 3, 7, 11, 13)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertLessEqual(len(c), 50)
        keys = [k for k, _ in c.items()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), len(c))


if __name__ == "__main__":
    unittest.main()
