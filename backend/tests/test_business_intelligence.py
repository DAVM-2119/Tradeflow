import pytest
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import Role
from apps.marketplace.models import (
    CargoLoad, LoadStatus, Shipment, ShipmentStatus,
    Payment, PaymentStatus, FreightInvoice, FreightSettlement, SettlementStatus,
    DriverIncidentReport, IncidentType,
    AutomationRecommendation, RecommendationStatus,
    OperationalEvent, EventSeverity, Notification
)

from apps.marketplace.analytics_services import BusinessIntelligenceService

User = get_user_model()


@pytest.fixture
def admin_user(db):
    user = User.objects.filter(email="admin_p17@tradeflow.et").first()
    if not user:
        user = User.objects.create_superuser(email="admin_p17@tradeflow.et", password="Password123!", role=Role.ADMIN)
    return user


@pytest.fixture
def shipper_user(db):
    user = User.objects.filter(email="shipper_p17@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="shipper_p17@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user


@pytest.fixture
def unrelated_user(db):
    user = User.objects.filter(email="unrelated_p17@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="unrelated_p17@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user


@pytest.mark.django_db
class TestAnalyticsDashboardAndScoping:
    def test_dashboard_overview(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/dashboard/")
        assert res.status_code == status.HTTP_200_OK
        assert "shipments" in res.data
        assert "delivery_performance" in res.data
        assert "financial" in res.data
        assert "risk" in res.data

    def test_dashboard_role_scoping(self, shipper_user, unrelated_user):
        client = APIClient()
        client.force_authenticate(user=shipper_user)
        res_shipper = client.get("/api/v1/analytics/dashboard/")
        assert res_shipper.status_code == status.HTTP_200_OK

        client.force_authenticate(user=unrelated_user)
        res_unrelated = client.get("/api/v1/analytics/dashboard/")
        assert res_unrelated.status_code == status.HTTP_200_OK

    def test_dashboard_empty_data(self, shipper_user):
        data = BusinessIntelligenceService.get_dashboard_overview(shipper_user)
        assert data["shipments"]["total"] == 0
        assert data["delivery_performance"]["on_time_rate"] == 1.0


@pytest.mark.django_db
class TestShipmentAndDeliveryAnalytics:
    def test_shipment_status_distribution(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/shipments/")
        assert res.status_code == status.HTTP_200_OK
        assert "status_distribution" in res.data
        assert "completion_rate" in res.data

    def test_delivery_performance_rates(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/delivery-performance/")
        assert res.status_code == status.HTTP_200_OK
        assert "on_time_delivery_rate" in res.data
        assert "average_delay_minutes" in res.data


@pytest.mark.django_db
class TestFinancialAnalyticsDecimalSafety:
    def test_financial_totals_use_decimal(self, admin_user):
        data = BusinessIntelligenceService.get_financial_analytics(admin_user)
        assert isinstance(data["total_invoiced_etb"], Decimal)
        assert isinstance(data["total_settled_etb"], Decimal)
        assert isinstance(data["total_paid_etb"], Decimal)

    def test_financial_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/financial/")
        assert res.status_code == status.HTTP_200_OK
        assert "total_invoiced_etb" in res.data


@pytest.mark.django_db
class TestMarketRiskAndIncidentAnalytics:
    def test_market_analytics_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/market/")
        assert res.status_code == status.HTTP_200_OK
        assert "data_available" in res.data

    def test_risk_analytics_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/risk/")
        assert res.status_code == status.HTTP_200_OK
        assert "average_risk_score" in res.data

    def test_incident_analytics_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/incidents/")
        assert res.status_code == status.HTTP_200_OK
        assert "total_incidents" in res.data


@pytest.mark.django_db
class TestAutomationAndZeroDenominatorProtection:
    def test_zero_denominator_protection(self, admin_user):
        data = BusinessIntelligenceService.get_automation_analytics(admin_user)
        assert data["approval_rate"] == 0.0
        assert data["execution_rate"] == 0.0
        assert data["failure_rate"] == 0.0

    def test_automation_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/automation/")
        assert res.status_code == status.HTTP_200_OK
        assert "approval_rate" in res.data


@pytest.mark.django_db
class TestEventsCorridorsAndTopPerformers:
    def test_event_analytics_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/events/")
        assert res.status_code == status.HTTP_200_OK
        assert "total_operational_events" in res.data

    def test_corridor_analytics_endpoint(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/corridors/")
        assert res.status_code == status.HTTP_200_OK
        assert "corridors" in res.data

    def test_top_performers_deterministic(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/top-performers/")
        assert res.status_code == status.HTTP_200_OK
        assert "top_transporters" in res.data
        assert "top_drivers" in res.data


@pytest.mark.django_db
class TestTrendsAndReportsExport:
    def test_shipment_trend_analytics(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/trends/?metric=shipments&period=30d")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["metric"] == "shipments"
        assert "data" in res.data

    def test_invalid_metric_rejected(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/trends/?metric=invalid_metric")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_period_rejected(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/dashboard/?period=invalid_period")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_custom_date_range_validation(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        # Invalid start > end
        res = client.get("/api/v1/analytics/dashboard/?period=custom&start_date=2026-08-30T00:00:00Z&end_date=2026-08-01T00:00:00Z")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_executive_report_json(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/reports/executive/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["report_type"] == "executive"

    def test_csv_export(self, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)
        res = client.get("/api/v1/analytics/reports/executive/?format=csv")
        assert res.status_code == status.HTTP_200_OK
        assert res["Content-Type"] == "text/csv"
        assert "Report Type" in res.content.decode("utf-8")


@pytest.mark.django_db
class TestRedisResilienceAndNonMutation:
    def test_analytics_fallback_when_redis_unavailable(self, admin_user):
        with patch("django.core.cache.cache.get", side_effect=Exception("Redis connection lost")):
            data = BusinessIntelligenceService.get_dashboard_overview(admin_user)
            assert "shipments" in data

    def test_unauthenticated_access_rejected(self):
        client = APIClient()
        res = client.get("/api/v1/analytics/dashboard/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_analytics_requests_do_not_mutate_business_state(self, admin_user):
        load_count_before = CargoLoad.objects.count()
        shipment_count_before = Shipment.objects.count()

        client = APIClient()
        client.force_authenticate(user=admin_user)
        client.get("/api/v1/analytics/dashboard/")
        client.get("/api/v1/analytics/shipments/")
        client.get("/api/v1/analytics/financial/")
        client.get("/api/v1/analytics/risk/")
        client.get("/api/v1/analytics/reports/executive/?format=csv")

        assert CargoLoad.objects.count() == load_count_before
        assert Shipment.objects.count() == shipment_count_before
