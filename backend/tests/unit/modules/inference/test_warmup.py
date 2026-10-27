"""Warm-up hints retain only a bounded set of model identities."""

import pytest

from app.modules.inference.warmup import WarmupRequests


class TestWarmupRequests:
    def test_bounds_pending_models_without_duplicate_work(self):
        requests = WarmupRequests()
        ids = [f"{i:064x}" for i in range(6)]
        for identity in ids:
            requests.request(identity)
        requests.request(ids[2])
        assert [requests.take() for _ in range(5)] == [
            ids[3],
            ids[4],
            ids[5],
            ids[2],
            None,
        ]

    def test_discards_pending_hints_on_clear(self):
        requests = WarmupRequests()
        requests.request("a" * 64)
        requests.clear()
        assert requests.take() is None

    @pytest.mark.parametrize("value", ["private query", "a" * 65, "../model"])
    def test_rejects_non_model_hints(self, value):
        with pytest.raises(ValueError, match="embedding_model_identity_invalid"):
            WarmupRequests().request(value)


class TestWaiting:
    def test_a_request_wakes_a_waiting_warmup(self):
        import threading

        requests = WarmupRequests()
        woken = []
        waiter = threading.Thread(target=lambda: woken.append(requests.wait(30)))
        waiter.start()

        requests.request("a" * 64)
        waiter.join(timeout=5)

        assert woken == [True]

    def test_an_unrequested_wait_runs_out(self):
        assert WarmupRequests().wait(0.01) is False

    def test_a_wake_ends_the_wait(self):
        requests = WarmupRequests()
        requests.wake()

        assert requests.wait(30) is True
