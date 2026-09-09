"""Defend peak audit reservations so verification cannot overcommit scratch space."""

from app.db.models import VaultAuditMode
from app.modules.administration.vault_audit_capacity import estimate_resources


class TestEstimateResources:
    def test_estimates_sequential_source_peak(
        self, db_session, make_user, make_model, make_file, make_audit_run
    ):
        model = make_model()
        make_file(model, size_bytes=100)
        make_file(model, size_bytes=300)
        run = make_audit_run(make_user())
        assert estimate_resources(db_session, run)[0].required_bytes == 300

    def test_includes_backup_allocation(
        self, db_session, make_user, make_audit_run, make_owned_storage_object
    ):
        make_owned_storage_object(object_kind="backup", size_bytes=500)
        run = make_audit_run(make_user(), mode=VaultAuditMode.FULL)
        resources = estimate_resources(db_session, run)
        assert resources[1].required_bytes == 1000
