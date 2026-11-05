from rest_framework import serializers


class JobSerializer(serializers.Serializer):
    id=serializers.UUIDField()
    action=serializers.CharField()
    command=serializers.CharField()
    parameters=serializers.JSONField()
    status=serializers.ChoiceField(choices=['queued','running','succeeded','failed','cancelled','interrupted'])
    created_at=serializers.DateTimeField()
    updated_at=serializers.DateTimeField()
    started_at=serializers.DateTimeField(allow_null=True)
    finished_at=serializers.DateTimeField(allow_null=True)
    error=serializers.JSONField(allow_null=True)
    detail_url=serializers.CharField()
    logs_url=serializers.CharField()
    log_artifact=serializers.CharField()


class SubmissionSerializer(serializers.Serializer):
    job=JobSerializer()
    created=serializers.BooleanField()


class PageQuery(serializers.Serializer):
    limit=serializers.IntegerField(default=50,min_value=1,max_value=200)
    offset=serializers.IntegerField(default=0,min_value=0,max_value=1000000)


class JobQuery(PageQuery):
    status=serializers.ChoiceField(required=False,choices=['queued','running','succeeded','failed','cancelled','interrupted'])


class LogQuery(serializers.Serializer):
    offset=serializers.IntegerField(default=0,min_value=0)
    limit=serializers.IntegerField(default=65536,min_value=4,max_value=262144)


class ArtifactQuery(serializers.Serializer):
    path=serializers.CharField(required=False,default='',allow_blank=True)


class ArtifactListQuery(ArtifactQuery):
    limit=serializers.IntegerField(default=200,min_value=1,max_value=1000)
    offset=serializers.IntegerField(default=0,min_value=0)
