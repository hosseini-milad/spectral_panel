from mongoengine import (
    Document,
    StringField,
    IntField,
    FloatField,
    DateTimeField
)

from datetime import datetime


class GraphRepresentative(Document):

    source_file = StringField(
        required=True
    )

    original_id = StringField(
        required=True
    )

    node_index = IntField()

    attention = FloatField()

    label = IntField()

    centrality = FloatField()

    created_at = DateTimeField(
        default=datetime.utcnow
    )


    meta = {
        "collection": "graph_representatives",
        "indexes": [
            "source_file",
            "original_id"
        ]
    }