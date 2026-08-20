from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from apps.accounts.models import (
    User,
    ShipperProfile,
    TransporterProfile,
    TransporterVerificationAudit,
    DriverProfile,
    FreightForwarderProfile,
    CustomsStaffProfile,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active', 'created_at')
    list_filter = ('role', 'is_staff', 'is_active')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone_number')}),
        ('Role & Permissions', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important Dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )
    readonly_fields = ('date_joined', 'created_at', 'updated_at')
    search_fields = ('email', 'first_name', 'last_name', 'phone_number')
    ordering = ('-created_at',)


@admin.register(ShipperProfile)
class ShipperProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'user', 'trade_license_number', 'tax_id', 'created_at')
    search_fields = ('company_name', 'user__email', 'trade_license_number', 'tax_id')


@admin.register(TransporterProfile)
class TransporterProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'user', 'trade_license_number', 'tax_id', 'verification_status', 'created_at')
    list_filter = ('verification_status',)
    search_fields = ('company_name', 'user__email', 'trade_license_number', 'tax_id')


@admin.register(TransporterVerificationAudit)
class TransporterVerificationAuditAdmin(admin.ModelAdmin):
    list_display = ('transporter', 'performed_by', 'previous_status', 'new_status', 'created_at')
    list_filter = ('previous_status', 'new_status')
    search_fields = ('transporter__company_name', 'performed_by__email', 'reason')
    readonly_fields = ('created_at',)


@admin.register(DriverProfile)
class DriverProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'transporter', 'license_number', 'license_expiration', 'created_at')
    search_fields = ('user__email', 'license_number', 'transporter__company_name')


@admin.register(FreightForwarderProfile)
class FreightForwarderProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'user', 'license_number', 'created_at')
    search_fields = ('company_name', 'user__email', 'license_number')


@admin.register(CustomsStaffProfile)
class CustomsStaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge_number', 'station_location', 'created_at')
    search_fields = ('user__email', 'badge_number', 'station_location')
