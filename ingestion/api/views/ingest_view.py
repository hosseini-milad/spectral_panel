from rest_framework.views import APIView
from rest_framework.response import Response

from ...pipelines.ingest_pipeline import run_ingestion


class IngestView(APIView):

    def post(self, request):

        files = request.FILES.getlist("files")

        total = 0

        for file in files:
            total += run_ingestion(file)

        return Response({
            "message": "ingested",
            "total": total
        })