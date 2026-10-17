from mongoengine import DynamicDocument, StringField, DateTimeField
from datetime import datetime


class SampledSecurityData(DynamicDocument):
    source_file = StringField()
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "sampled_security_data"
    }