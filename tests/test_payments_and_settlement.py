import pytest
from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.accounts.models import Role, VerificationStatus, ShipperProfile, TransporterProfile, DriverProfile
from apps.marketplace.models import (
    Vehicle,
    VehicleType,
    CargoLoad,
    LoadStatus,
    Bid,
    BidStatus,
    Shipment,
    ShipmentStatus,
    ProofOfDelivery,
    CargoCondition,
    PaymentStatus,
    FreightInvoice,
    SettlementStatus,
    FreightSettlement,
    Payment,
    PayoutStatus,
    TransporterPayout,
    PaymentDisputeStatus,
    PaymentDispute,
)
from apps.marketplace.services import (
    VerificationService,
    BiddingService,
    TrackingService,
    PODService,
    InvoiceService,
    SettlementService,
    PaymentService,
    ReconciliationService,
    PayoutService,
    DisputeService,
)

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(email="admin_phase8@tradeflow.et", password="AdminPassword123!")


@pytest.fixture
def shipper_user():
    user = User.objects.create_user(email="shipper_phase8@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    ShipperProfile.objects.create(
        user=user,
        company_name="Ethiopia Freight Shippers PLC",
        trade_license_number="TL-SHIP-88",
        tax_id="TIN-SHIP-88"
    )
    return user


@pytest.fixture
def transporter_user(admin_user):
    user = User.objects.create_user(email="transporter_phase8@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    trans = TransporterProfile.objects.create(
        user=user,
        company_name="Abyssinia Logistics Transporter",
        trade_license_number="TL-ABYS-88",
        tax_id="TIN-ABYS-88",
        verification_status=VerificationStatus.PENDING
    )
    VerificationService.verify_transporter(trans, admin_user, reason="Verified for Phase 8 payment testing.")
    return user


@pytest.fixture
def driver_user(transporter_user):
    user = User.objects.create_user(email="driver_phase8@tradeflow.et", password="Password123!", role=Role.DRIVER)
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number="DL-ETH-889900"
    )
    return user


@pytest.fixture
def vehicle(transporter_user):
    return Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number="ET-3-88990",
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=35.00,
        insurance_policy_number="POL-889",
        roadworthiness_certificate="ROAD-889"
    )


@pytest.fixture
def completed_shipment(shipper_user, transporter_user, driver_user, vehicle):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Corridor Cargo Shipment",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Wheat Grain",
        weight_tonnes=30.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=100000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(
        load=load,
        transporter=transporter_user.transporter_profile,
        proposed_vehicle=vehicle,
        amount=100000.00,
        status=BidStatus.SUBMITTED
    )
    BiddingService.accept_bid(shipper_user, bid)
    ship = load.shipment
    TrackingService.assign_driver(ship, driver_user.driver_profile, transporter_user)

    # Submit e-POD to set DELIVERED
    PODService.create_pod(ship, driver_user, {
        "recipient_name": "Ato Girma",
        "recipient_phone": "+251900112233",
        "delivery_location": "Modjo Dry Port Warehouse 1",
        "delivered_at": timezone.now(),
        "cargo_condition": CargoCondition.GOOD_CONDITION
    })

    return ship


@pytest.mark.django_db
def test_freight_invoice_generation(shipper_user, completed_shipment):
    """1. Freight invoice is generated with unique number and Decimal amounts."""
    invoice = InvoiceService.generate_invoice(completed_shipment)
    assert invoice.invoice_number.startswith("INV-")
    assert invoice.total_amount == Decimal('100000.00')
    assert invoice.currency == "ETB"
    assert invoice.status == PaymentStatus.PENDING


@pytest.mark.django_db
def test_settlement_commission_calculation(completed_shipment):
    """2. Settlement calculates 5% platform commission and net payable with Decimal precision."""
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment, commission_rate=Decimal('0.0500'))
    assert settlement.gross_freight_amount == Decimal('100000.00')
    assert settlement.commission_rate == Decimal('0.0500')
    assert settlement.platform_commission_amount == Decimal('5000.00')
    assert settlement.transporter_net_payable == Decimal('95000.00')
    assert settlement.status == SettlementStatus.READY


