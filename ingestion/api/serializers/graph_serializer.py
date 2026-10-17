
from rest_framework import serializers


class GraphSerializer(serializers.Serializer):
    source_day = serializers.DateField(
        input_formats=["%Y-%m-%d"],
        format="%Y-%m-%d",
    )

    candidate_generation = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
    )

    is_random = serializers.BooleanField(
        required=False,
        allow_null=True,
    )

    k = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
    )

    threshold = serializers.FloatField(
        required=False,
        default=0.95,
        min_value=-1.0,
        max_value=1.0,
    )

    degree_cap = serializers.IntegerField(
        required=False,
        default=100,
        min_value=1,
    )

    workers = serializers.IntegerField(
        required=False,
        default=-1,
    )

    create_visualization = serializers.BooleanField(
        required=False,
        default=True,
    )
