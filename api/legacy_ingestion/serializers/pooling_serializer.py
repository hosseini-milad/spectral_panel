from rest_framework import serializers


class PoolingSerializer(serializers.Serializer):

    source_file = serializers.CharField(
        required=True
    )

    representative_ratio = serializers.FloatField(
        required=False,
        default=0.05
    )

    def validate_representative_ratio(self, value):

        if value <= 0 or value >= 1:
            raise serializers.ValidationError(
                "ratio must be between 0 and 1"
            )

        return value