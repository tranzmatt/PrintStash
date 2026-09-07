"""Dashboard usage uses database evidence without enumerating storage."""

from app.modules.library.model_views import statistics
from app.modules.storage.storage_backend.runtime import get_backend


class TestVaultStats:
    def test_never_enumerates_storage(self, db_session, make_user, monkeypatch):
        backend = get_backend()

        def forbidden(*args, **kwargs):
            raise AssertionError("dashboard attempted remote enumeration")

        monkeypatch.setattr(backend, "usage", forbidden)
        result = statistics.vault_stats(db_session, make_user(superuser=True))
        assert result.storage.ok is True

    def test_reports_recorded_usage(
        self, db_session, make_user, make_owned_storage_object
    ):
        statistics._usage_cache.clear()
        make_owned_storage_object(size_bytes=23)
        result = statistics.vault_stats(db_session, make_user(superuser=True))
        assert result.storage.total_size_bytes == 23

    def test_refreshes_evidence_after_ttl(
        self, db_session, make_user, make_owned_storage_object, monkeypatch
    ):
        statistics._usage_cache.clear()
        clock = [1000.0]
        monkeypatch.setattr(statistics, "monotonic", lambda: clock[0])
        user = make_user(superuser=True)
        assert statistics.vault_stats(db_session, user).storage.total_size_bytes == 0
        make_owned_storage_object(size_bytes=24)
        clock[0] += statistics._USAGE_TTL_S + 1
        assert statistics.vault_stats(db_session, user).storage.total_size_bytes == 24
