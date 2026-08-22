import hmac
import hashlib
import json
import csv
import io
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import timedelta

from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound

from apps.accounts.models import Role
from apps.marketplace.models import (
    SecurityAuditEvent, SecurityAuditEventSeverity, SecurityAuditEventType,
    SecurityIncident, SecurityIncidentStatus, SecurityIncidentType,
    SecurityPolicy
)

User = get_user_model()
logger = logging.getLogger('tradeflow.security')


class SecurityGovernanceService:
    """
    Primary orchestration service for Phase 19 Advanced Security, Compliance & Governance.
    """

    SENSITIVE_KEYS = {
        'password', 'token', 'access_token', 'refresh_token', 'authorization',
        'secret', 'webhook_secret', 'api_key', 'client_secret', 'private_key',
        'database_url', 'credit_card', 'card_number', 'cvv'
    }

    @classmethod
    def sanitize_metadata(cls, data: Any) -> Any:
        """
        Recursively sanitizes dictionary and list metadata by masking sensitive keys with '********'.
        """
        if isinstance(data, dict):
            sanitized = {}
            for k, v in data.items():
                if isinstance(k, str) and k.lower() in cls.SENSITIVE_KEYS:
                    sanitized[k] = "********"
                else:
                    sanitized[k] = cls.sanitize_metadata(v)
            return sanitized
        elif isinstance(data, list):
            return [cls.sanitize_metadata(item) for item in data]
        return data

    @classmethod
    def compute_event_hash(cls, previous_hash: str, event_type: str, actor_id: Optional[int], target_object_id: str, action: str, description: str, request_id: str, timestamp_iso: str, metadata_json: str) -> str:
        raw_str = f"{previous_hash}|{event_type}|{actor_id or ''}|{target_object_id or ''}|{action}|{description or ''}|{request_id or ''}|{timestamp_iso}|{metadata_json}"
        return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

    @classmethod
    def record_audit_event(
        cls,
        event_type: str,
        action: str,
        actor: Optional[Any] = None,
        target_user: Optional[Any] = None,
        target_model: str = "",
        target_object_id: str = "",
        severity: str = SecurityAuditEventSeverity.INFO,
        description: str = "",
        request: Optional[Any] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SecurityAuditEvent:
        """
        Appends an immutable SecurityAuditEvent record with SHA-256 hash chaining.
        """
        sanitized_meta = cls.sanitize_metadata(metadata or {})
        now = timezone.now()

        req_id = request_id or getattr(request, 'request_id', '') or ''
        ip_addr = getattr(request, 'META', {}).get('REMOTE_ADDR') if request else None
        user_agent = getattr(request, 'META', {}).get('HTTP_USER_AGENT', '') if request else ''
        endpoint = getattr(request, 'path', '') if request else ''
        http_method = getattr(request, 'method', '') if request else ''

        actor_role = ""
        if actor and hasattr(actor, 'role'):
            actor_role = str(actor.role)

        with transaction.atomic():
            last_event = SecurityAuditEvent.objects.select_for_update().order_by('-id').first()
            prev_hash = last_event.event_hash if last_event and last_event.event_hash else "0" * 64

            audit_evt = SecurityAuditEvent.objects.create(
                event_type=event_type,
                severity=severity,
                actor=actor,
                actor_role=actor_role,
                target_user=target_user,
                target_model=target_model,
                target_object_id=str(target_object_id or ''),
                action=action,
                description=description,
                request_id=req_id,
                ip_address=ip_addr,
                user_agent=user_agent,
                endpoint=endpoint,
                http_method=http_method,
                metadata=sanitized_meta,
                previous_hash=prev_hash,
                event_hash=""
            )

            meta_json = json.dumps(sanitized_meta, sort_keys=True)
            timestamp_iso = audit_evt.created_at.isoformat()
            actor_id = actor.id if actor and hasattr(actor, 'id') else None

            evt_hash = cls.compute_event_hash(
                prev_hash, event_type, actor_id, str(target_object_id or ''), action, description, req_id, timestamp_iso, meta_json
            )

            audit_evt.event_hash = evt_hash
            audit_evt.save(update_fields=['event_hash'])

            return audit_evt

    @classmethod
    def verify_audit_event_integrity(cls, event: SecurityAuditEvent) -> bool:
        meta_json = json.dumps(event.metadata or {}, sort_keys=True)
        timestamp_iso = event.created_at.isoformat()
        actor_id = event.actor.id if event.actor else None

        computed = cls.compute_event_hash(
            event.previous_hash or ("0" * 64),
            event.event_type,
            actor_id,
            str(event.target_object_id or ''),
            event.action,
            event.description or '',
            event.request_id or '',
            timestamp_iso,
            meta_json
        )
        return hmac.compare_digest(event.event_hash or '', computed)


    @classmethod
    def verify_audit_chain(cls) -> Dict[str, Any]:
        """
        Inspects full database audit log chain for hash integrity and continuity.
        """
        events = list(SecurityAuditEvent.objects.order_by('id'))
        total = len(events)
        invalid_count = 0
        details = []

        expected_prev = "0" * 64
        chain_valid = True

        for idx, evt in enumerate(events):
            if idx > 0 and evt.previous_hash != expected_prev:
                chain_valid = False
                invalid_count += 1
                details.append(f"Chain discontinuity at Audit #{evt.id}: expected prev {expected_prev[:8]}, found {evt.previous_hash[:8]}")

            if not cls.verify_audit_event_integrity(evt):
                chain_valid = False
                invalid_count += 1
                details.append(f"Audit #{evt.id} hash verification failed.")

            expected_prev = evt.event_hash

        status_str = "valid" if chain_valid else "corrupted"

        return {
            "status": status_str,
            "events_checked": total,
            "invalid_events": invalid_count,
            "chain_valid": chain_valid,
            "verified_at": timezone.now(),
            "details": details
        }

    @classmethod
    def record_data_access(cls, actor, resource_type: str, resource_id: Any, action: str = "READ", request: Optional[Any] = None) -> SecurityAuditEvent:
        return cls.record_audit_event(
            event_type=SecurityAuditEventType.SENSITIVE_DATA_ACCESSED,
            action=action,
            actor=actor,
            target_model=resource_type,
            target_object_id=str(resource_id),
            severity=SecurityAuditEventSeverity.INFO,
            description=f"Accessed sensitive resource '{resource_type}' ID {resource_id}",
            request=request,
            metadata={"resource_type": resource_type, "resource_id": str(resource_id)}
        )

    @classmethod
    def detect_security_incidents(cls) -> List[SecurityIncident]:
        """
        Evaluates failed login attempts and API security violations to generate SecurityIncident records.
        """
        now = timezone.now()
        cutoff = now - timedelta(minutes=15)

        incidents = []

        # Brute force login detection
        failed_logins = SecurityAuditEvent.objects.filter(
            event_type=SecurityAuditEventType.LOGIN_FAILURE,
            created_at__gte=cutoff
        )

        ip_counts = failed_logins.values('ip_address').annotate(total=Count('id')).filter(total__gte=5)
        for entry in ip_counts:
            ip = entry['ip_address']
            count = entry['total']
            corr_id = f"brute_{ip}_{now.strftime('%Y%m%d%H%M')}"

            if not SecurityIncident.objects.filter(correlation_id=corr_id).exists():
                inc = SecurityIncident.objects.create(
                    incident_type=SecurityIncidentType.BRUTE_FORCE,
                    severity=SecurityAuditEventSeverity.HIGH,
                    status=SecurityIncidentStatus.OPEN,
                    title=f"Brute Force Attempt Detected from IP {ip}",
                    description=f"Detected {count} failed login attempts from IP {ip} within 15 minutes.",
                    correlation_id=corr_id,
                    metadata={"ip_address": ip, "failed_count": count}
                )
                incidents.append(inc)

        return incidents

    @classmethod
    def get_security_overview(cls) -> Dict[str, Any]:
        now = timezone.now()
        cutoff_24h = now - timedelta(hours=24)

        audit_qs = SecurityAuditEvent.objects.all()

        tot_events = audit_qs.count()
        crit_events = audit_qs.filter(severity=SecurityAuditEventSeverity.CRITICAL).count()
        high_events = audit_qs.filter(severity=SecurityAuditEventSeverity.HIGH).count()

        failed_logins = audit_qs.filter(event_type=SecurityAuditEventType.LOGIN_FAILURE, created_at__gte=cutoff_24h).count()
        succ_logins = audit_qs.filter(event_type=SecurityAuditEventType.LOGIN_SUCCESS, created_at__gte=cutoff_24h).count()
        access_denials = audit_qs.filter(event_type=SecurityAuditEventType.API_ACCESS_DENIED, created_at__gte=cutoff_24h).count()

        inc_qs = SecurityIncident.objects.all()
        open_inc = inc_qs.filter(status=SecurityIncidentStatus.OPEN).count()
        inv_inc = inc_qs.filter(status=SecurityIncidentStatus.INVESTIGATING).count()
        res_inc = inc_qs.filter(status=SecurityIncidentStatus.RESOLVED).count()

        priv_changes = audit_qs.filter(event_type__in=[
            SecurityAuditEventType.ROLE_CHANGED,
            SecurityAuditEventType.PERMISSION_GRANTED,
            SecurityAuditEventType.PERMISSION_REVOKED,
            SecurityAuditEventType.USER_DEACTIVATED
        ]).count()

        webhook_failures = audit_qs.filter(event_type=SecurityAuditEventType.WEBHOOK_SECURITY_FAILURE).count()

        chain_res = cls.verify_audit_chain()

        return {
            "total_security_events": tot_events,
            "critical_events": crit_events,
            "high_severity_events": high_events,
            "failed_logins": failed_logins,
            "successful_logins": succ_logins,
            "access_denials": access_denials,
            "open_security_incidents": open_inc,
            "investigating_incidents": inv_inc,
            "resolved_incidents": res_inc,
            "privilege_changes": priv_changes,
            "webhook_security_failures": webhook_failures,
            "audit_integrity_status": chain_res["status"],
            "generated_at": now
        }

    @classmethod
    def get_compliance_report(cls, report_type: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        filters = filters or {}
        now = timezone.now()
        qs = SecurityAuditEvent.objects.all()

        if report_type == 'AUTHENTICATION':
            qs = qs.filter(event_type__in=[
                SecurityAuditEventType.LOGIN_SUCCESS, SecurityAuditEventType.LOGIN_FAILURE,
                SecurityAuditEventType.LOGOUT, SecurityAuditEventType.TOKEN_REFRESH,
                SecurityAuditEventType.PASSWORD_CHANGED
            ])
            title = "Compliance Audit Report: Authentication Events"
        elif report_type == 'PRIVILEGE_CHANGES':
            qs = qs.filter(event_type__in=[
                SecurityAuditEventType.ROLE_CHANGED, SecurityAuditEventType.PERMISSION_GRANTED,
                SecurityAuditEventType.PERMISSION_REVOKED, SecurityAuditEventType.USER_CREATED,
                SecurityAuditEventType.USER_DEACTIVATED
            ])
            title = "Compliance Audit Report: Privilege and User Governance"
        elif report_type == 'SECURITY_INCIDENTS':
            inc_list = list(SecurityIncident.objects.all().values(
                'id', 'incident_type', 'severity', 'status', 'title', 'detected_at'
            ))
            return {
                "report_type": report_type,
                "title": "Compliance Audit Report: Security Incidents",
                "generated_at": now,
                "filters_applied": filters,
                "record_count": len(inc_list),
                "summary": {"total_incidents": len(inc_list)},
                "records": [
                    {**inc, "detected_at": inc["detected_at"].isoformat() if inc["detected_at"] else ""}
                    for inc in inc_list
                ]
            }
        else:
            title = f"Compliance Audit Report: {report_type.upper()}"

        records = []
        for evt in qs[:500]:
            records.append({
                "id": evt.id,
                "event_type": evt.event_type,
                "severity": evt.severity,
                "actor": evt.actor.email if evt.actor else "System",
                "target_user": evt.target_user.email if evt.target_user else "",
                "action": evt.action,
                "ip_address": evt.ip_address or "",
                "request_id": evt.request_id or "",
                "created_at": evt.created_at.isoformat()
            })

        return {
            "report_type": report_type,
            "title": title,
            "generated_at": now,
            "filters_applied": filters,
            "record_count": len(records),
            "summary": {"total_events": len(records)},
            "records": records
        }

    @classmethod
    def render_csv_compliance_report(cls, report_data: Dict[str, Any], report_type: str) -> str:
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["TRADEFLOW SECURITY COMPLIANCE REPORT"])
        writer.writerow(["Report Title", report_data.get('title')])
        writer.writerow(["Generated At", str(report_data.get('generated_at'))])
        writer.writerow(["Record Count", report_data.get('record_count')])
        writer.writerow([])

        records = report_data.get('records', [])
        if records:
            headers = list(records[0].keys())
            writer.writerow(headers)
            for row in records:
                writer.writerow([row.get(h, '') for h in headers])
        else:
            writer.writerow(["No records found."])

        return output.getvalue()
