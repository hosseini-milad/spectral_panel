from mongoengine import (
    Document,
    StringField,
    DictField,
    ListField,
    BooleanField,
    IntField,
    DateTimeField
)

from datetime import datetime


class GraphMetadata(Document):

    source_file = StringField(required=True)

    graph_path = StringField()

    representative_graph_path = StringField()
    
    stats = DictField()

    # یال های گراف
    edges = ListField(
        DictField()
    )

    # ماتریس ویژگی نودها
    features = ListField(
        ListField()
    )

    # Ordered sampled-record ids let edge endpoints resolve to actual flow nodes.
    node_ids = ListField(StringField())
    node_labels = ListField(IntField())
    source_day = StringField()
    candidate_generation = StringField()
    is_random = BooleanField()
    graph_parameters = DictField()

    created_at = DateTimeField(
        default=datetime.utcnow
    )


    meta = {
        "collection": "graph_metadata"
    }
