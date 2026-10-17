from mongoengine import DynamicDocument, StringField, DateTimeField
from datetime import datetime


class RawSecurityData(DynamicDocument):
    source_file = StringField(required=True)
    ingestion_id = StringField()
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "security_data"
    }