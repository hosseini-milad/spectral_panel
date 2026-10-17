from mongoengine import Document, StringField, IntField, ListField, DateTimeField
from datetime import datetime


class DatasetMetadata(Document):
    source_file = StringField()
    columns = ListField(StringField())
    record_count = IntField()
    created_at = DateTimeField(default=datetime.utcnow)