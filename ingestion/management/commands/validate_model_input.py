from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Validate data lineage and representative class balance."

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)

    def handle(self, *args, **options):
        call_command(
            "validate_data",
            source_file=options["source_file"],
        )
