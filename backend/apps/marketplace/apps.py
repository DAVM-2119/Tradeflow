from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.marketplace'
    label = 'marketplace'
    verbose_name = 'Marketplace & Fleet Management'