@pytest.mark.django_db
def test_payment_initiation_with_idempotency_key(api_client, shipper_user, completed_shipment):
    """3 & 4. Initiating payment via API creates Payment record using MockPaymentProvider."""
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment)

    api_client.force_authenticate(user=shipper_user)
    payload = {
        "settlement_id": settlement.id,
        "idempotency_key": "IDEM-KEY-UNIQUE-1001",
        "provider_name": "MOCK"
    }

    res = api_client.post('/api/v1/payments/initiate/', payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data['idempotency_key'] == "IDEM-KEY-UNIQUE-1001"
    assert data['status'] == "SUCCEEDED"
    assert data['provider_transaction_id'].startswith("MOCK-TXN-")

    # Settlement updated to PAID
    settlement.refresh_from_db()
    assert settlement.status == SettlementStatus.PAID


@pytest.mark.django_db
def test_duplicate_payment_request_idempotent(api_client, shipper_user, completed_shipment):
    """5. Retrying payment initiation with identical idempotency key returns existing payment without duplicates."""
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment)
    api_client.force_authenticate(user=shipper_user)

    payload = {
        "settlement_id": settlement.id,
        "idempotency_key": "IDEM-KEY-DUPLICATE-2002"
    }

    res1 = api_client.post('/api/v1/payments/initiate/', payload, format='json')
    res2 = api_client.post('/api/v1/payments/initiate/', payload, format='json')

    assert res1.status_code == status.HTTP_201_CREATED
    assert res2.status_code == status.HTTP_201_CREATED
    assert res1.json()['id'] == res2.json()['id']
    assert Payment.objects.filter(idempotency_key="IDEM-KEY-DUPLICATE-2002").count() == 1


@pytest.mark.django_db
def test_payment_reconciliation_matched(api_client, admin_user, shipper_user, completed_shipment):
    """6. Admin reconciles payment record against MockPaymentProvider status (MATCHED)."""
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment)
    payment = PaymentService.initiate_payment(settlement, shipper_user, idempotency_key="IDEM-RECONCILE-3003")

    api_client.force_authenticate(user=admin_user)
    res = api_client.post(f'/api/v1/payments/{payment.id}/reconcile/')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['reconciliation_outcome'] == "MATCHED"


@pytest.mark.django_db
def test_transporter_payout_scheduling_and_processing(api_client, admin_user, shipper_user, transporter_user, completed_shipment):
    """7 & 8. Payout is scheduled upon settlement payment and Admin processes transfer."""
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment)
    PaymentService.initiate_payment(settlement, shipper_user, idempotency_key="IDEM-PAYOUT-4004")

    # Verify payout scheduled
    payout = TransporterPayout.objects.get(settlement=settlement)
    assert payout.status == PayoutStatus.SCHEDULED
    assert payout.net_payout_amount == Decimal('95000.00')

    # Admin processes payout
    api_client.force_authenticate(user=admin_user)
    res = api_client.post(f'/api/v1/payouts/{payout.id}/process/')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['status'] == "PAID"

    settlement.refresh_from_db()
    assert settlement.status == SettlementStatus.SETTLED


@pytest.mark.django_db
def test_payment_dispute_creation_and_resolution(api_client, admin_user, shipper_user, completed_shipment):
    """9. Shipper opens settlement dispute and Admin resolves it."""
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment)

    # Shipper raises dispute
    api_client.force_authenticate(user=shipper_user)
    res_dispute = api_client.post(f'/api/v1/settlements/{settlement.id}/dispute/', {"reason": "Freight weight discrepancy noted."}, format='json')
    assert res_dispute.status_code == status.HTTP_201_CREATED
    assert res_dispute.json()['status'] == "OPEN"

    settlement.refresh_from_db()
    assert settlement.status == SettlementStatus.DISPUTED

    # Admin resolves dispute
    dispute_id = res_dispute.json()['id']
    dispute = PaymentDispute.objects.get(pk=dispute_id)
    DisputeService.resolve_dispute(dispute, admin_user, resolution_notes="Discrepancy reviewed and settled.")

    dispute.refresh_from_db()
    assert dispute.status == "RESOLVED"
    assert dispute.resolved_by == admin_user


@pytest.mark.django_db
def test_unauthorized_user_cannot_initiate_payment(api_client, completed_shipment):
    """10. User not participating in load/settlement receives 403 Forbidden on payment initiation."""
    other_user = User.objects.create_user(email="other_shipper_p8@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    settlement = SettlementService.create_settlement_for_shipment(completed_shipment)

    api_client.force_authenticate(user=other_user)
    payload = {"settlement_id": settlement.id, "idempotency_key": "IDEM-UNAUTH-5005"}
    res = api_client.post('/api/v1/payments/initiate/', payload, format='json')
    assert res.status_code == status.HTTP_403_FORBIDDEN
