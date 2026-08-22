import logging
from typing import Dict, Any, Tuple
from django.db import connection
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


class DependencyHealthService:
    """
    Production dependency health and readiness service for TradeFlow.
    Evaluates database (PostgreSQL), cache (Redis), and application health status.
    Exposes reusable status checks without hardcoding credentials or connection details.
    """

    @classmethod
    def check_database(cls) -> Dict[str, Any]:
        """
        Verifies primary PostgreSQL database connectivity via Django ORM connection pool.
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    return {"status": "healthy"}
            return {"status": "unhealthy", "error": "Database returned unexpected query result."}
        except Exception as exc:
            logger.error(f"PostgreSQL database health check failed: {type(exc).__name__} - {str(exc)}")
            return {"status": "unhealthy", "error": "Database service unavailable."}

    @classmethod
    def check_redis(cls) -> Dict[str, Any]:
        """
        Verifies Redis cache and channel broker reachability via configured Django cache backend.
        """
        try:
            ping_key = "system:health:ping"
            cache.set(ping_key, "pong", timeout=5)
            result = cache.get(ping_key)
            if result == "pong":
                return {"status": "healthy"}
            return {"status": "unhealthy", "error": "Redis cache ping mismatch."}
        except Exception as exc:
            logger.warning(f"Redis cache health check degraded: {type(exc).__name__} - {str(exc)}")
            return {"status": "unhealthy", "error": "Redis service unavailable."}

    @classmethod
    def check_application(cls) -> Dict[str, Any]:
        """
        Verifies Django application process status.
        """
        return {
            "status": "healthy",
            "service": "tradeflow-api",
            "version": "1.0.0"
        }

    @classmethod
    def get_system_health(cls) -> Dict[str, Any]:
        """
        Returns application process liveness status.
        Answers: Is the API process alive and accepting HTTP requests?
        """
        return {
            "status": "healthy",
            "service": "tradeflow-api",
            "timestamp": timezone.now().isoformat()
        }

    @classmethod
    def get_system_readiness(cls) -> Tuple[Dict[str, Any], int]:
        """
        Returns dependency readiness status for load balancers and orchestrators.
        Verifies database and Redis availability.
        Returns 200 OK when ready, 503 Service Unavailable when degraded.
        """
        db_health = cls.check_database()
        redis_health = cls.check_redis()

        is_db_healthy = db_health.get("status") == "healthy"
        is_redis_healthy = redis_health.get("status") == "healthy"

        # Application is ready if primary DB is healthy (Redis degraded state is reported but does not fail process)
        is_ready = is_db_healthy

        status_code = 200 if is_ready else 503
        readiness_status = "ready" if is_ready else "not_ready"

        return {
            "status": readiness_status,
            "database": {
                "status": db_health.get("status")
            },
            "redis": {
                "status": redis_health.get("status")
            },
            "timestamp": timezone.now().isoformat()
        }, status_code
