from ..models.normalized_data import NormalizedSecurityData
from ..models.sampled_data import SampledSecurityData
from ..services.sampling.adaptive_sampling import adaptive_sampling


def run_sampling(source_file, ratio=0.1):

    docs = list(
        NormalizedSecurityData.objects(source_file=source_file).as_pymongo()
    )

    if not docs:
        return 0

    sampled_docs = adaptive_sampling(docs, ratio)

    # حذف قبلی‌ها
    SampledSecurityData.objects(source_file=source_file).delete()

    result = []

    for doc in sampled_docs:

        doc.pop("_id", None)

        result.append(SampledSecurityData(**doc))

    if result:
        SampledSecurityData.objects.insert(result)

    return len(result)
