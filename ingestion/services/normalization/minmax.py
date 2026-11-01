import math
import numpy as np

LOG_FIELDS = {
    "bytes",
    "bytes_per_packet",
    "bytes_per_sec",
    "duration_s",
    "packets",
    "packets_per_sec",
}

ROBUST_FIELDS = LOG_FIELDS


def compute_min_max(docs, excluded):
    min_max = {}
    robust_values = {key: [] for key in ROBUST_FIELDS}
    
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

                if key in robust_values:
                    if val < 0:
                        continue
                    robust_values[key].append(float(np.log1p(val)))

            except (TypeError, ValueError, OverflowError):
                continue

    for key, values in robust_values.items():
        if not values or key not in min_max:
            continue

        
        min_max[key]["log_min"] = float(min(values))
        min_max[key]["log_max"] = float(max(values))

    return min_max