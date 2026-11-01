import math
from ingestion.services.normalization.minmax import LOG_FIELDS, ROBUST_FIELDS
from .encoders import is_ip, normalize_ip, normalize_text
from ...utils.constants import BINARY_FIELDS, LABEL_FIELD


class Normalizer:

    def __init__(self, min_max):
        self.min_max = min_max

    @classmethod
    def _bounded(cls, value):
        """Return a finite value bounded to [0, 1], without decimal rounding."""
        try:
            number = float(value)

            if not math.isfinite(number):
                return 0

            return min(1.0, max(0.0, number))

        except (TypeError, ValueError, OverflowError):
            return 0
    def normalize_numeric(self, key, value):
        try:
            value = float(value)

            if not math.isfinite(value):
                return 0

            if key not in self.min_max:
                return None

            bounds = self.min_max[key]

            if key in LOG_FIELDS:
                if value < 0:
                    return 0
                value = math.log1p(value)

            if key in LOG_FIELDS and "log_min" in bounds and "log_max" in bounds:
                min_v = float(bounds["log_min"])
                max_v = float(bounds["log_max"])
            else:
                min_v = float(bounds["min"])
                max_v = float(bounds["max"])

            if not math.isfinite(min_v) or not math.isfinite(max_v):
                return 0

            if max_v <= min_v:
                return 0

            scaled = (value - min_v) / (max_v - min_v)
            return self._bounded(scaled)

        except (TypeError, ValueError, OverflowError, KeyError):
            return None

    @staticmethod
    def normalize_label(value):
        label = str(value).strip().lower()
        if label in {"benign", "normal", "0", "0.0", "false", "none", "", "nan"}:
            return 0
        # The label is binary for this phase; any known non-normal class is attack.
        return 1

    def normalize(self, key, value):
        if key == LABEL_FIELD:
            return self.normalize_label(value)

        if key in BINARY_FIELDS:
            try:
                return int(float(value) != 0)
            except (TypeError, ValueError, OverflowError):
                return 0

        if value is None:
            return 0

        if isinstance(value, str) and is_ip(value):
            return self._bounded(normalize_ip(value))

        num = self.normalize_numeric(key, value)
        if num is not None:
            return num

        return self._bounded(normalize_text(value))
