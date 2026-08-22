import logging
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from rest_framework.exceptions import PermissionDenied, ValidationError
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.accounts.models import Role
from apps.marketplace.models import (
    Shipment, OperationalEvent, OperationalEventType, EventSeverity,
    Notification, NotificationType, NotificationPreference
)

User = get_user_model()
logger = logging.getLogger(__name__)


class OperationalEventService:
    """
    Domain service for persisting operational events, enforcing idempotency,
    generating persistent notifications, and publishing real-time WebSocket signals.
    """

    @classmethod
    def create_event(
        cls,
        event_type: str,
        title: str,
        description: str,
        severity: str = EventSeverity.MEDIUM,
        shipment: Shipment = None,
        actor=None,
        source: str = 'SYSTEM',
        payload: dict = None,
        idempotency_key: str = None
    ) -> OperationalEvent:
        """
        Atomically persists an operational event, prevents duplicate event creation,
        triggers recipient notifications, and broadcasts real-time WebSocket payloads.
        """
        if event_type not in OperationalEventType.values:
            raise ValidationError(f"Invalid event type '{event_type}'. Valid choices: {OperationalEventType.values}")
        if severity not in EventSeverity.values:
            raise ValidationError(f"Invalid severity '{severity}'. Valid choices: {EventSeverity.values}")

        payload_data = payload or {}

        # Construct deterministic idempotency key if not explicitly supplied
        if not idempotency_key:
            ship_id = shipment.id if shipment else 'system'
            time_bucket = timezone.now().strftime('%Y%m%d%H')  # hourly bucket
            raw_hash = f"{ship_id}:{event_type}:{title}:{time_bucket}"
            payload_str = str(sorted(payload_data.items())) if payload_data else ""
            hash_sig = hashlib.sha256((raw_hash + payload_str).encode('utf-8')).hexdigest()[:16]
            idempotency_key = f"event:{ship_id}:{event_type}:{time_bucket}:{hash_sig}"

        with transaction.atomic():
            event, created = OperationalEvent.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={
                    'event_type': event_type,
                    'severity': severity,
                    'shipment': shipment,
                    'actor': actor if (actor and getattr(actor, 'is_authenticated', False)) else None,
                    'source': source,
                    'title': title,
                    'description': description,
                    'payload': payload_data,
                }
            )

            if created:
                logger.info(f"Created OperationalEvent #{event.id} [{severity}] ({event_type}) for shipment #{shipment.id if shipment else 'SYSTEM'}")
                # Generate persistent notifications for authorized recipients
                NotificationService.create_notifications_for_event(event)

        # Broadcast real-time event via Redis + Channels layer AFTER DB commit
        if created:
            cls.broadcast_event_realtime(event)

        return event

    @classmethod
    def broadcast_event_realtime(cls, event: OperationalEvent):
        """
        Sends structured event payload to Channels WebSocket group for the shipment.
        """
        if not event.shipment:
            return

        try:
            channel_layer = get_channel_layer()
            if not channel_layer:
                return
            group_name = f"shipments.{event.shipment.id}.events"

            event_data = {
                "type": "shipment.event",
                "event": {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "shipment_id": event.shipment.id,
                    "shipment_tracking_number": event.shipment.tracking_number,
                    "title": event.title,
                    "description": event.description,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
            }
            async_to_sync(channel_layer.group_send)(group_name, event_data)
        except Exception as e:
            logger.warning(f"Real-time event WebSocket broadcast failed for event #{event.id}: {str(e)}")

    @classmethod
    def get_event(cls, event_id: int, user) -> OperationalEvent:
        """
        Retrieves single event if user is authorized participant/admin.
        """
        try:
            event = OperationalEvent.objects.select_related('shipment', 'actor').get(id=event_id)
        except OperationalEvent.DoesNotExist:
            raise ValidationError("Operational event not found.")

        if user.role == Role.ADMIN:
            return event

        if event.shipment:
            if not NotificationService.check_shipment_participant(event.shipment, user):
                raise PermissionDenied("You are not authorized to view events for this shipment.")
            return event

        raise PermissionDenied("You are not authorized to view this event.")

    @classmethod
    def get_shipment_events(cls, shipment: Shipment, user):
        """
        Returns paginated shipment events for authorized participant/admin.
        """
        if user.role != Role.ADMIN and not NotificationService.check_shipment_participant(shipment, user):
            raise PermissionDenied("You are not authorized to view events for this shipment.")

        return OperationalEvent.objects.filter(shipment=shipment).select_related('actor').order_by('-created_at')


class NotificationService:
    """
    Domain service for resolving notification recipients, applying user preferences,
    persisting deduplicated notification records, and managing read/acknowledgement states.
    """

    MAP_EVENT_TO_NOTIFICATION_TYPE = {
        OperationalEventType.ROUTE_DEVIATION: NotificationType.ROUTE_ALERT,
        OperationalEventType.ETA_DELAY: NotificationType.ETA_ALERT,
        OperationalEventType.HIGH_OPERATIONAL_RISK: NotificationType.RISK_ALERT,
        OperationalEventType.INCIDENT_REPORTED: NotificationType.INCIDENT_ALERT,
        OperationalEventType.FUEL_RISK: NotificationType.FUEL_ALERT,
        OperationalEventType.HIGH_MARKET_PRESSURE: NotificationType.MARKET_ALERT,
        OperationalEventType.STALE_GPS: NotificationType.OPERATIONAL_ALERT,
        OperationalEventType.AUTOMATION_RECOMMENDATION: NotificationType.AUTOMATION_ALERT,
        OperationalEventType.AUTOMATION_APPROVAL_REQUIRED: NotificationType.AUTOMATION_ALERT,
        OperationalEventType.AUTOMATION_EXECUTED: NotificationType.AUTOMATION_ALERT,
        OperationalEventType.SHIPMENT_STATUS_CHANGED: NotificationType.SHIPMENT_UPDATE,
        OperationalEventType.PAYMENT_EVENT: NotificationType.OPERATIONAL_ALERT,
        OperationalEventType.SYSTEM_ALERT: NotificationType.SYSTEM_ALERT,
    }

    @classmethod
    def check_shipment_participant(cls, shipment: Shipment, user) -> bool:
        """
        Helper method checking whether user is shipper, transporter, assigned driver, or admin.
        """
        if user.role == Role.ADMIN:
            return True
        if shipment.load and shipment.load.shipper and shipment.load.shipper.user_id == user.id:
            return True
        if shipment.transporter and shipment.transporter.user_id == user.id:
            return True
        if shipment.driver and shipment.driver.user_id == user.id:
            return True
        return False

    @classmethod
    def determine_recipients(cls, event: OperationalEvent) -> list:
        """
        Determines target users authorized to receive notifications for an event.
        """
        recipients = set()

        # Always notify active Admins
        admins = User.objects.filter(role=Role.ADMIN, is_active=True)
        for admin in admins:
            recipients.add(admin)

        if event.shipment:
            shipment = event.shipment
            if shipment.load and shipment.load.shipper and shipment.load.shipper.user:
                recipients.add(shipment.load.shipper.user)
            if shipment.transporter and shipment.transporter.user:
                recipients.add(shipment.transporter.user)
            if shipment.driver and shipment.driver.user:
                recipients.add(shipment.driver.user)

        # Do not notify the actor who triggered the event (unless actor is None)
        if event.actor:
            recipients.discard(event.actor)

        return [r for r in recipients if r and r.is_active]

    @classmethod
    def is_notification_enabled_for_user(cls, user, event: OperationalEvent) -> bool:
        """
        Checks user NotificationPreference flags. Critical severity alerts bypass normal disables.
        """
        pref, _ = NotificationPreference.objects.get_or_create(user=user)

        if event.severity == EventSeverity.CRITICAL:
            return pref.critical_alerts_enabled

        event_type = event.event_type
        if event_type == OperationalEventType.ROUTE_DEVIATION:
            return pref.route_alerts_enabled
        elif event_type == OperationalEventType.ETA_DELAY:
            return pref.eta_alerts_enabled
        elif event_type == OperationalEventType.HIGH_OPERATIONAL_RISK:
            return pref.risk_alerts_enabled
        elif event_type == OperationalEventType.INCIDENT_REPORTED:
            return pref.incident_alerts_enabled
        elif event_type == OperationalEventType.FUEL_RISK:
            return pref.fuel_alerts_enabled
        elif event_type == OperationalEventType.HIGH_MARKET_PRESSURE:
            return pref.market_alerts_enabled
        elif event_type in [OperationalEventType.AUTOMATION_RECOMMENDATION, OperationalEventType.AUTOMATION_APPROVAL_REQUIRED, OperationalEventType.AUTOMATION_EXECUTED]:
            return pref.automation_alerts_enabled
        elif event_type == OperationalEventType.SHIPMENT_STATUS_CHANGED:
            return pref.shipment_updates_enabled
        elif event_type == OperationalEventType.SYSTEM_ALERT:
            return pref.system_alerts_enabled

        return True

    @classmethod
    def create_notifications_for_event(cls, event: OperationalEvent) -> list:
        """
        Creates deduplicated Notification records for target recipients and publishes real-time WebSocket payloads.
        """
        recipients = cls.determine_recipients(event)
        created_notifications = []

        notif_type = cls.MAP_EVENT_TO_NOTIFICATION_TYPE.get(event.event_type, NotificationType.OPERATIONAL_ALERT)

        with transaction.atomic():
            for recipient in recipients:
                if not cls.is_notification_enabled_for_user(recipient, event):
                    continue

                notification, created = Notification.objects.get_or_create(
                    event=event,
                    recipient=recipient,
                    defaults={
                        'shipment': event.shipment,
                        'notification_type': notif_type,
                        'priority': event.severity,
                        'title': event.title,
                        'message': event.description,
                        'data': event.payload,
                    }
                )
                if created:
                    created_notifications.append(notification)

        # Broadcast real-time notification to recipient WebSocket groups
        for notification in created_notifications:
            cls.broadcast_notification_realtime(notification)

        return created_notifications

    @classmethod
    def broadcast_notification_realtime(cls, notification: Notification):
        """
        Sends real-time notification payload to recipient's private WebSocket group.
        """
        try:
            channel_layer = get_channel_layer()
            if not channel_layer:
                return
            group_name = f"notifications.user.{notification.recipient.id}"

            notif_data = {
                "type": "user.notification",
                "notification": {
                    "id": notification.id,
                    "notification_type": notification.notification_type,
                    "priority": notification.priority,
                    "title": notification.title,
                    "message": notification.message,
                    "data": notification.data,
                    "is_read": notification.is_read,
                    "is_acknowledged": notification.is_acknowledged,
                    "shipment_id": notification.shipment_id,
                    "created_at": notification.created_at.isoformat(),
                }
            }
            async_to_sync(channel_layer.group_send)(group_name, notif_data)
        except Exception as e:
            logger.warning(f"Real-time notification WebSocket broadcast failed for notification #{notification.id}: {str(e)}")

    @classmethod
    def mark_as_read(cls, notification_id: int, user) -> Notification:
        """
        Marks single notification as read for authenticated recipient.
        """
        with transaction.atomic():
            try:
                notification = Notification.objects.select_for_update().get(id=notification_id)
            except Notification.DoesNotExist:
                raise ValidationError("Notification not found.")

            if notification.recipient_id != user.id and user.role != Role.ADMIN:
                raise PermissionDenied("You are not authorized to mark this notification as read.")

            if not notification.is_read:
                notification.is_read = True
                notification.read_at = timezone.now()
                notification.save(update_fields=['is_read', 'read_at'])

            return notification

    @classmethod
    def mark_all_as_read(cls, user) -> int:
        """
        Marks all unread notifications for user as read.
        """
        now = timezone.now()
        count = Notification.objects.filter(recipient=user, is_read=False).update(is_read=True, read_at=now)
        return count

    @classmethod
    def acknowledge_notification(cls, notification_id: int, user) -> Notification:
        """
        Acknowledges critical notification for recipient.
        """
        with transaction.atomic():
            try:
                notification = Notification.objects.select_for_update().get(id=notification_id)
            except Notification.DoesNotExist:
                raise ValidationError("Notification not found.")

            if notification.recipient_id != user.id and user.role != Role.ADMIN:
                raise PermissionDenied("You are not authorized to acknowledge this notification.")

            if not notification.is_acknowledged:
                notification.is_acknowledged = True
                notification.acknowledged_at = timezone.now()
                if not notification.is_read:
                    notification.is_read = True
                    notification.read_at = timezone.now()
                notification.save(update_fields=['is_acknowledged', 'acknowledged_at', 'is_read', 'read_at'])

            return notification

    @classmethod
    def get_unread_count(cls, user) -> dict:
        """
        Efficiently calculates unread and critical unread count.
        """
        unread_count = Notification.objects.filter(recipient=user, is_read=False).count()
        critical_unread_count = Notification.objects.filter(
            recipient=user,
            is_read=False,
            priority=EventSeverity.CRITICAL
        ).count()

        return {
            "unread_count": unread_count,
            "critical_unread_count": critical_unread_count
        }
