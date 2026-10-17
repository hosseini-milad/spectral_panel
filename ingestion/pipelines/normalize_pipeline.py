from ..models.raw_data import RawSecurityData
from ..models.normalized_data import NormalizedSecurityData
from ..services.normalization.minmax import compute_min_max
from ..services.normalization.normalize_service import Normalizer
from ..utils.constants import EXCLUDED_FIELDS, PASSTHROUGH_FIELDS


def run_normalization(source_file):

    docs = list(RawSecurityData.objects(source_file=source_file))

    if not docs:
        return 0

    min_max = compute_min_max(docs, EXCLUDED_FIELDS)

    normalizer = Normalizer(min_max)

    # جلوگیری از تکرار
    NormalizedSecurityData.objects(source_file=source_file).delete()

    result = []

    for doc in docs:

        new_doc = {
            "original_id": str(doc.id),
            "source_file": doc.source_file
        }

        for key, value in doc.to_mongo().items():

            if key in EXCLUDED_FIELDS:
                if key in PASSTHROUGH_FIELDS:
                    new_doc[key] = value
                continue

            try:
                val = normalizer.normalize(key, value)
                if val is None:
                    val = 0
            except:
                val = 0

            new_doc[key] = val

        result.append(NormalizedSecurityData(**new_doc))

    if result:
        NormalizedSecurityData.objects.insert(result)

    return len(result)
