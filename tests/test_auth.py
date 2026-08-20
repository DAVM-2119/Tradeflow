import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.accounts.models import Role, VerificationStatus
from apps.accounts.permissions import (
    IsShipper,
    IsTransporter,
    IsDriver,
    IsFreightForwarder,
    IsCustomsStaff,
    IsAdmin,
    IsOwnerOrAdmin,
)

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_register_success(api_client):
    """1. Successful registration creates user record and linked profile in PostgreSQL."""
    payload = {
        "email": "new_shipper@tradeflow.et",
        "password": "StrongPassword123!",
        "first_name": "Haile",
        "last_name": "Gebrselassie",
        "phone_number": "+251911000111",
        "role": "SHIPPER",
        "company_name": "Haile Trading PLC",
        "trade_license_number": "TL-HAILE-001",
        "tax_id": "TIN-HAILE-001"
    }
    response = api_client.post('/api/v1/auth/register/', payload, format='json')
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data['email'] == "new_shipper@tradeflow.et"
    assert data['role'] == "SHIPPER"
    assert 'password' not in data

    # Verify database record created
    user = User.objects.get(email="new_shipper@tradeflow.et")
    assert user.check_password("StrongPassword123!") is True
    assert user.shipper_profile.company_name == "Haile Trading PLC"


