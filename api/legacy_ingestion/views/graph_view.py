
from rest_framework.views import APIView
from rest_framework.response import Response

from ..serializers.graph_serializer import GraphSerializer
from ingestion.pipelines.graph_pipeline import run_graph_pipeline


class GraphView(APIView):

    def post(self, request):
        serializer = GraphSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        params = serializer.validated_data

        try:
            stats = run_graph_pipeline(
                source_day=params["source_day"].isoformat(),
                candidate_generation=params.get("candidate_generation"),
                is_random=params.get("is_random"),
                k=params["k"],
                threshold=params["threshold"],
                degree_cap=params["degree_cap"],
                workers=params["workers"],
                create_visualization=params["create_visualization"],
            )
        except Exception as exc:
            return Response(
                {
                    "message": "graph creation failed",
                    "error": str(exc),
                },
                status=500,
            )

        if stats is None:
            return Response(
                {
                    "message": "No sampled records found",
                    "stats": None,
                },
                status=404,
            )

        return Response(
            {
                "message": "graph created",
                "stats": stats,
            },
            status=200,
        )
