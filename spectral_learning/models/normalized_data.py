from mongoengine import DynamicDocument


class NormalizedSecurityData(DynamicDocument):
    """
    Read-only representation of normalized_security_data.

    The collection contains dynamically stored normalized
    security features. Feature values are expected to be
    normalized to [0, 1].
    """

    meta = {
        "collection": "normalized_security_data",
    }