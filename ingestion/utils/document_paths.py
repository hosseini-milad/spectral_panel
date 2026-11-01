"""Shared layout for generated documents; input datasets stay under files/."""
import re
from pathlib import Path

from django.conf import settings


def safe_name(value):
    return re.sub(r"[^\w.=-]+", "_", str(value)).strip("._") or "unknown"


def document_directory(category, source_file=None, *, layer=1, day=None, chunk=None):
    if category not in {"nominal", "component", "report", "hierarchy"}:
        raise ValueError(f"Unknown document category: {category}")
    if int(layer) < 1:
        raise ValueError("layer must be positive")
    source = str(source_file or "")
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", source)
    chunk_match = re.search(r"(?:^|-)chunk-(\d+)(?:-|$)", source)
    day = day or (date_match.group() if date_match else "unknown-day")
    if chunk is None and chunk_match:
        chunk = int(chunk_match.group(1))
    scope = f"chunk-{int(chunk)}" if chunk is not None else "whole-day"
    directory = Path(settings.BASE_DIR) / "document" / category / f"layer{int(layer)}" / safe_name(day) / scope
    # Different graph variants must never overwrite each other's reports.
    if source:
        directory /= safe_name(source)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
