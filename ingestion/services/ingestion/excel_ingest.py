import math
from pathlib import Path

import numpy as np
import pandas as pd

from ...models.raw_data import RawSecurityData


def _column_name(value):
    name = str(value).strip().lower().replace(" ", "_")
    if name == "newlabel":
        return "label"
    return name


def read_standardized_excel(file_path):
    """Read an Excel dataset and normalize its header conventions."""
    frame = pd.read_excel(file_path)
    unnamed = sum(str(column).strip().lower().startswith("unnamed:") for column in frame.columns)

    # DS (4).xlsx has a metadata row above its actual header. Promote that
    # row only when the workbook clearly has a mostly-unnamed first header.
    if unnamed >= max(3, len(frame.columns) // 2) and not frame.empty:
        candidate = [_column_name(value) for value in frame.iloc[0].tolist()]
        if "source_port" in candidate and "label" in candidate:
            frame.columns = frame.iloc[0].tolist()
            frame = frame.iloc[1:].reset_index(drop=True)

    frame.columns = [_column_name(column) for column in frame.columns]
    if len(set(frame.columns)) != len(frame.columns):
        duplicates = sorted({name for name in frame.columns if frame.columns.count(name) > 1})
        raise ValueError(f"Duplicate columns after standardization: {duplicates}")
    if "label" not in frame.columns:
        raise ValueError("No label/newlabel column found")
    return frame


def _clean_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def ingest_dataframe(frame, source_file):
    """Replace one source file's raw rows with standardized-header records."""
    if frame.empty:
        raise ValueError(f"No data rows found in {source_file!r}")

    RawSecurityData.objects(source_file=source_file).delete()
    documents = []
    for row in frame.to_dict(orient="records"):
        clean_row = {key: _clean_value(value) for key, value in row.items()}
        label = clean_row.get("label")
        if label is None or not str(label).strip():
            raise ValueError(f"Missing label in {source_file!r}")
        clean_row["source_file"] = source_file
        documents.append(RawSecurityData(**clean_row))

    RawSecurityData.objects.insert(documents, load_bulk=False)
    return len(documents), list(frame.columns)


def ingest_excel(file):
    source_file = Path(file.name).name
    frame = read_standardized_excel(file)
    return ingest_dataframe(frame, source_file)
