from datetime import date, timedelta
from hashlib import sha256
from uuid import uuid4
from bson import ObjectId


def build_normal_day(db, dry_run=True):
    collection = db.security_data
    start = date(2026, 6, 21)
    target = "2026-06-20"
    block_size = 20_000
    day_count = 10
    expected_total = day_count * block_size
    plan = []

    # بررسی ظرفیت تمام روزها قبل از نوشتن
    for i in range(day_count):
        source_day = (start + timedelta(days=i)).isoformat()
        query = {
            "source_day": source_day,
            "label": 0,
            "is_synthetic_normal": {"$ne": True},
            "is_artificial_day": {"$ne": True},
        }
        available = collection.count_documents(query)
        offset = i * block_size
        plan.append({
            "source_day": source_day,
            "skip": offset,
            "take": block_size,
            "available": available,
        })

    shortages = [
        row for row in plan
        if row["available"] < row["skip"] + row["take"]
    ]
    if shortages:
        raise ValueError(f"داده نرمال کافی نیست: {shortages}")

    # داده روز مقصد موجود را حذف یا مخلوط نمی‌کنیم.
    if collection.find_one({"source_day": target}, {"_id": 1}):
        raise ValueError("روز مقصد قبلاً داده دارد؛ ساخت متوقف شد.")

    run_id = uuid4().hex

    try:
        for row in plan:
            query = {
                "source_day": row["source_day"],
                "label": 0,
                "is_synthetic_normal": {"$ne": True},
                "is_artificial_day": {"$ne": True},
            }
            records = list(
                collection.find(query)
                .sort("_id", 1)
                .skip(row["skip"])
                .limit(block_size)
            )
            if len(records) != block_size:
                raise ValueError("داده مبدأ هنگام ساخت تغییر کرده است.")

            for position, record in enumerate(records):
                original_id = record["_id"]
                key = f"artificial-v2|{target}|{original_id}"
                record["_id"] = ObjectId(
                    sha256(key.encode()).hexdigest()[:24]
                )
                record["source_day"] = target
                record["is_artificial_day"] = True
                record["artificial_day"] = {
                    "run_id": run_id,
                    "original_id": original_id,
                    "original_source_day": row["source_day"],
                    "source_rank": row["skip"] + position,
                }

            collection.insert_many(records, ordered=True)

        count = collection.count_documents({
            "artificial_day.run_id": run_id
        })
        if count != 400_000:
            raise ValueError(f"تعداد خروجی غیرمنتظره است: {count}")

        return {"target_day": target, "inserted": count, "run_id": run_id}

    except Exception:
        # فقط کپی‌های ساخته‌شده توسط همین اجرا پاک می‌شوند.
        collection.delete_many({"artificial_day.run_id": run_id})
        raise

if __name__ == "__main__":
    import argparse
    from pymongo import MongoClient

    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    with MongoClient("mongodb://localhost:27017") as client:
        result = build_normal_day(
            client["siem_db"],
            dry_run=not args.write,
        )
        print(result)