import hashlib
import json
import pytest

from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import Role
from apps.marketplace.models import (
    SecurityAuditEvent, SecurityAuditEventSeverity, SecurityAuditEventType,
    SecurityIncident, SecurityIncidentStatus, SecurityIncidentType,
    SecurityPolicy, CargoLoad, Shipment
)
from apps.marketplace.security_services import SecurityGovernanceService

User = get_user_model()


@pytest.fixture
def admin_user(db):
    user = User.objects.filter(email="admin_sec_p19@tradeflow.et").first()
    if not user:
        user = User.objects.create_superuser(email="admin_sec_p19@tradeflow.et", password="Password123!", role=Role.ADMIN)
    return user


@pytest.fixture
def shipper_user(db):
    user = User.objects.filter(email="shipper_sec_p19@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="shipper_sec_p19@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user


@pytest.fixture
def sample_audit_events(admin_user, shipper_user):
    e1 = SecurityGovernanceService.record_audit_event(
        event_type=SecurityAuditEventType.LOGIN_SUCCESS,
        action="USER_LOGIN",
        actor=admin_user,
        description="Admin login successful"
    )
    e2 = SecurityGovernanceService.record_audit_event(
        event_type=SecurityAuditEventType.ROLE_CHANGED,
        action="UPDATE_USER_ROLE",
        actor=admin_user,
        target_user=shipper_user,
        description="Updated shipper role"
    )
    return [e1, e2]


@pytest.mark.django_db
class TestAuditEventsAndHashing:
    def test_audit_event_creation(self, admin_user):
        evt = SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.LOGIN_SUCCESS,
            action="USER_LOGIN",
            actor=admin_user,
            description="Login from office IP"
        )
        assert evt.id is not None
        assert evt.actor == admin_user
        assert evt.event_hash != ""

    def test_audit_event_detail_view(self, admin_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        evt_id = sample_audit_events[0].id
        res = client.get(f"/api/v1/security/events/{evt_id}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["id"] == evt_id

    def test_sha256_hash_chaining(self, admin_user, shipper_user):
        e1 = SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.LOGIN_SUCCESS,
            action="LOGIN",
            actor=admin_user
        )
        e2 = SecurityGovernanceService.record_audit_event(
            event_type=SecurityAuditEventType.USER_UPDATED,
            action="UPDATE_PROFILE",
            actor=admin_user,
            target_user=shipper_user
        )
        assert e2.previous_hash == e1.event_hash
        assert SecurityGovernanceService.verify_audit_event_integrity(e2) is True

    def test_audit_chain_verification_valid(self, sample_audit_events):
        res = SecurityGovernanceService.verify_audit_chain()
        assert res["status"] == "valid"
        assert res["chain_valid"] is True
        assert res["invalid_events"] == 0

    def test_corrupted_audit_event_detection(self, sample_audit_events):
        target = sample_audit_events[0]
        SecurityAuditEvent.objects.filter(id=target.id).update(description="TAMPERED DESCRIPTION")
        res = SecurityGovernanceService.verify_audit_chain()
        assert res["status"] == "corrupted"
        assert res["chain_valid"] is False
        assert res["invalid_events"] >= 1

    def test_audit_chain_verification_corrupted_previous_hash(self, sample_audit_events):
        target = sample_audit_events[1]
        SecurityAuditEvent.objects.filter(id=target.id).update(previous_hash="invalid_prev_hash_12345")
        res = SecurityGovernanceService.verify_audit_chain()
        assert res["chain_valid"] is False


@pytest.mark.django_db
class TestAuthenticationAndAuthorizationAuditing:
    def test_authorization_rejected_for_non_admins(self, shipper_user):
        client = APIClient()
        client.force_authenticate(user=shipper_user)

        res_overview = client.get("/api/v1/security/overview/")
        assert res_overview.status_code == status.HTTP_403_FORBIDDEN

        res_events = client.get("/api/v1/security/events/")
        assert res_events.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_security_endpoints_rejected(self):
        client = APIClient()
        res = client.get("/api/v1/security/overview/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_security_overview_endpoint(self, admin_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/overview/")
        assert res.status_code == status.HTTP_200_OK
        assert "total_security_events" in res.data
        assert res.data["audit_integrity_status"] == "valid"


@pytest.mark.django_db
class TestSecurityIncidentsAndPolicies:
    def test_incident_creation_and_lifecycle(self, admin_user):
        inc = SecurityIncident.objects.create(
            incident_type=SecurityIncidentType.BRUTE_FORCE,
            severity=SecurityAuditEventSeverity.HIGH,
            title="Brute Force Alert",
            description="5 failed logins from IP 192.168.1.100"
        )
        client = APIClient()
        client.force_authenticate(user=admin_user)

        res_list = client.get("/api/v1/security/incidents/")
        assert res_list.status_code == status.HTTP_200_OK
        assert len(res_list.data) >= 1

        res_det = client.get(f"/api/v1/security/incidents/{inc.id}/")
        assert res_det.status_code == status.HTTP_200_OK

        res_assign = client.post(f"/api/v1/security/incidents/{inc.id}/assign/", {"assigned_to_id": admin_user.id})
        assert res_assign.status_code == status.HTTP_200_OK
        assert res_assign.data["status"] == SecurityIncidentStatus.INVESTIGATING

        res_resolve = client.post(f"/api/v1/security/incidents/{inc.id}/resolve/", {"resolution_notes": "Blocked IP address"})
        assert res_resolve.status_code == status.HTTP_200_OK
        assert res_resolve.data["status"] == SecurityIncidentStatus.RESOLVED

    def test_incident_dismiss_view(self, admin_user):
        inc = SecurityIncident.objects.create(
            incident_type=SecurityIncidentType.SUSPICIOUS_LOGIN,
            severity=SecurityAuditEventSeverity.LOW,
            title="Suspicious Login IP",
            description="VPN login detected"
        )
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.post(f"/api/v1/security/incidents/{inc.id}/dismiss/", {"resolution_notes": "Verified VPN user"})
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == SecurityIncidentStatus.DISMISSED

    def test_security_policy_creation_and_update(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        payload = {
            "name": "Failed Login Threshold Policy",
            "policy_type": "FAILED_LOGIN_THRESHOLD",
            "threshold": 5,
            "window_seconds": 300,
            "severity": "HIGH"
        }
        res = client.post("/api/v1/security/policies/", payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        pol_id = res.data["id"]

        res_upd = client.patch(f"/api/v1/security/policies/{pol_id}/", {"threshold": 10}, format="json")
        assert res_upd.status_code == status.HTTP_200_OK
        assert res_upd.data["threshold"] == 10

    def test_security_policy_list_view(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/policies/")
        assert res.status_code == status.HTTP_200_OK

    def test_security_incident_detection_service(self):
        for _ in range(6):
            SecurityGovernanceService.record_audit_event(
                event_type=SecurityAuditEventType.LOGIN_FAILURE,
                action="LOGIN_FAILED",
                request=None,
                metadata={"ip_address": "10.0.0.99"}
            )
        # Manually create auditing event with ip_address
        SecurityAuditEvent.objects.filter(event_type=SecurityAuditEventType.LOGIN_FAILURE).update(ip_address="10.0.0.99")
        incidents = SecurityGovernanceService.detect_security_incidents()
        assert len(incidents) >= 1
        assert incidents[0].incident_type == SecurityIncidentType.BRUTE_FORCE


@pytest.mark.django_db
class TestSecretSanitizationAndDataAuditing:
    def test_secret_sanitization_nested_dicts_and_lists(self):
        raw_meta = {
            "user": "test_user",
            "password": "SuperSecretPassword123!",
            "tokens": {"access_token": "jwt_access_abc123", "public_id": 99},
            "secrets_list": [{"webhook_secret": "whsec_123"}, {"api_key": "key_456"}]
        }
        sanitized = SecurityGovernanceService.sanitize_metadata(raw_meta)
        assert sanitized["password"] == "********"
        assert sanitized["tokens"]["access_token"] == "********"
        assert sanitized["tokens"]["public_id"] == 99
        assert sanitized["secrets_list"][0]["webhook_secret"] == "********"
        assert sanitized["secrets_list"][1]["api_key"] == "********"

    def test_sensitive_data_access_auditing(self, admin_user):
        evt = SecurityGovernanceService.record_data_access(
            actor=admin_user,
            resource_type="FreightSettlement",
            resource_id=50,
            action="READ"
        )
        assert evt.event_type == SecurityAuditEventType.SENSITIVE_DATA_ACCESSED
        assert evt.target_model == "FreightSettlement"
        assert evt.target_object_id == "50"


@pytest.mark.django_db
class TestReportsAndCsvExport:
    def test_compliance_report_json(self, admin_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/reports/AUTHENTICATION/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["report_type"] == "AUTHENTICATION"
        assert "records" in res.data

    def test_compliance_report_privilege_changes(self, admin_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/reports/PRIVILEGE_CHANGES/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["report_type"] == "PRIVILEGE_CHANGES"

    def test_compliance_report_security_incidents(self, admin_user):
        SecurityIncident.objects.create(
            incident_type=SecurityIncidentType.POLICY_VIOLATION,
            severity=SecurityAuditEventSeverity.MEDIUM,
            title="Policy Violation"
        )
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/reports/SECURITY_INCIDENTS/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["report_type"] == "SECURITY_INCIDENTS"

    def test_compliance_report_csv_export(self, admin_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/reports/AUTHENTICATION/?format=csv")
        assert res.status_code == status.HTTP_200_OK
        assert res.headers["Content-Type"] == "text/csv"
        assert "tradeflow_compliance_report" in res.headers["Content-Disposition"]
        assert b"TRADEFLOW SECURITY COMPLIANCE REPORT" in res.content

    def test_audit_integrity_api_endpoint(self, admin_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/audit-integrity/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["chain_valid"] is True
        assert res.data["invalid_events"] == 0

    def test_user_security_history_api(self, admin_user, shipper_user, sample_audit_events):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get(f"/api/v1/security/users/{shipper_user.id}/history/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["user_email"] == shipper_user.email
        assert len(res.data["recent_events"]) >= 1

    def test_user_security_history_nonexistent_user(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/security/users/999999/history/")
        assert res.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestNonMutationAndResilience:
    def test_security_apis_do_not_mutate_business_state(self, admin_user):
        load_count_before = CargoLoad.objects.count()
        shipment_count_before = Shipment.objects.count()

        client = APIClient()
        client.force_authenticate(user=admin_user)
        client.get("/api/v1/security/overview/")
        client.get("/api/v1/security/events/")
        client.get("/api/v1/security/audit-integrity/")

        assert CargoLoad.objects.count() == load_count_before
        assert Shipment.objects.count() == shipment_count_before

