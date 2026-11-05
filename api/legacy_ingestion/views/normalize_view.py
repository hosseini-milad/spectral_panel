from rest_framework.views import APIView
from rest_framework.response import Response

from ..serializers.normalize_serializer import NormalizeSerializer
from ingestion.pipelines.normalize_pipeline import run_normalization


class NormalizeView(APIView):

    def post(self, request):

        serializer = NormalizeSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        source_file = serializer.validated_data["source_file"]

        count = run_normalization(source_file)

        return Response({
            "message": "normalized",
            "count": count
        })