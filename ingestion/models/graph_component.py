from datetime import datetime

from mongoengine import (
    Document,
    StringField,
    IntField,
    ListField,
    DictField,
    DateTimeField,
)


class GraphComponent(Document):
    """A connected component of a layer-1 graph, stored as a first-class entity."""

    component_id = StringField(required=True)
    source_file = StringField(required=True)
    source_day = StringField()
    layer = IntField(default=1)
    component_index = IntField(required=True)

    node_indices = ListField(IntField())
    node_ids = ListField(StringField())
    node_count = IntField(default=0)

    representative_ids = ListField(StringField())
    representative_original_ids = ListField(StringField())
    representative_node_indices = ListField(IntField())
    representative_count = IntField(default=0)

    # Numeric means/stds over selected representatives only.
    mean_features = DictField()
    feature_std = DictField()
    feature_observation_counts = DictField()
    feature_fields = ListField(StringField())

    component_statistics = DictField()
    created_at = DateTimeField(default=datetime.utcnow)

    meta = {
        "collection": "graph_components",
        "indexes": [
            {"fields": ["component_id"], "unique": True},
            "source_file",
            "source_day",
            {"fields": ["source_file", "component_index"], "unique": True},
        ],
    }
