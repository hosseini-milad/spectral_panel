from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ...models.sampled_data import SampledSecurityData


from ..serializers.pooling_serializer import (
    PoolingSerializer
)


from ...pipelines.pooling_pipeline import (
    run_pooling
)


from ...models.graph_metadata import (
    GraphMetadata
)


class PoolingView(APIView):

    def post(self, request):

        serializer = PoolingSerializer(
            data=request.data
        )


        if not serializer.is_valid():

            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )


        source_file = serializer.validated_data[
            "source_file"
        ]


        ratio = serializer.validated_data[
            "representative_ratio"
        ]


        try:

            # دریافت اطلاعات گراف ذخیره شده
            graph = GraphMetadata.objects(
                source_file=source_file
            ).first()


            if not graph:

                return Response(
                    {
                        "error":
                        "Graph not found"
                    },
                    status=404
                )

            docs = list(
                SampledSecurityData.objects(
                    source_file=source_file
                ).order_by("id").as_pymongo()
            )
            result = run_pooling(
                source_file=source_file,
                edges=graph.edges,
                features=graph.features,
                docs=docs,
                ratio=ratio
            )


            return Response(
                {
                    "message":
                    "Pooling completed",

                    "representatives":
                    len(result)
                }
            )


        except Exception as e:
            import traceback

            traceback.print_exc()


            return Response(
                {
                    "error":str(e)
                },
                status=500
            )
