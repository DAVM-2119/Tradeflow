from django.urls import path
from apps.marketplace.views import (
    TransporterListView,
    TransporterMeProfileView,
    TransporterVehicleListCreateView,
    TransporterVehicleDetailView,
    TransporterVerificationView,
    TransporterVerificationAuditListView,
    LoadListCreateView,
    LoadDetailView,
    LoadCancelView,
    LoadBidsListCreateView,
    BidAcceptView,
    BidWithdrawView,
    TransporterMyBidsView,
    ShipmentListView,
    ShipmentDetailView,
    ShipmentAssignDriverView,
    ShipmentStatusUpdateView,
    ShipmentLocationView,
    ShipmentTrackingHistoryView,
    ShipmentDocumentListUploadView,
    DocumentDetailView,
    DocumentDownloadView,
    ShipmentPODView,
    PODConfirmView,
    PODDisputeView,
    RatingListCreateView,
)

urlpatterns = [
    # Transporters & Fleet
    path('transporters/', TransporterListView.as_view(), name='transporter-list'),
    path('transporters/me/', TransporterMeProfileView.as_view(), name='transporter-me'),
    path('transporters/me/vehicles/', TransporterVehicleListCreateView.as_view(), name='transporter-vehicle-list-create'),
    path('transporters/me/vehicles/<int:pk>/', TransporterVehicleDetailView.as_view(), name='transporter-vehicle-detail'),
    path('transporters/<int:pk>/verification/', TransporterVerificationView.as_view(), name='transporter-verification'),
    path('transporters/<int:pk>/verification/history/', TransporterVerificationAuditListView.as_view(), name='transporter-verification-audit'),

    # Cargo Loads & Spot Market Bids
    path('loads/', LoadListCreateView.as_view(), name='load-list-create'),
    path('loads/<int:pk>/', LoadDetailView.as_view(), name='load-detail'),
    path('loads/<int:pk>/cancel/', LoadCancelView.as_view(), name='load-cancel'),
    path('loads/<int:pk>/bids/', LoadBidsListCreateView.as_view(), name='load-bids-list-create'),
    path('bids/<int:pk>/accept/', BidAcceptView.as_view(), name='bid-accept'),
    path('bids/<int:pk>/withdraw/', BidWithdrawView.as_view(), name='bid-withdraw'),
    path('bids/me/', TransporterMyBidsView.as_view(), name='transporter-bids-me'),

    # Shipments & Real-Time Tracking
    path('shipments/', ShipmentListView.as_view(), name='shipment-list'),
    path('shipments/<int:pk>/', ShipmentDetailView.as_view(), name='shipment-detail'),
    path('shipments/<int:pk>/assign-driver/', ShipmentAssignDriverView.as_view(), name='shipment-assign-driver'),
    path('shipments/<int:pk>/status/', ShipmentStatusUpdateView.as_view(), name='shipment-status-update'),
    path('shipments/<int:pk>/location/', ShipmentLocationView.as_view(), name='shipment-location'),
    path('shipments/<int:pk>/tracking/', ShipmentTrackingHistoryView.as_view(), name='shipment-tracking-history'),

    # Phase 7: Document Management & Digital Proof of Delivery (e-POD)
    path('shipments/<int:pk>/documents/', ShipmentDocumentListUploadView.as_view(), name='shipment-document-list-upload'),
    path('documents/<int:pk>/', DocumentDetailView.as_view(), name='document-detail'),
    path('documents/<int:pk>/download/', DocumentDownloadView.as_view(), name='document-download'),
    path('shipments/<int:pk>/pod/', ShipmentPODView.as_view(), name='shipment-pod'),
    path('pod/<int:pk>/confirm/', PODConfirmView.as_view(), name='pod-confirm'),
    path('pod/<int:pk>/dispute/', PODDisputeView.as_view(), name='pod-dispute'),

    # Ratings
    path('ratings/', RatingListCreateView.as_view(), name='rating-list-create'),
]
