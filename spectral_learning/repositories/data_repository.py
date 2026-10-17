from typing import Optional

from bson import ObjectId

from ..models.normalized_data import NormalizedSecurityData
from ..models.graph_representative import GraphRepresentative
from mongoengine import get_connection


class SecurityDataRepository:
    """
    Centralized read-only access to MongoDB collections.
    """

    @staticmethod
    def get_normalized_records(
        source_file: Optional[str] = None,
    ):
        query = NormalizedSecurityData.objects

        if source_file:
            query = query(source_file=source_file)

        return list(query.as_pymongo())

    @staticmethod
    def get_representatives(
        source_file: Optional[str] = None,
    ):
        query = GraphRepresentative.objects

        if source_file:
            query = query(source_file=source_file)

        return list(query.as_pymongo())

    @staticmethod
    def get_collection_records(
        collection_name: str,
        source_file: Optional[str] = None,
    ):
        """Read documents from an ingestion-owned MongoDB collection."""
        collection = get_connection(alias="default")["siem_db"][collection_name]
        query = {"source_file": source_file} if source_file else {}
        return list(collection.find(query))

    @staticmethod
    def get_normalized_by_id(record_id: str):
        """
        Retrieve one normalized record by MongoDB _id.
        """

        if not ObjectId.is_valid(record_id):
            return None

        return NormalizedSecurityData.objects(
            id=ObjectId(record_id)
        ).first()

    @staticmethod
    def count_normalized(source_file: Optional[str] = None):
        query = NormalizedSecurityData.objects

        if source_file:
            query = query(source_file=source_file)

        return query.count()

    @staticmethod
    def count_representatives(source_file: Optional[str] = None):
        query = GraphRepresentative.objects

        if source_file:
            query = query(source_file=source_file)

        return query.count()
