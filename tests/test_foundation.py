import pytest
from django.db import connection
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status


@pytest.mark.django_db
def test_database_connection():
    """Verify raw SQL execution against local PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1;")
        result = cursor.fetchone()
    assert result[0] == 1


def test_redis_cache_connection():
    """Verify setting and getting values from local Redis cache."""
    key = "test_redis_key"
    value = "test_redis_value"
    cache.set(key, value, timeout=10)
    retrieved = cache.get(key)
    assert retrieved == value


@pytest.mark.django_db
def test_health_check_endpoint():
    """Verify the /api/v1/health/ endpoint response."""
    client = APIClient()
    response = client.get('/api/v1/health/')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['service'] == 'TradeFlow API'
    assert data['status'] == 'healthy'
    assert data['checks']['database'] == 'ok'
    assert data['checks']['redis'] == 'ok'
