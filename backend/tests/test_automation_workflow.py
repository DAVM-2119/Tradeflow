import pytest
from datetime import date, timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, Role, ShipperProfile, TransporterProfile, DriverProfile
from apps.marketplace.models import (
    Vehicle,
    CargoLoad,
    LoadStatus,
    Bid,
    BidStatus,
    Shipment,
    ShipmentStatus,
    LocationUpdate,
    DriverIncidentReport,
    IncidentType,
    AutomationRule,
    AutomationRecommendation,
    AutomationExecution,
    RecommendationPriority,
    RecommendationStatus,
    AutomationRuleType,
    AutomationRecommendationType,
)
from apps.marketplace.services import BiddingService, TrackingService
from apps.marketplace.automation_services import AutomationService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def shipper_user(db):
    user = User.objects.create_user(email="shipper_phase13@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    ShipperProfile.objects.create(user=user, company_name="Ethiopian Coffee Exporters PLC", trade_license_number="TL-ECE-13", tax_id="TIN-ECE-13")
    return user


@pytest.fixture
def transporter_user(db):
    user = User.objects.create_user(email="transporter_phase13@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    TransporterProfile.objects.create(
        user=user,
        company_name="Abyssinia Logistics PLC",
        trade_license_number="TL-ABY-13",
        tax_id="TIN-ABY-13",
        verification_status="VERIFIED"
    )
    return user



@pytest.fixture
def driver_user(db, transporter_user):
    user = User.objects.create_user(email="driver_phase13@tradeflow.et", password="Password123!", role=Role.DRIVER)
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number="DL-ETH-1313"
    )
    return user



@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(email="admin_phase13@tradeflow.et", password="AdminPassword123!", role=Role.ADMIN)


@pytest.fixture
def vehicle(db, transporter_user):
    return Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number="ET-3-99999",
        vehicle_type="Heavy Freight Truck",
        capacity_tonnes=40.00,
        fuel_type="Diesel",
        is_active=True
    )


@pytest.fixture
def active_shipment(db, shipper_user, transporter_user, driver_user, vehicle):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Sesame Seed Export",
        origin="Gonder",
        destination="Modjo Dry Port",
        cargo_type="Agriculture",
        weight_tonnes=30.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=120000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(load=load, transporter=transporter_user.transporter_profile, proposed_vehicle=vehicle, amount=115000.00, status=BidStatus.SUBMITTED)
    BiddingService.accept_bid(shipper_user, bid)
    shipment = load.shipment
    TrackingService.assign_driver(shipment, driver_user.driver_profile, transporter_user)
    return shipment


@pytest.mark.django_db
class TestAutomationRuleModel:
    def test_default_rules_creation(self):
        rules = AutomationService.get_or_create_default_rules()
        assert len(rules) >= 7
        assert AutomationRule.objects.filter(rule_type=AutomationRuleType.HIGH_OPERATIONAL_RISK).exists()
        assert AutomationRule.objects.filter(rule_type=AutomationRuleType.ROUTE_DEVIATION).exists()

    def test_rule_uniqueness(self):
        AutomationRule.objects.create(name="Unique Rule Test", rule_type=AutomationRuleType.HIGH_OPERATIONAL_RISK)
        with pytest.raises(Exception):
            AutomationRule.objects.create(name="Unique Rule Test", rule_type=AutomationRuleType.ROUTE_DEVIATION)


@pytest.mark.django_db
class TestRuleEvaluation:
    def test_high_operational_risk_evaluation(self, active_shipment):
        eval_result = AutomationService.evaluate_shipment(active_shipment)
        assert eval_result["evaluated_rules"] >= 7
        assert eval_result["recommendations_created"] >= 0

    def test_incident_reported_rule_evaluation(self, active_shipment, driver_user):
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.ROAD_PROBLEM,
            description="Landslide blocking corridor roadway near Gonder.",
            reported_at=timezone.now(),
            latitude=12.60,
            longitude=37.46
        )

        eval_result = AutomationService.evaluate_shipment(active_shipment)
        incident_recs = [r for r in eval_result["recommendations"] if r.recommendation_type == AutomationRecommendationType.REVIEW_INCIDENT]
        assert len(incident_recs) == 1
        rec = incident_recs[0]
        assert rec.status == RecommendationStatus.PENDING
        assert "Landslide blocking corridor" in rec.description

    def test_stale_gps_telemetry_evaluation(self, active_shipment, driver_user):
        active_shipment.status = ShipmentStatus.IN_TRANSIT
        active_shipment.save()

        LocationUpdate.objects.create(
            shipment=active_shipment,
            recorded_by=driver_user,
            latitude=11.50,
            longitude=38.20,
            timestamp=timezone.now() - timedelta(hours=5)
        )

        eval_result = AutomationService.evaluate_shipment(active_shipment)
        stale_recs = [r for r in eval_result["recommendations"] if r.rule.rule_type == AutomationRuleType.STALE_GPS_DATA]
        assert len(stale_recs) == 1
        rec = stale_recs[0]
        assert rec.priority == RecommendationPriority.HIGH
        assert rec.context_snapshot["hours_since_gps"] >= 4.9


