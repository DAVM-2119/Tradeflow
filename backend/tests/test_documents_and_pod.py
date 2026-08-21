import os
import pytest
from datetime import date, timedelta
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
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
    DocumentType,
    ShipmentDocument,
    CargoCondition,
    PODConfirmationStatus,
    ProofOfDelivery,
)
from apps.marketplace.services import VerificationService, BiddingService, TrackingService

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(email="admin_phase7@tradeflow.et", password="AdminPassword123!")


@pytest.fixture
def shipper_user():
    user = User.objects.create_user(email="shipper_phase7@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    ShipperProfile.objects.create(
        user=user,
        company_name="Ethiopia Trading Logistics PLC",
        trade_license_number="TL-ETL-77",
        tax_id="TIN-ETL-77"
    )
    return user


@pytest.fixture
def transporter_user(admin_user):
    user = User.objects.create_user(email="transporter_phase7@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    trans = TransporterProfile.objects.create(
        user=user,
        company_name="Red Sea Freight Services",
        trade_license_number="TL-REDSEA-77",
        tax_id="TIN-REDSEA-77",
        verification_status=VerificationStatus.PENDING
    )
    VerificationService.verify_transporter(trans, admin_user, reason="Verified for Phase 7 testing.")
    return user


@pytest.fixture
def driver_user(transporter_user):
    user = User.objects.create_user(email="driver_phase7@tradeflow.et", password="Password123!", role=Role.DRIVER)
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number="DL-ETH-778899"
    )
    return user


@pytest.fixture
def vehicle(transporter_user):
    return Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number="ET-3-77889",
        vehicle_type=VehicleType.CONTAINER_TRUCK,
        capacity_tonnes=40.00,
        insurance_policy_number="POL-778",
        roadworthiness_certificate="ROAD-778"
    )


@pytest.fixture
def shipment(shipper_user, transporter_user, driver_user, vehicle):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Phase 7 Trade Corridor Cargo",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Electronics",
        weight_tonnes=25.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=120000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(
        load=load,
        transporter=transporter_user.transporter_profile,
        proposed_vehicle=vehicle,
        amount=115000.00,
        status=BidStatus.SUBMITTED
    )
    BiddingService.accept_bid(shipper_user, bid)
    ship = load.shipment
    TrackingService.assign_driver(ship, driver_user.driver_profile, transporter_user)
    return ship


@pytest.mark.django_db
def test_authorized_participant_uploads_valid_pdf(api_client, shipper_user, shipment):
    """1. Authorized participant uploads a valid PDF document with SHA-256 calculation."""
    api_client.force_authenticate(user=shipper_user)
    pdf_content = b"%PDF-1.4 sample bill of lading content for tradeflow"
    file = SimpleUploadedFile("waybill_test.pdf", pdf_content, content_type="application/pdf")

    payload = {
        "document_type": DocumentType.WAYBILL,
        "file": file,
        "notes": "Original Ethiopian Customs Commission Waybill"
    }

    res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', payload, format='multipart')
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data['file_name'] == "waybill_test.pdf"
    assert data['checksum_sha256'] != ""
    assert data['uploaded_by_email'] == shipper_user.email


@pytest.mark.django_db
def test_authorized_participant_uploads_valid_image(api_client, driver_user, shipment):
    """2. Driver uploads a valid PNG image document."""
    api_client.force_authenticate(user=driver_user)
    image_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR sample png image data"
    file = SimpleUploadedFile("weighbridge_ticket.png", image_content, content_type="image/png")

    payload = {
        "document_type": DocumentType.WEIGHT_BRIDGE_TICKET,
        "file": file,
        "notes": "Modjo Dry Port Weighbridge Ticket"
    }

    res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', payload, format='multipart')
    assert res.status_code == status.HTTP_201_CREATED
    assert res.json()['document_type'] == "WEIGHT_BRIDGE_TICKET"


@pytest.mark.django_db
def test_invalid_file_extension_rejected(api_client, shipper_user, shipment):
    """3. Executable/script extensions (.exe or .sh) are rejected with 400 Bad Request."""
    api_client.force_authenticate(user=shipper_user)
    malicious_file = SimpleUploadedFile("malware.exe", b"echo hack", content_type="application/x-msdownload")

    payload = {
        "document_type": DocumentType.WAYBILL,
        "file": malicious_file
    }

    res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', payload, format='multipart')
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "File extension '.exe' is not permitted" in str(res.json())