@pytest.mark.django_db
def test_register_duplicate_email_rejected(api_client):
    """2. Duplicate email registration is rejected."""
    User.objects.create_user(email="existing@tradeflow.et", password="Password123!")
    payload = {
        "email": "existing@tradeflow.et",
        "password": "StrongPassword123!",
        "first_name": "Test",
        "last_name": "User",
        "role": "SHIPPER"
    }
    response = api_client.post('/api/v1/auth/register/', payload, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "email" in response.json()


@pytest.mark.django_db
def test_register_weak_password_rejected(api_client):
    """3. Weak/short password fails backend validation."""
    payload = {
        "email": "weak@tradeflow.et",
        "password": "123",
        "first_name": "Test",
        "last_name": "User",
        "role": "SHIPPER"
    }
    response = api_client.post('/api/v1/auth/register/', payload, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "password" in response.json()


@pytest.mark.django_db
def test_register_invalid_role_rejected(api_client):
    """4. Invalid role string returns 400 Bad Request."""
    payload = {
        "email": "invalid_role@tradeflow.et",
        "password": "StrongPassword123!",
        "first_name": "Test",
        "last_name": "User",
        "role": "SUPERHERO"
    }
    response = api_client.post('/api/v1/auth/register/', payload, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "role" in response.json()


@pytest.mark.django_db
def test_register_admin_role_prevention(api_client):
    """5. Normal users cannot self-register as ADMIN."""
    payload = {
        "email": "fake_admin@tradeflow.et",
        "password": "StrongPassword123!",
        "first_name": "Fake",
        "last_name": "Admin",
        "role": "ADMIN"
    }
    response = api_client.post('/api/v1/auth/register/', payload, format='json')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "role" in response.json()


@pytest.mark.django_db
def test_password_hashing(api_client):
    """6. Password stored in database is securely hashed, not plaintext."""
    User.objects.create_user(email="hash_check@tradeflow.et", password="SecretPassword123!")
    user = User.objects.get(email="hash_check@tradeflow.et")
    assert user.password != "SecretPassword123!"
    assert user.password.startswith("pbkdf2_sha256$") or user.password.startswith("argon2") or len(user.password) > 50


@pytest.mark.django_db
def test_login_success(api_client):
    """7. Valid credentials return access and refresh JWT tokens."""
    User.objects.create_user(email="login_user@tradeflow.et", password="ValidPassword123!")
    login_data = {
        "email": "login_user@tradeflow.et",
        "password": "ValidPassword123!"
    }
    response = api_client.post('/api/v1/auth/login/', login_data, format='json')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access" in data
    assert "refresh" in data
    assert data["user"]["email"] == "login_user@tradeflow.et"


@pytest.mark.django_db
def test_login_invalid_credentials_failed(api_client):
    """8. Invalid password returns 401 Unauthorized."""
    User.objects.create_user(email="login_user@tradeflow.et", password="ValidPassword123!")
    login_data = {
        "email": "login_user@tradeflow.et",
        "password": "WrongPassword123!"
    }
    response = api_client.post('/api/v1/auth/login/', login_data, format='json')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_access_token_authentication_success(api_client):
    """9. Access token Bearer header authenticates requests to protected endpoints."""
    user = User.objects.create_user(email="bearer_user@tradeflow.et", password="ValidPassword123!")
    login_res = api_client.post('/api/v1/auth/login/', {"email": "bearer_user@tradeflow.et", "password": "ValidPassword123!"})
    access_token = login_res.json()["access"]

    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
    me_res = api_client.get('/api/v1/auth/me/')
    assert me_res.status_code == status.HTTP_200_OK
    assert me_res.json()["email"] == "bearer_user@tradeflow.et"


@pytest.mark.django_db
def test_refresh_token_success(api_client):
    """10. Refresh token can obtain a new access token."""
    user = User.objects.create_user(email="refresh_user@tradeflow.et", password="ValidPassword123!")
    login_res = api_client.post('/api/v1/auth/login/', {"email": "refresh_user@tradeflow.et", "password": "ValidPassword123!"})
    refresh_token = login_res.json()["refresh"]

    refresh_res = api_client.post('/api/v1/auth/refresh/', {"refresh": refresh_token})
    assert refresh_res.status_code == status.HTTP_200_OK
    assert "access" in refresh_res.json()


@pytest.mark.django_db
def test_user_me_endpoint_get_and_patch(api_client):
    """11. Authenticated user can view and update their own profile."""
    user = User.objects.create_user(email="me_user@tradeflow.et", password="ValidPassword123!", first_name="OldName")
    api_client.force_authenticate(user=user)

    # GET
    res = api_client.get('/api/v1/auth/me/')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["first_name"] == "OldName"

    # PATCH
    patch_res = api_client.patch('/api/v1/auth/me/', {"first_name": "NewName", "phone_number": "+251922334455"})
    assert patch_res.status_code == status.HTTP_200_OK
    assert patch_res.json()["first_name"] == "NewName"
    assert patch_res.json()["phone_number"] == "+251922334455"


@pytest.mark.django_db
def test_unauthenticated_request_rejected(api_client):
    """12. Protected endpoints reject unauthenticated requests."""
    response = api_client.get('/api/v1/auth/me/')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_role_permissions_enforcement():
    """13. Reusable RBAC permission classes enforce matching roles."""
    shipper = User.objects.create_user(email="perm_shipper@tradeflow.et", password="Pass", role=Role.SHIPPER)
    transporter = User.objects.create_user(email="perm_trans@tradeflow.et", password="Pass", role=Role.TRANSPORTER)

    class MockRequest:
        def __init__(self, user):
            self.user = user

    shipper_req = MockRequest(shipper)
    transporter_req = MockRequest(transporter)

    # IsShipper
    assert IsShipper().has_permission(shipper_req, None) is True
    assert IsShipper().has_permission(transporter_req, None) is False

    # IsTransporter
    assert IsTransporter().has_permission(transporter_req, None) is True
    assert IsTransporter().has_permission(shipper_req, None) is False


@pytest.mark.django_db
def test_object_level_authorization():
    """14. IsOwnerOrAdmin permits owner/admin and rejects unauthorized user."""
    owner = User.objects.create_user(email="owner@tradeflow.et", password="Pass")
    other_user = User.objects.create_user(email="other@tradeflow.et", password="Pass")
    admin_user = User.objects.create_superuser(email="admin_owner@tradeflow.et", password="Pass")

    class MockResource:
        def __init__(self, user):
            self.user = user

    resource = MockResource(owner)

    class MockRequest:
        def __init__(self, user):
            self.user = user

    perm = IsOwnerOrAdmin()
    assert perm.has_object_permission(MockRequest(owner), None, resource) is True
    assert perm.has_object_permission(MockRequest(admin_user), None, resource) is True
    assert perm.has_object_permission(MockRequest(other_user), None, resource) is False


@pytest.mark.django_db
def test_admin_authorization():
    """15. ADMIN users possess global administrative authorization."""
    admin_user = User.objects.create_user(email="admin_role@tradeflow.et", password="Pass", role=Role.ADMIN)

    class MockRequest:
        def __init__(self, user):
            self.user = user

    req = MockRequest(admin_user)
    assert IsAdmin().has_permission(req, None) is True
    assert IsShipper().has_permission(req, None) is True
    assert IsTransporter().has_permission(req, None) is True


@pytest.mark.django_db
def test_inactive_user_login_rejected(api_client):
    """16. Inactive user account is rejected during authentication."""
    user = User.objects.create_user(email="inactive@tradeflow.et", password="ValidPassword123!", is_active=False)
    login_data = {
        "email": "inactive@tradeflow.et",
        "password": "ValidPassword123!"
    }
    response = api_client.post('/api/v1/auth/login/', login_data, format='json')
    assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED]
