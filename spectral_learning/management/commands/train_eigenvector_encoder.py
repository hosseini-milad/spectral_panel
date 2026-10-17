from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.eigenvector_training import train_eigenvector_encoder


class Command(BaseCommand):
    help = "Train a self-supervised eigenvector-aware graph encoder."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("source_file", type=str)
        parser.add_argument("--scales", default="minute")
        parser.add_argument("--epochs", type=int, default=50)
        parser.add_argument("--hidden-dim", type=int, default=64)
        parser.add_argument("--embedding-dim", type=int, default=32)
        parser.add_argument("--learning-rate", type=float, default=0.001)
        parser.add_argument("--mask-rate", type=float, default=0.15)
        parser.add_argument("--spectral-weight", type=float, default=0.2)
        parser.add_argument("--seed", type=int, default=17)
        parser.add_argument("--checkpoint", type=str, default=None)

    def handle(self, *args, **options):
        scales = tuple(scale.strip() for scale in options["scales"].split(",") if scale.strip())
        if not scales or any(scale not in {"minute", "hour", "day"} for scale in scales):
            raise CommandError("--scales must be a comma-separated subset of minute,hour,day")
        if options["epochs"] < 1:
            raise CommandError("--epochs must be positive")
        try:
            result = train_eigenvector_encoder(
                source_file=options["source_file"],
                scales=scales,
                epochs=options["epochs"],
                hidden_dim=options["hidden_dim"],
                embedding_dim=options["embedding_dim"],
                learning_rate=options["learning_rate"],
                mask_rate=options["mask_rate"],
                spectral_weight=options["spectral_weight"],
                seed=options["seed"],
                checkpoint_path=options["checkpoint"],
            )
        except Exception as exc:
            raise CommandError(f"Eigenvector-aware training failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Eigenvector-aware training completed."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
