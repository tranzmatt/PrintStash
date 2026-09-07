"""Capacity admission never lets concurrent owners spend the same free bytes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlmodel import SQLModel, create_engine

from app.core.errors import OperationError
from app.db.session import SQLiteSessionFactory, get_session_factory
from app.modules.storage.capacity import CapacityManager, CapacityResource


class TestCapacityManager:
    def test_denies_combined_allocations_on_one_volume(self, db_session):
        manager = CapacityManager(get_session_factory(), headroom_bytes=10)
        resources = [
            CapacityResource.for_quota("one", 50, 100, role=role)
            for role in ("input", "output")
        ]
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            manager.reserve("upload", resources)

    def test_preserves_exact_headroom(self, db_session):
        manager = CapacityManager(get_session_factory(), headroom_bytes=10)
        reservation = manager.reserve(
            "upload", [CapacityResource.for_quota("one", 90, 100, role="input")]
        )
        assert manager.reserved_bytes() == {"quota:one": 90}
        reservation.release()
        assert manager.reserved_bytes() == {}

    def test_retains_unknown_quota_warning(self, db_session):
        manager = CapacityManager(get_session_factory(), headroom_bytes=10)
        reservation = manager.reserve(
            "upload", [CapacityResource.for_quota("remote", 90, None, role="vault")]
        )
        assert reservation.warnings == ("capacity_unknown:quota:remote",)

    def test_rejects_changed_operation_identity(self, db_session):
        manager = CapacityManager(get_session_factory(), headroom_bytes=0)
        manager.reserve(
            "upload", [CapacityResource.for_quota("one", 20, 100, role="input")]
        )
        with pytest.raises(OperationError, match="capacity_operation_conflict"):
            manager.reserve(
                "upload", [CapacityResource.for_quota("one", 30, 100, role="input")]
            )

    def test_releases_after_operation_failure(self, db_session):
        manager = CapacityManager(get_session_factory(), headroom_bytes=0)
        with pytest.raises(ValueError):
            with manager.hold(
                "upload", [CapacityResource.for_quota("one", 20, 100, role="input")]
            ):
                raise ValueError("failed")
        assert manager.reserved_bytes() == {}

    def test_rechecks_before_larger_allocation(self, db_session):
        manager = CapacityManager(get_session_factory(), headroom_bytes=0)
        handle = manager.reserve(
            "upload", [CapacityResource.for_quota("one", 20, 100, role="input")]
        )
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            handle.renew([CapacityResource.for_quota("one", 101, 100, role="input")])
        assert manager.reserved_bytes() == {"quota:one": 20}

    def test_serializes_competing_reservations(self, tmp_path):
        engine = create_engine(
            f"sqlite:///{tmp_path / 'capacity.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(engine)
        manager = CapacityManager(SQLiteSessionFactory(engine), headroom_bytes=0)
        barrier = Barrier(2)

        def reserve(owner):
            barrier.wait()
            try:
                manager.reserve(
                    owner, [CapacityResource.for_quota("one", 60, 100, role="input")]
                )
                return True
            except OperationError:
                return False

        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(reserve, ["first", "second"]))
        assert sorted(outcomes) == [False, True]
        assert manager.reserved_bytes() == {"quota:one": 60}
        engine.dispose()

    def test_resolves_shared_filesystem_identity(self, tmp_path):
        first = CapacityResource.for_path(tmp_path / "input", 10, role="input")
        second = CapacityResource.for_path(tmp_path / "output", 20, role="output")
        assert first.domain_id == second.domain_id

    def test_reconciles_expired_terminal_owner(
        self, db_session, make_capacity_reservation
    ):
        make_capacity_reservation(expired=True)
        manager = CapacityManager(get_session_factory(), headroom_bytes=0)
        assert manager.reconcile(lambda operation_id: False) == 1
        assert manager.reserved_bytes() == {}

    def test_retains_expired_active_owner(self, db_session, make_capacity_reservation):
        make_capacity_reservation(expired=True)
        manager = CapacityManager(get_session_factory(), headroom_bytes=0)
        assert manager.reconcile(lambda operation_id: True) == 0
        assert manager.reserved_bytes() == {"quota:test": 10}

    def test_retains_unexpired_owner(self, db_session, make_capacity_reservation):
        make_capacity_reservation()
        manager = CapacityManager(get_session_factory(), headroom_bytes=0)
        assert manager.reconcile(lambda operation_id: False) == 0
        assert manager.reserved_bytes() == {"quota:test": 10}
