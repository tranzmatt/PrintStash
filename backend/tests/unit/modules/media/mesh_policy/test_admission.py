"""Configuration changes must never create overlapping permit pools."""

import threading
from concurrent.futures import ThreadPoolExecutor

from app.core.config import _overlay
from app.modules.media import (
    mesh_policy,
)


class TestRenderAdmission:
    def test_release_progresses_during_waiter_checkpoint(self, monkeypatch) -> None:
        gate = mesh_policy.RenderAdmission()
        admitted = threading.Event()
        release = threading.Event()
        released = threading.Event()
        checkpoint_entered = threading.Event()
        checkpoint_finish = threading.Event()
        waiter_finished = threading.Event()
        errors = []

        def active_worker():
            try:
                with gate:
                    admitted.set()
                    assert release.wait(5)
                released.set()
            except BaseException as exc:
                errors.append(exc)

        def checkpoint():
            checkpoint_entered.set()
            assert checkpoint_finish.wait(5)

        def waiting_worker():
            try:
                with gate:
                    pass
                waiter_finished.set()
            except BaseException as exc:
                errors.append(exc)

        active = threading.Thread(target=active_worker)
        waiter = threading.Thread(target=waiting_worker)
        active.start()
        try:
            assert admitted.wait(5)
            monkeypatch.setattr(mesh_policy, "checkpoint", checkpoint)
            waiter.start()
            assert checkpoint_entered.wait(5)
            release.set()
            progressed = released.wait(1)
        finally:
            checkpoint_finish.set()
            release.set()
            active.join(5)
            if waiter.ident is not None:
                waiter.join(5)
        assert not active.is_alive()
        assert not waiter.is_alive()
        assert not errors
        assert waiter_finished.is_set()
        assert progressed
        assert gate.active == 0

    def test_config_change_waits_for_old_admissions_to_settle(self, monkeypatch):
        monkeypatch.setattr(mesh_policy, "_RENDER_SEMAPHORE", None)
        monkeypatch.setitem(_overlay, "max_render_jobs", 1)
        old_gate = mesh_policy.render_admission()
        old_gate.__enter__()
        entered = threading.Event()
        waiting = threading.Event()
        monkeypatch.setitem(_overlay, "max_render_jobs", 2)

        def new_work():
            gate = mesh_policy.render_admission()
            waiting.set()
            with gate:
                entered.set()
                return gate

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(new_work)
                assert waiting.wait(2)
                assert not entered.wait(0.1)
                old_gate.__exit__(None, None, None)
                assert entered.wait(2)
                assert result.result() is old_gate
        finally:
            if not entered.is_set():
                old_gate.__exit__(None, None, None)

    def test_disabling_estimates_keeps_divided_safety_budget(self, monkeypatch):
        from app.modules.media import mesh_isolation

        monkeypatch.setitem(_overlay, "mesh_memory_budget_fraction", 0)
        monkeypatch.setitem(_overlay, "max_render_jobs", 2)
        monkeypatch.setattr(mesh_policy, "detect_memory_limit_bytes", lambda: 1024**3)
        assert mesh_isolation.memory_budget_bytes() == 256 * 1024**2

    def test_native_fallback_is_divided_by_concurrency(self, monkeypatch):
        monkeypatch.setitem(_overlay, "max_render_jobs", 4)
        monkeypatch.setattr(mesh_policy, "detect_memory_limit_bytes", lambda: None)
        assert mesh_policy.native_memory_budget_bytes() == 256 * 1024**2

    def test_cancelled_waiter_releases_without_admission(self):
        import pytest

        from app.core.cancellation import (
            OperationCancelled,
            cancellation_scope,
        )

        gate = mesh_policy.RenderAdmission()
        entered = threading.Event()
        stopped = threading.Event()

        def waiting():
            with cancellation_scope(stopped.is_set):
                entered.set()
                with gate:
                    raise AssertionError("cancelled work admitted")

        with gate, ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(waiting)
            assert entered.wait(2)
            stopped.set()
            with pytest.raises(OperationCancelled):
                result.result(timeout=2)
            assert gate.active == 1
        assert gate.active == 0