@pytest.mark.django_db
def test_oversized_file_rejected(api_client, shipper_user, shipment):
    """4. File larger than 10MB is rejected with 400 Bad Request."""
    api_client.force_authenticate(user=shipper_user)
    # Create mock file larger than 10MB
    large_content = b"0" * (10 * 1024 * 1024 + 100)
    large_file = SimpleUploadedFile("huge_file.pdf", large_content, content_type="application/pdf")

    payload = {
        "document_type": DocumentType.CUSTOMS_RELEASE,
        "file": large_file
    }

    res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', payload, format='multipart')
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "exceeds maximum limit of 10 MB" in str(res.json())


@pytest.mark.django_db
def test_unauthorized_user_cannot_upload_document(api_client, shipment):
    """5. User not participating in shipment receives 403 Forbidden on document upload."""
    other_user = User.objects.create_user(email="unauth_doc_user@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    api_client.force_authenticate(user=other_user)

    file = SimpleUploadedFile("invoice.pdf", b"pdf content", content_type="application/pdf")
    payload = {"document_type": DocumentType.COMMERCIAL_INVOICE, "file": file}

    res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', payload, format='multipart')
    assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_authorized_participant_can_download_document(api_client, shipper_user, shipment):
    """6. Participant downloads document via protected endpoint."""
    api_client.force_authenticate(user=shipper_user)
    file = SimpleUploadedFile("customs_release.pdf", b"%PDF-1.4 release document content", content_type="application/pdf")
    payload = {"document_type": DocumentType.CUSTOMS_RELEASE, "file": file}

    upload_res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', payload, format='multipart')
    doc_id = upload_res.json()['id']

    # Download document
    download_res = api_client.get(f'/api/v1/documents/{doc_id}/download/')
    assert download_res.status_code == status.HTTP_200_OK
    assert download_res.headers['Content-Type'] == 'application/pdf'


@pytest.mark.django_db
def test_unauthorized_user_cannot_download_document(api_client, shipper_user, shipment):
    """7. Non-participant receives 403 Forbidden on document download attempt."""
    api_client.force_authenticate(user=shipper_user)
    file = SimpleUploadedFile("secret_waybill.pdf", b"%PDF content", content_type="application/pdf")
    upload_res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', {"document_type": DocumentType.WAYBILL, "file": file}, format='multipart')
    doc_id = upload_res.json()['id']

    other_user = User.objects.create_user(email="intruder@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    api_client.force_authenticate(user=other_user)

    res = api_client.get(f'/api/v1/documents/{doc_id}/download/')
    assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_uploader_can_delete_document(api_client, shipper_user, shipment):
    """8. Document uploader can delete document (204 No Content)."""
    api_client.force_authenticate(user=shipper_user)
    file = SimpleUploadedFile("temp.pdf", b"temp content", content_type="application/pdf")
    upload_res = api_client.post(f'/api/v1/shipments/{shipment.id}/documents/', {"document_type": DocumentType.OTHER, "file": file}, format='multipart')
    doc_id = upload_res.json()['id']

    res = api_client.delete(f'/api/v1/documents/{doc_id}/')
    assert res.status_code == status.HTTP_204_NO_CONTENT
    assert not ShipmentDocument.objects.filter(id=doc_id).exists()


@pytest.mark.django_db
def test_driver_submits_valid_pod_and_transitions_shipment(api_client, driver_user, shipment):
    """9. Driver submits e-POD -> status is SUBMITTED & shipment transitions automatically to DELIVERED."""
    api_client.force_authenticate(user=driver_user)
    pod_payload = {
        "recipient_name": "Ato Kebede Tassew",
        "recipient_phone": "+251911223344",
        "delivery_location": "Modjo Dry Port Warehouse B",
        "delivered_at": timezone.now().isoformat(),
        "signature_data": "<svg>signature_data</svg>",
        "cargo_condition": CargoCondition.GOOD_CONDITION,
        "received_weight_tonnes": 25.00,
        "delivery_notes": "All 25 tonnes delivered in sound condition."
    }

    res = api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', pod_payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data['confirmation_status'] == "SUBMITTED"
    assert data['recipient_name'] == "Ato Kebede Tassew"

    # Verify shipment transitioned to DELIVERED
    shipment.refresh_from_db()
    assert shipment.status == ShipmentStatus.DELIVERED
    assert shipment.actual_delivery_time is not None


@pytest.mark.django_db
def test_shipper_can_confirm_pod(api_client, shipper_user, driver_user, shipment):
    """10. Shipper load owner confirms e-POD delivery."""
    api_client.force_authenticate(user=driver_user)
    pod_payload = {
        "recipient_name": "Ato Kebede",
        "recipient_phone": "+251911223344",
        "delivery_location": "Modjo Dry Port",
        "delivered_at": timezone.now().isoformat(),
        "cargo_condition": CargoCondition.GOOD_CONDITION
    }
    pod_res = api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', pod_payload, format='json')
    pod_id = pod_res.json()['id']

    # Shipper confirms POD
    api_client.force_authenticate(user=shipper_user)
    res = api_client.post(f'/api/v1/pod/{pod_id}/confirm/')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['confirmation_status'] == "CONFIRMED"
    assert res.json()['confirmed_by_shipper_email'] == shipper_user.email


@pytest.mark.django_db
def test_shipper_can_dispute_pod(api_client, shipper_user, driver_user, shipment):
    """11. Shipper load owner disputes e-POD delivery with dispute reason."""
    api_client.force_authenticate(user=driver_user)
    pod_payload = {
        "recipient_name": "Ato Kebede",
        "recipient_phone": "+251911223344",
        "delivery_location": "Modjo Dry Port",
        "delivered_at": timezone.now().isoformat(),
        "cargo_condition": CargoCondition.PARTIALLY_DAMAGED
    }
    pod_res = api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', pod_payload, format='json')
    pod_id = pod_res.json()['id']

    # Shipper disputes POD
    api_client.force_authenticate(user=shipper_user)
    res = api_client.post(f'/api/v1/pod/{pod_id}/dispute/', {"dispute_reason": "2 cartons water damaged during transport."}, format='json')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['confirmation_status'] == "DISPUTED"
    assert res.json()['dispute_reason'] == "2 cartons water damaged during transport."


@pytest.mark.django_db
def test_dispute_without_reason_rejected(api_client, shipper_user, driver_user, shipment):
    """12. Disputing e-POD without reason returns 400 Bad Request."""
    api_client.force_authenticate(user=driver_user)
    pod_res = api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', {
        "recipient_name": "Ato Kebede",
        "recipient_phone": "+251911223344",
        "delivery_location": "Modjo Dry Port",
        "delivered_at": timezone.now().isoformat()
    }, format='json')
    pod_id = pod_res.json()['id']

    api_client.force_authenticate(user=shipper_user)
    res = api_client.post(f'/api/v1/pod/{pod_id}/dispute/', {"dispute_reason": "   "}, format='json')
    assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_unauthorized_user_cannot_confirm_or_dispute_pod(api_client, driver_user, shipment):
    """13. Non-shipper user receives 403 Forbidden on confirm/dispute attempts."""
    api_client.force_authenticate(user=driver_user)
    pod_res = api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', {
        "recipient_name": "Ato Kebede",
        "recipient_phone": "+251911223344",
        "delivery_location": "Modjo Dry Port",
        "delivered_at": timezone.now().isoformat()
    }, format='json')
    pod_id = pod_res.json()['id']

    other_user = User.objects.create_user(email="other_shipper@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    api_client.force_authenticate(user=other_user)

    res_confirm = api_client.post(f'/api/v1/pod/{pod_id}/confirm/')
    assert res_confirm.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_duplicate_pod_submission_rejected(api_client, driver_user, shipment):
    """14. Submitting duplicate e-POD returns 400 Bad Request."""
    api_client.force_authenticate(user=driver_user)
    payload = {
        "recipient_name": "Ato Kebede",
        "recipient_phone": "+251911223344",
        "delivery_location": "Modjo Dry Port",
        "delivered_at": timezone.now().isoformat()
    }
    api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', payload, format='json')

    # Duplicate submission
    res_dup = api_client.post(f'/api/v1/shipments/{shipment.id}/pod/', payload, format='json')
    assert res_dup.status_code == status.HTTP_400_BAD_REQUEST
    assert "already been submitted" in str(res_dup.json())
