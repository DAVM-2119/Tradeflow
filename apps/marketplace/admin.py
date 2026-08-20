from django.contrib import admin
from apps.marketplace.models import Vehicle, CargoLoad, Bid, Shipment, LocationUpdate, ShipmentMilestone, Rating


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate_number', 'transporter', 'vehicle_type', 'capacity_tonnes', 'fuel_type', 'is_active', 'created_at')
    list_filter = ('vehicle_type', 'fuel_type', 'is_active')
    search_fields = ('plate_number', 'transporter__company_name', 'insurance_policy_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CargoLoad)
class CargoLoadAdmin(admin.ModelAdmin):
    list_display = ('title', 'shipper', 'origin', 'destination', 'weight_tonnes', 'required_vehicle_type', 'target_price', 'status', 'created_at')
    list_filter = ('status', 'required_vehicle_type', 'origin', 'destination')
    search_fields = ('title', 'shipper__company_name', 'origin', 'destination', 'cargo_type')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ('load', 'transporter', 'proposed_vehicle', 'amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('load__title', 'transporter__company_name', 'notes')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ('tracking_number', 'load', 'transporter', 'vehicle', 'driver', 'status', 'created_at')
    list_filter = ('status', 'origin', 'destination')
    search_fields = ('tracking_number', 'transporter__company_name', 'driver__user__email', 'origin', 'destination')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(LocationUpdate)
class LocationUpdateAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'latitude', 'longitude', 'speed_kmh', 'location_name', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('shipment__tracking_number', 'location_name')
    readonly_fields = ('timestamp',)


@admin.register(ShipmentMilestone)
class ShipmentMilestoneAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'status', 'location_name', 'updated_by', 'timestamp')
    list_filter = ('status', 'timestamp')
    search_fields = ('shipment__tracking_number', 'notes', 'location_name')
    readonly_fields = ('timestamp',)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('rater', 'ratee', 'stars', 'shipment_id', 'created_at')
    list_filter = ('stars',)
    search_fields = ('rater__email', 'ratee__email', 'comment')
    readonly_fields = ('created_at', 'updated_at')
