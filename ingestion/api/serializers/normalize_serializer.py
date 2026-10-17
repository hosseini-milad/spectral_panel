from rest_framework import serializers


class NormalizeSerializer(serializers.Serializer):
    source_file = serializers.CharField()