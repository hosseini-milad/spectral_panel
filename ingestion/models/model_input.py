from datetime import datetime

from mongoengine import DateTimeField, Document, StringField


class ModelInputSecurityData(Document):
    source_file = StringField(required=True)
    normalized_id = StringField(required=True)
    raw_original_id = StringField(required=True)
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "model_input_security_data",
        "indexes": ["source_file", "normalized_id", "raw_original_id"],
    }
