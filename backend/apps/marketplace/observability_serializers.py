from rest_framework import serializers


class SystemHealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    timestamp = serializers.DateTimeField()


class SystemReadinessSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.DictField()
    redis = serializers.DictField()
    timestamp = serializers.DateTimeField()


class SystemMetricsSerializer(serializers.Serializer):
    requests = serializers.DictField()
    dependencies = serializers.DictField()
    websocket = serializers.DictField()
    operations = serializers.DictField()
    generated_at = serializers.DateTimeField()


class SystemStatusSerializer(serializers.Serializer):
    application = serializers.CharField()
    environment = serializers.CharField()
    database = serializers.CharField()
    cache = serializers.CharField()
    websocket = serializers.CharField()
    api_version = serializers.CharField()
