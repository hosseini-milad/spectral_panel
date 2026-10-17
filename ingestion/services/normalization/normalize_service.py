import math

from .encoders import is_ip, normalize_ip, normalize_text
from ...utils.constants import BINARY_FIELDS, LABEL_FIELD


class Normalizer:
    DECIMALS = 3

    def __init__(self, min_max):
        self.min_max = min_max

    @classmethod
    def _bounded(cls, value):
        """Return a finite [0, 1] value rounded to at most three decimals."""
        try:
            number = float(value)
            if not math.isfinite(number):
                return 0
            return round(min(1.0, max(0.0, number)), cls.DECIMALS)
        except (TypeError, ValueError, OverflowError):
            return 0

    def normalize_numeric(self, key, value):
        try:
            value = float(value)
            if not math.isfinite(value):
                return 0
            if key not in self.min_max:
                return None

            min_v = float(self.min_max[key]["min"])
            max_v = float(self.min_max[key]["max"])
            if not math.isfinite(min_v) or not math.isfinite(max_v):
                return 0
            if max_v == min_v:
                return 0
            return self._bounded((value - min_v) / (max_v - min_v))
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
