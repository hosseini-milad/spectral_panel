import hashlib
import random


def stratified_sample(docs, sample_ratio=0.1):

    grouped = {}

    # گروه‌بندی بر اساس label
    for doc in docs:
        label = doc.get("label", doc.get("newlabel", 0))

        if label not in grouped:
            grouped[label] = []

        grouped[label].append(doc)

    sampled = []

    for label, items in sorted(grouped.items(), key=lambda item: str(item[0])):

        items = sorted(items, key=lambda item: str(item.get("_id", "")))

        k = min(len(items), max(1, round(len(items) * sample_ratio)))
        source_file = str(items[0].get("source_file", "")) if items else ""
        seed_material = f"{source_file}|{label}|{sample_ratio}".encode("utf-8")
        seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
        sampled.extend(random.Random(seed).sample(items, k))

    return sampled