@pytest.mark.django_db
class TestDuplicatePrevention:
    def test_duplicate_pending_recommendation_prevention(self, active_shipment, driver_user):
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.CHECKPOINT_DELAY,
            description="Customs inspection checkpoint delay.",
            reported_at=timezone.now(),
            latitude=11.60,
            longitude=38.30
        )


        eval1 = AutomationService.evaluate_shipment(active_shipment)
        created1 = eval1["recommendations_created"]
        assert created1 >= 1

        # Second evaluation for same shipment
        eval2 = AutomationService.evaluate_shipment(active_shipment)
        assert eval2["recommendations_created"] == 0
        assert eval2["recommendations_existing"] >= created1


@pytest.mark.django_db
class TestApprovalAndExecutionLifecycle:
    def test_approve_recommendation_success(self, active_shipment, shipper_user):
        AutomationService.get_or_create_default_rules()
        rule = AutomationRule.objects.first()

        rec = AutomationRecommendation.objects.create(
            shipment=active_shipment,
            rule=rule,
            recommendation_type=AutomationRecommendationType.REVIEW_SHIPMENT,
            priority=RecommendationPriority.HIGH,
            status=RecommendationStatus.PENDING,
            title="Operational Review Needed",
            description="Review required.",
            recommended_action="Acknowledge review."
        )

        approved_rec = AutomationService.approve_recommendation(rec.id, shipper_user)
        assert approved_rec.status == RecommendationStatus.APPROVED
        assert approved_rec.reviewed_by == shipper_user
        assert approved_rec.reviewed_at is not None

    def test_reject_recommendation_success(self, active_shipment, transporter_user):
        AutomationService.get_or_create_default_rules()
        rule = AutomationRule.objects.first()

        rec = AutomationRecommendation.objects.create(
            shipment=active_shipment,
            rule=rule,
            recommendation_type=AutomationRecommendationType.REVIEW_ROUTE,
            priority=RecommendationPriority.MEDIUM,
            status=RecommendationStatus.PENDING,
            title="Route Review Suggested",
            description="Review route.",
            recommended_action="Check route."
        )

        rejected_rec = AutomationService.reject_recommendation(rec.id, transporter_user, reason="Route is optimal.")
        assert rejected_rec.status == RecommendationStatus.REJECTED
        assert rejected_rec.rejection_reason == "Route is optimal."
        assert rejected_rec.reviewed_by == transporter_user

    def test_execute_approved_recommendation_success(self, active_shipment, shipper_user):
        AutomationService.get_or_create_default_rules()
        rule = AutomationRule.objects.first()

        rec = AutomationRecommendation.objects.create(
            shipment=active_shipment,
            rule=rule,
            recommendation_type=AutomationRecommendationType.CONTACT_DRIVER,
            priority=RecommendationPriority.HIGH,
            status=RecommendationStatus.PENDING,
            title="Contact Driver Alert",
            description="Contact driver.",
            recommended_action="Call driver."
        )

        AutomationService.approve_recommendation(rec.id, shipper_user)
        execution = AutomationService.execute_recommendation(rec.id, shipper_user)

        assert execution.status == "SUCCESS"
        assert execution.executed_by == shipper_user
        assert execution.action_type == AutomationRecommendationType.CONTACT_DRIVER
        assert AutomationExecution.objects.filter(recommendation=rec).count() == 1

        rec.refresh_from_db()
        assert rec.status == RecommendationStatus.EXECUTED

    def test_cannot_execute_pending_or_rejected_recommendation(self, active_shipment, shipper_user):
        rec = AutomationRecommendation.objects.create(
            shipment=active_shipment,
            recommendation_type=AutomationRecommendationType.REVIEW_SHIPMENT,
            status=RecommendationStatus.PENDING,
            title="Pending Rec",
            description="Desc",
            recommended_action="Action"
        )

        with pytest.raises(Exception):
            AutomationService.execute_recommendation(rec.id, shipper_user)


