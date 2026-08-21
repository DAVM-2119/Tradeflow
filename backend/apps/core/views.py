from django.db import connection
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    System Health Check Endpoint.
    Verifies Django application runtime, PostgreSQL database, and Redis cache.
    """
    db_status = "ok"
    redis_status = "ok"
    
    # Check Database
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check Redis Cache
    try:
        cache.set("health_check_key", "healthy", timeout=5)
        val = cache.get("health_check_key")
        if val != "healthy":
            redis_status = "error: Cache value mismatch"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    is_healthy = (db_status == "ok") and (redis_status == "ok")
    http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return Response({
        "status": "healthy" if is_healthy else "unhealthy",
        "service": "TradeFlow API",
        "version": "1.0.0",
        "checks": {
            "database": db_status,
            "redis": redis_status,
        }
    }, status=http_status)
