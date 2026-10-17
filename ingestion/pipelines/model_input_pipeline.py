from ingestion.models.model_input import ModelInputSecurityData
from ingestion.models.normalized_data import NormalizedSecurityData


def prepare_model_input(source_file):
    """Refresh normalized-to-raw lineage rows for a source dataset."""
    normalized = list(
        NormalizedSecurityData.objects(source_file=source_file).as_pymongo()
    )
    if not normalized:
        raise ValueError(f"No normalized records found for {source_file!r}")

    prepared = []
    for doc in normalized:
        raw_id = doc.get("original_id")
        if raw_id is None or str(raw_id) == "":
            raise ValueError(
                f"Missing original_id in normalized record {doc.get('_id')}"
            )
        prepared.append(ModelInputSecurityData(
            source_file=source_file,
            normalized_id=str(doc["_id"]),
            raw_original_id=str(raw_id),
        ))

    ModelInputSecurityData.objects(source_file=source_file).delete()
    if prepared:
        ModelInputSecurityData.objects.insert(prepared, load_bulk=False)

    return {
        "source_file": source_file,
        "normalized_count": len(normalized),
        "model_input_count": len(prepared),
    }
