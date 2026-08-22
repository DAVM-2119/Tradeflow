import uuid
import time
import re
import logging
import threading
from typing import Dict, Any, Optional
from django.utils import timezone
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger('tradeflow.observability')

# Configurable threshold for slow operation detection (in milliseconds)
SLOW_OPERATION_THRESHOLD_MS = 500.0
REQUEST_ID_REGEX = re.compile(r'^[a-zA-Z0-9_\-]{8,64}$')


class OperationalMetricsService:
    """
    In-memory thread-safe operational metrics aggregator tracking platform reliability,
    HTTP requests, dependency failures, WebSocket authentication failures, and operational events.
    """
    _lock = threading.Lock()
    _total_requests = 0
    _error_requests = 0
    _slow_requests = 0
    _db_failures = 0
    _redis_failures = 0
    _websocket_auth_failures = 0
    _event_creation_failures = 0
    _notification_delivery_failures = 0
    _automation_execution_failures = 0

    @classmethod
    def record_request(cls, status_code: int, duration_ms: float):
        with cls._lock:
            cls._total_requests += 1
            if status_code >= 400:
                cls._error_requests += 1
            if duration_ms >= SLOW_OPERATION_THRESHOLD_MS:
                cls._slow_requests += 1

    @classmethod
    def record_db_failure(cls):
        with cls._lock:
            cls._db_failures += 1

    @classmethod
    def record_redis_failure(cls):
        with cls._lock:
            cls._redis_failures += 1

    @classmethod
    def record_websocket_auth_failure(cls):
        with cls._lock:
            cls._websocket_auth_failures += 1

    @classmethod
    def record_event_failure(cls):
        with cls._lock:
            cls._event_creation_failures += 1

    @classmethod
    def record_notification_failure(cls):
        with cls._lock:
            cls._notification_delivery_failures += 1

    @classmethod
    def record_automation_failure(cls):
        with cls._lock:
            cls._automation_execution_failures += 1

    @classmethod
    def get_metrics_summary(cls) -> Dict[str, Any]:
        with cls._lock:
            return {
                "requests": {
                    "total": cls._total_requests,
                    "errors": cls._error_requests,
                    "slow_requests": cls._slow_requests
                },
                "dependencies": {
                    "database_failures": cls._db_failures,
                    "redis_failures": cls._redis_failures
                },
                "websocket": {
                    "authentication_failures": cls._websocket_auth_failures
                },
                "operations": {
                    "event_creation_failures": cls._event_creation_failures,
                    "notification_delivery_failures": cls._notification_delivery_failures,
                    "automation_execution_failures": cls._automation_execution_failures
                },
                "generated_at": timezone.now().isoformat()
            }


class RequestCorrelationMiddleware:
    """
    Middleware ensuring every HTTP request receives a unique, sanitized request correlation ID.
    Propagates X-Request-ID header to response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming_id = request.headers.get('X-Request-ID') or request.META.get('HTTP_X_REQUEST_ID')

        if incoming_id and REQUEST_ID_REGEX.match(incoming_id):
            request_id = incoming_id
        else:
            request_id = f"req_{uuid.uuid4().hex[:16]}"

        request.request_id = request_id

        response = self.get_response(request)

        if hasattr(response, 'headers'):
            response.headers['X-Request-ID'] = request_id
        elif hasattr(response, '__setitem__'):
            response['X-Request-ID'] = request_id

        return response


class RequestTimingMiddleware:
    """
    Middleware measuring API request duration and producing structured operational logs.
    Detects and logs slow operations exceeding SLOW_OPERATION_THRESHOLD_MS (500ms).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        request_id = getattr(request, 'request_id', 'unknown')
        user_id = request.user.id if hasattr(request, 'user') and request.user and request.user.is_authenticated else None
        status_code = getattr(response, 'status_code', 500)

        # Track in operational metrics service
        OperationalMetricsService.record_request(status_code, duration_ms)

        log_payload = {
            "event": "http_request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
            "timestamp": timezone.now().isoformat()
        }

        logger.info(f"HTTP {request.method} {request.path} [{status_code}] {duration_ms}ms (req_id={request_id})")

        # Slow operation logging threshold check
        if duration_ms >= SLOW_OPERATION_THRESHOLD_MS:
            logger.warning(
                f"SLOW OPERATION DETECTED: {request.method} {request.path} took {duration_ms}ms (>={SLOW_OPERATION_THRESHOLD_MS}ms threshold) [req_id={request_id}]"
            )

        return response


def tradeflow_custom_exception_handler(exc, context) -> Optional[Response]:
    """
    Centralized DRF exception handler for production reliability and error observability.
    Safely captures uncaught exceptions, attaches request ID, logs diagnostic details,
    and returns safe API responses without leaking internal stack traces or secrets.
    """
    response = exception_handler(exc, context)
    request = context.get('request')
    request_id = getattr(request, 'request_id', 'unknown') if request else 'unknown'

    if response is None:
        # Unhandled application exception
        logger.error(
            f"UNHANDLED EXCEPTION [{type(exc).__name__}] on {getattr(request, 'path', 'unknown')} (req_id={request_id}): {str(exc)}",
            exc_info=True
        )
        response = Response(
            {
                "detail": "Internal server error.",
                "request_id": request_id
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # Attach request ID to error payload if dictionary
    if isinstance(response.data, dict) and 'request_id' not in response.data:
        response.data['request_id'] = request_id

    if hasattr(response, 'headers'):
        response.headers['X-Request-ID'] = request_id

    return response
