from django.urls import path
from apps.marketplace.consumers import UserNotificationConsumer, ShipmentEventConsumer

websocket_urlpatterns = [
    path('ws/notifications/', UserNotificationConsumer.as_asgi()),
    path('ws/shipments/<int:shipment_id>/events/', ShipmentEventConsumer.as_asgi()),
]
