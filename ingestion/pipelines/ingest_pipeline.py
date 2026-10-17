from ..services.ingestion.excel_ingest import ingest_excel
from ..models.dataset_metadata import DatasetMetadata
from pathlib import Path


def run_ingestion(file):

    count, columns = ingest_excel(file)
    source_file = Path(file.name).name

    DatasetMetadata.objects(source_file=source_file).delete()

    DatasetMetadata(
        source_file=source_file,
        columns=columns,
        record_count=count
    ).save()

    return count
