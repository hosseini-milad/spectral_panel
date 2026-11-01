from datetime import datetime

from mongoengine import (
    Document,
    StringField,
    IntField,
    FloatField,
    DateTimeField,
)


class GraphRepresentative(Document):
    source_file = StringField(required=True)
    original_id = StringField(required=True)
    node_index = IntField()

    # String representation of GraphComponent.component_id.
    component_id = StringField()
    component_index = IntField()

    attention = FloatField()
    label = IntField()
    centrality = FloatField()
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "graph_representatives",
        "indexes": [
            "source_file",
            "original_id",
            "component_id",
            ("source_file", "component_id"),
        ],
    }
