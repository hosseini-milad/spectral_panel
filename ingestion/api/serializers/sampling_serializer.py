from rest_framework import serializers


class SamplingSerializer(serializers.Serializer):
    source_file = serializers.CharField()
    ratio = serializers.FloatField(default=0.1)