@pytest.mark.django_db
class TestPricingRESTAPI:
    def test_evaluate_shipment_automation_endpoint(self, api_client, shipper_user, active_shipment):
        api_client.force_authenticate(user=shipper_user)
        url = f"/api/v1/shipments/{active_shipment.id}/automation/evaluate/"
        res = api_client.post(url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["shipment_id"] == active_shipment.id
        assert "evaluated_rules" in res.data
        assert "recommendations" in res.data

    def test_list_shipment_automation_recommendations_endpoint(self, api_client, transporter_user, active_shipment):
        AutomationService.evaluate_shipment(active_shipment)
        api_client.force_authenticate(user=transporter_user)
        url = f"/api/v1/shipments/{active_shipment.id}/automation/"
        res = api_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        assert isinstance(res.data["results"], list)

    def test_approve_reject_execute_api_flow(self, api_client, shipper_user, active_shipment):
        AutomationService.get_or_create_default_rules()
        rule = AutomationRule.objects.first()

        rec = AutomationRecommendation.objects.create(
            shipment=active_shipment,
            rule=rule,
            recommendation_type=AutomationRecommendationType.REVIEW_SHIPMENT,
            priority=RecommendationPriority.HIGH,
            status=RecommendationStatus.PENDING,
            title="API Approve Test",
            description="Desc",
            recommended_action="Action"
        )

        api_client.force_authenticate(user=shipper_user)

        # Approve
        approve_url = f"/api/v1/automation/recommendations/{rec.id}/approve/"
        res = api_client.post(approve_url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == RecommendationStatus.APPROVED

        # Execute
        exec_url = f"/api/v1/automation/recommendations/{rec.id}/execute/"
        res = api_client.post(exec_url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "SUCCESS"

    def test_admin_list_rules_endpoint(self, api_client, admin_user, shipper_user):
        AutomationService.get_or_create_default_rules()

        # Admin access
        api_client.force_authenticate(user=admin_user)
        res = api_client.get("/api/v1/automation/rules/")
        assert res.status_code == status.HTTP_200_OK

        # Non-admin rejected
        api_client.force_authenticate(user=shipper_user)
        res = api_client.get("/api/v1/automation/rules/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthorized_user_cannot_access_shipment_automation(self, api_client, active_shipment):
        unauth_user = User.objects.create_user(email="unauth_phase13@tradeflow.et", password="Password123!", role=Role.SHIPPER)
        ShipperProfile.objects.create(user=unauth_user, company_name="Other Exporters PLC", trade_license_number="TL-OTH-13", tax_id="TIN-OTH-13")

        api_client.force_authenticate(user=unauth_user)
        res = api_client.post(f"/api/v1/shipments/{active_shipment.id}/automation/evaluate/")
        assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestSecurityAndNonMutation:
    def test_forged_reviewed_by_and_executed_by_ignored(self, api_client, shipper_user, active_shipment):
        rec = AutomationRecommendation.objects.create(
            shipment=active_shipment,
            recommendation_type=AutomationRecommendationType.REVIEW_PRICING,
            status=RecommendationStatus.PENDING,
            title="Security Test",
            description="Desc",
            recommended_action="Action"
        )

        api_client.force_authenticate(user=shipper_user)
        approve_url = f"/api/v1/automation/recommendations/{rec.id}/approve/"
        # Client tries to inject reviewed_by = 999
        res = api_client.post(approve_url, {"reviewed_by": 999}, format='json')
        assert res.status_code == status.HTTP_200_OK

        rec.refresh_from_db()
        assert rec.reviewed_by == shipper_user  # Backend uses request.user, ignoring payload injection

    def test_automation_evaluation_does_not_mutate_business_state(self, active_shipment):
        initial_status = active_shipment.status
        initial_price = active_shipment.load.target_price

        AutomationService.evaluate_shipment(active_shipment)

        active_shipment.refresh_from_db()
        assert active_shipment.status == initial_status
        assert active_shipment.load.target_price == initial_price
