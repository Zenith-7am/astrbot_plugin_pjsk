"""Tests for PendingImageStore."""
import time
from gateway.matchers.pending_image_store import PendingImageStore, _Entry


class TestPendingImageStore:
    def test_put_and_pop(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        assert store.pop("g1", "u1") == b"img1"

    def test_pop_removes_entry(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        store.pop("g1", "u1")
        assert store.pop("g1", "u1") is None

    def test_pop_expired_returns_none(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        # Fast-forward past TTL by reaching into internals
        key = ("g1", "u1")
        store._entries[key] = _Entry(data=store._entries[key].data, timestamp=time.monotonic() - 131)
        assert store.pop("g1", "u1") is None

    def test_different_users_independent(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"img1")
        store.put("g1", "u2", b"img2")
        assert store.pop("g1", "u1") == b"img1"
        assert store.pop("g1", "u2") == b"img2"

    def test_new_image_overwrites_old(self):
        store = PendingImageStore()
        store.put("g1", "u1", b"old")
        store.put("g1", "u1", b"new")
        assert store.pop("g1", "u1") == b"new"

    
    def test_put_sweeps_expired_entries(self):
        store = PendingImageStore(max_entries=10)
        # Insert several entries and age them past TTL
        import time as _time
        for i in range(5):
            key = ("g1", f"u{i}")
            store._entries[key] = _Entry(data=f"old{i}".encode(), timestamp=_time.monotonic() - 200)
        # Now put() a new entry — should sweep the 5 expired ones
        store.put("g1", "u_new", b"fresh")
        # Only the fresh entry should remain
        assert len(store._entries) == 1
        assert store._entries[("g1", "u_new")].data == b"fresh"

    def test_hard_limit_evicts_oldest(self):
        store = PendingImageStore(max_entries=3)
        store.put("g1", "u1", b"a")
        store.put("g1", "u2", b"b")
        store.put("g1", "u3", b"c")
        store.put("g1", "u4", b"d")  # evicts oldest
        assert store.pop("g1", "u1") is None  # evicted
        assert store.pop("g1", "u4") == b"d"
