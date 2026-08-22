import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from apps.accounts.models import Role
from apps.marketplace.models import Shipment
from apps.marketplace.realtime_services import NotificationService

logger = logging.getLogger(__name__)


@database_sync_to_async
def is_authorized_shipment_participant(shipment_id: int, user) -> bool:
    """
    Verifies if user is an authorized participant or Admin for the target shipment.
    """
    try:
        shipment = Shipment.objects.select_related('load__shipper', 'transporter', 'driver').get(id=shipment_id)
        return NotificationService.check_shipment_participant(shipment, user)
    except Shipment.DoesNotExist:
        return False


class UserNotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for personal real-time notification stream (/ws/notifications/).
    """

    async def connect(self):
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            logger.warning("Unauthenticated WebSocket connection attempt to /ws/notifications/ rejected.")
            await self.close(code=4001)
            return

        self.group_name = f"notifications.user.{self.user.id}"

        # Join personal user notification channel group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        logger.info(f"WebSocket client connected to private notifications group for User #{self.user.id}")

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        # Ping/Pong heartbeat support
        if text_data:
            try:
                data = json.loads(text_data)
                if data.get('type') == 'ping':
                    await self.send(text_data=json.dumps({"type": "pong"}))
            except Exception:
                pass

    async def user_notification(self, event):
        """
        Handler pushing real-time notification to client.
        """
        await self.send(text_data=json.dumps(event.get('notification', {})))


class ShipmentEventConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time shipment operational event streams (/ws/shipments/{shipment_id}/events/).
    """

    async def connect(self):
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated:
            logger.warning("Unauthenticated WebSocket connection attempt to shipment events rejected.")
            await self.close(code=4001)
            return

        self.shipment_id = self.scope['url_route']['kwargs'].get('shipment_id')

        # Verify shipment participation / admin authorization
        authorized = await is_authorized_shipment_participant(self.shipment_id, self.user)
        if not authorized:
            logger.warning(f"User #{self.user.id} denied unauthorized WebSocket access to shipment #{self.shipment_id} events.")
            await self.close(code=4003)
            return

        self.group_name = f"shipments.{self.shipment_id}.events"

        # Join shipment events channel group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()
        logger.info(f"User #{self.user.id} joined shipment #{self.shipment_id} event stream group.")

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            try:
                data = json.loads(text_data)
                if data.get('type') == 'ping':
                    await self.send(text_data=json.dumps({"type": "pong"}))
            except Exception:
                pass

    async def shipment_event(self, event):
        """
        Handler pushing real-time shipment event to client.
        """
        await self.send(text_data=json.dumps(event.get('event', {})))
