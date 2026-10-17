from django.core.management.base import BaseCommand, CommandError

from spectral_learning.services.similarity_graph_autoencoder import (
    train_similarity_graph_autoencoder,
)


class Command(BaseCommand):
    help = "Train and score a self-supervised eigenvector-aware autoencoder on hourly similarity graphs."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--epochs", type=int, default=40)
        parser.add_argument("--hidden-dim", type=int, default=64)
        parser.add_argument("--embedding-dim", type=int, default=32)
        parser.add_argument("--learning-rate", type=float, default=0.001)
        parser.add_argument("--mask-rate", type=float, default=0.15)
        parser.add_argument("--threshold-quantile", type=float, default=0.99)
        parser.add_argument("--seed", type=int, default=17)
        parser.add_argument("--checkpoint", type=str, default=None)

    def handle(self, *args, **options):
        if options["epochs"] < 1:
            raise CommandError("--epochs must be positive")
        if not 0.5 <= options["threshold_quantile"] < 1:
            raise CommandError("--threshold-quantile must be in [0.5, 1)")
        try:
            result = train_similarity_graph_autoencoder(
                epochs=options["epochs"], hidden_dim=options["hidden_dim"],
                embedding_dim=options["embedding_dim"], learning_rate=options["learning_rate"],
                mask_rate=options["mask_rate"], threshold_quantile=options["threshold_quantile"],
                seed=options["seed"], checkpoint_path=options["checkpoint"],
            )
        except Exception as exc:
            raise CommandError(f"Similarity-graph autoencoder failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS("Similarity-graph autoencoder training and scoring completed."))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
