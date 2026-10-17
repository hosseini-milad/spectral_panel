from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.data_validation import (
    validate_dataset,
)


class Command(BaseCommand):

    requires_system_checks = []

    help = (
        "Validate normalized security data and "
        "graph representative links."
    )

    def add_arguments(self, parser):

        parser.add_argument(
            "--source-file",
            type=str,
            required=False,
            default=None,
            help="Optional source file filter.",
        )

    def handle(self, *args, **options):

        source_file = options.get("source_file")

        self.stdout.write(
            self.style.WARNING(
                "Starting database validation..."
            )
        )

        result = validate_dataset(
            source_file=source_file
        )

        summary = result["summary"]
        link_errors = result["link_violations"]

        self.stdout.write("")
        self.stdout.write("========== DATA SUMMARY ==========")

        self.stdout.write(
            f"Normalized records : "
            f"{summary['normalized_count']}"
        )

        self.stdout.write(
            f"Representatives    : "
            f"{summary['representative_count']}"
        )
        self.stdout.write(f"Sampled records    : {summary['sampled_count']}")
        self.stdout.write(f"Raw records        : {summary['raw_count']}")

        self.stdout.write(
            f"Feature count      : "
            f"{summary['feature_count']}"
        )

        self.stdout.write(f"Label counts       : {summary['label_distribution']}")
        self.stdout.write(
            "Representative class deviations: "
            f"{summary['representative_label_deviation_from_expected']}"
        )
        self.stdout.write(
            f"Sampled/normalized : {summary['sampled_fraction_of_normalized_by_label']}"
        )
        self.stdout.write(
            f"Reps/sampled ratios: {summary['representative_fraction_of_sampled_by_label']}"
        )

        self.stdout.write("")

        range_errors = result["range_violations"]
        self.stdout.write(
            f"Range violations   : {len(range_errors)}"
        )
        for link_name, errors in link_errors.items():
            self.stdout.write(f"{link_name} violations : {len(errors)}")

        class_balance_errors = result["representative_class_balance_violations"]
        self.stdout.write(
            f"Representative class balance violations: {len(class_balance_errors)}"
        )
        for error in class_balance_errors[:10]:
            self.stdout.write(str(error))

        self.stdout.write("")

        if range_errors:

            self.stdout.write(
                self.style.ERROR(
                    "FAILED: Some normalized features "
                    "are outside [0, 1]."
                )
            )

            for error in range_errors[:10]:
                self.stdout.write(
                    str(error)
                )

        any_link_errors = any(link_errors.values())
        any_class_balance_errors = bool(class_balance_errors)
        if any_link_errors:
            self.stdout.write(self.style.ERROR("FAILED: Some data lineage links are invalid."))
            for errors in link_errors.values():
                for error in errors[:10]:
                    self.stdout.write(str(error))

        if any_class_balance_errors:
            self.stdout.write(
                self.style.ERROR(
                    "FAILED: Representative selection does not preserve "
                    "the normalized source class proportions "
                    "(tolerance: 1 per class)."
                )
            )

        if not range_errors and not any_link_errors and not any_class_balance_errors:

            self.stdout.write(
                self.style.SUCCESS(
                    "PASS: Database structure is valid."
                )
            )

        if range_errors or any_link_errors or any_class_balance_errors:
            raise CommandError("Dataset validation failed; see violations above.")

        self.stdout.write("")
        self.stdout.write(
            "========== FEATURE SCHEMA =========="
        )

        for index, feature in enumerate(
            result["feature_schema"],
            start=1,
        ):
            self.stdout.write(
                f"{index:03d}. {feature}"
            )
