from mongoengine import (
    Document,
    StringField,
    IntField,
    FloatField,
    DateTimeField,
)


class GraphRepresentative(Document):
    """
    Read-only representation of graph_representatives.
    """

    source_file = StringField()
    original_id = StringField()
    node_index = IntField()
    attention = FloatField()
    label = IntField()
    centrality = FloatField()
    created_at = DateTimeField()

    meta = {
        "collection": "graph_representatives",
    }