from rest_framework.views import APIView
from rest_framework.response import Response

from ..serializers.sampling_serializer import SamplingSerializer
from ...pipelines.sampling_pipeline import run_sampling


class SamplingView(APIView):

    def post(self, request):

        serializer = SamplingSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        source_file = serializer.validated_data["source_file"]
        ratio = serializer.validated_data["ratio"]

        count = run_sampling(source_file, ratio)

        return Response({
            "message": "sampling done",
            "count": count
        })