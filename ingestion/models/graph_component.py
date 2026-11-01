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
    graph_collection = StringField(default="graph_metadata")
    graph_revision = StringField()
    chunk_index = IntField(null=True)
    node_collection = StringField()
    node_original_ids = ListField(StringField())
    node_lineage = ListField(DictField())
    parent_component_ids = ListField(StringField())
    component_index = IntField(required=True)

    node_indices = ListField(IntField())
    node_ids = ListField(StringField())
    node_count = IntField(default=0)

    representative_ids = ListField(StringField())
    representative_original_ids = ListField(StringField())
    representative_node_indices = ListField(IntField())
    representative_count = IntField(default=0)

    # Numeric summaries over ALL member nodes; representative summaries are separate.
    mean_features = DictField()
    feature_std = DictField()
    feature_observation_counts = DictField()
    feature_fields = ListField(StringField())
    representative_profile = DictField()
    categorical_profile = DictField()
    profile_scope = StringField(default="all_component_nodes")
    missing_node_ids = ListField(StringField())

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
