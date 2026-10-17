from mongoengine import DynamicDocument, StringField, DateTimeField
from datetime import datetime


class NormalizedSecurityData(DynamicDocument):
    source_file = StringField()
    original_id = StringField()
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "normalized_security_data"
    }