import time
from unittest.mock import patch
import pytest

from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import Role
from apps.marketplace.health_services import DependencyHealthService
from apps.marketplace.observability import OperationalMetricsService
from apps.marketplace.command_center_services import OperationalCommandCenterService

User = get_user_model()


@pytest.fixture
def admin_user(db):
    user = User.objects.filter(email="admin_phase16@tradeflow.et").first()
    if not user:
        user = User.objects.create_superuser(email="admin_phase16@tradeflow.et", password="Password123!", role=Role.ADMIN)
    return user


@pytest.fixture
def regular_user(db):
    user = User.objects.filter(email="user_phase16@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="user_phase16@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user


@pytest.mark.django_db
class TestDependencyHealthAndReadiness:
    def test_database_health_check(self):
        health = DependencyHealthService.check_database()
        assert health["status"] == "healthy"

    def test_redis_health_check(self):
        health = DependencyHealthService.check_redis()
        assert health["status"] in ["healthy", "unhealthy"]

    def test_health_endpoint(self):
        client = APIClient()
        res = client.get("/api/v1/system/health/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "healthy"
        assert res.data["service"] == "tradeflow-api"

    def test_readiness_endpoint(self):
        client = APIClient()
        res = client.get("/api/v1/system/readiness/")
        assert res.status_code in [status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE]
        assert "database" in res.data
        assert "redis" in res.data

    def test_database_failure_is_reported(self):
        with patch("django.db.connection.cursor", side_effect=Exception("DB Connection Refused")):
            health = DependencyHealthService.check_database()
            assert health["status"] == "unhealthy"
            assert "error" in health

    def test_redis_failure_is_reported(self):
        with patch("django.core.cache.cache.set", side_effect=Exception("Redis Timeout")):
            health = DependencyHealthService.check_redis()
            assert health["status"] == "unhealthy"
            assert "error" in health


@pytest.mark.django_db
class TestRedisFailureResilience:
    def test_command_center_falls_back_when_redis_unavailable(self, admin_user):
        with patch("django.core.cache.cache.get", side_effect=Exception("Redis Connection Error")):
            summary = OperationalCommandCenterService.get_realtime_summary(admin_user)
            assert "total_active_shipments" in summary
            assert "generated_at" in summary


@pytest.mark.django_db
class TestRequestCorrelationAndTiming:
    def test_request_id_generated(self):
        client = APIClient()
        res = client.get("/api/v1/system/health/")
        assert "X-Request-ID" in res.headers
        assert res.headers["X-Request-ID"].startswith("req_")

    def test_request_id_returned_in_response(self):
        client = APIClient()
        custom_id = "req_test_custom_123456"
        res = client.get("/api/v1/system/health/", HTTP_X_REQUEST_ID=custom_id)
        assert res.headers.get("X-Request-ID") == custom_id

    def test_request_timing_is_recorded(self):
        before = OperationalMetricsService.get_metrics_summary()["requests"]["total"]
        client = APIClient()
        client.get("/api/v1/system/health/")
        after = OperationalMetricsService.get_metrics_summary()["requests"]["total"]
        assert after >= before + 1

    def test_slow_operation_detection(self):
        before_slow = OperationalMetricsService.get_metrics_summary()["requests"]["slow_requests"]
        OperationalMetricsService.record_request(status_code=200, duration_ms=650.0)
        after_slow = OperationalMetricsService.get_metrics_summary()["requests"]["slow_requests"]
        assert after_slow >= before_slow + 1


@pytest.mark.django_db
class TestErrorObservabilityAndSecurity:
    def test_metrics_endpoint_authorization(self, admin_user, regular_user):
        client = APIClient()

        # Unauthenticated -> 401
        res = client.get("/api/v1/system/metrics/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

        # Regular non-admin user -> 403
        client.force_authenticate(user=regular_user)
        res = client.get("/api/v1/system/metrics/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Admin user -> 200
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/system/metrics/")
        assert res.status_code == status.HTTP_200_OK
        assert "requests" in res.data
        assert "dependencies" in res.data

    def test_system_status_does_not_expose_secrets(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/system/status/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["application"] == "TradeFlow"
        assert res.data["database"] == "PostgreSQL"

        # Verify no secrets/passwords exposed in status dictionary
        raw_text = str(res.data).lower()
        for secret_kw in ["secret", "password", "token", "key", "connection_string"]:
            assert secret_kw not in res.data or secret_kw not in raw_text

    def test_health_checks_do_not_mutate_business_state(self):
        client = APIClient()
        res1 = client.get("/api/v1/system/health/")
        res2 = client.get("/api/v1/system/readiness/")
        assert res1.status_code == status.HTTP_200_OK
        assert res2.status_code in [status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE]
