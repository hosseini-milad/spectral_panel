import math

from ...utils.constants import BINARY_FIELDS


def compute_min_max(docs, excluded):

    min_max = {}

    for doc in docs:
        for key, value in doc.to_mongo().items():

            if key in excluded or key in BINARY_FIELDS or isinstance(value, bool):
                continue

            try:
                val = float(value)
                if not math.isfinite(val):
                    continue

                if key not in min_max:
                    min_max[key] = {"min": val, "max": val}

                min_max[key]["min"] = min(min_max[key]["min"], val)
                min_max[key]["max"] = max(min_max[key]["max"], val)

            except:
                continue

    return min_max
