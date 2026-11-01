import json
from collections import Counter
from pathlib import Path
import statistics

import networkx as nx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_component import GraphComponent
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.services.pooling.community import detect_communities
from ingestion.utils.document_paths import document_directory


def _mean(values):
    return float(statistics.mean(values)) if values else None


def _distribution(values):
    if not values:
        return {}
    ordered = sorted(int(value) for value in values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": _mean(ordered),
        "median": float(statistics.median(ordered)),
        "q25": float(statistics.quantiles(ordered, n=4, method="inclusive")[0]) if len(ordered) > 1 else float(ordered[0]),
        "q75": float(statistics.quantiles(ordered, n=4, method="inclusive")[2]) if len(ordered) > 1 else float(ordered[0]),
    }


def _bins(values):
    ranges = [
        ("0", 0, 0),
        ("1", 1, 1),
        ("2-4", 2, 4),
        ("5-10", 5, 10),
        ("11-20", 11, 20),
        ("21-50", 21, 50),
        ("51-100", 51, 100),
        ("101+", 101, float("inf")),
    ]
    result = {}
    for label, low, high in ranges:
        result[label] = sum(low <= int(value) <= high for value in values)
    return result


class Command(BaseCommand):
    help = "Read-only structural audit of layer-1 components and representative allocation."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-file", required=True)
        parser.add_argument("--output-dir", default=None)

    def handle(self, *args, **options):
        source_file = options["source_file"]
        graph = GraphMetadata.objects(source_file=source_file).first()
        if graph is None:
            raise CommandError(f"GraphMetadata not found: {source_file}")

        components = list(
            GraphComponent.objects(source_file=source_file).as_pymongo()
        )
        representatives = list(
            GraphRepresentative.objects(source_file=source_file).as_pymongo()
        )
        if not components:
            raise CommandError(f"No GraphComponent documents for {source_file}")

        component_sizes = [int(doc.get("node_count", 0) or 0) for doc in components]
        rep_counts = [int(doc.get("representative_count", 0) or 0) for doc in components]
        ranked_components = sorted(
            zip(component_sizes, rep_counts),
            key=lambda item: (-item[0], -item[1]),
        )
        sorted_sizes = [item[0] for item in ranked_components]
        sorted_rep_counts = [item[1] for item in ranked_components]

        G = nx.Graph()
        node_count = len(graph.node_ids or [])
        G.add_nodes_from(range(node_count))
        for edge in graph.edges or []:
            G.add_edge(int(edge["source"]), int(edge["target"]),
                       weight=float(edge.get("weight", 1.0)))
        connected_count = nx.number_connected_components(G) if node_count else 0
        louvain_count = len(set(detect_communities(G).values())) if node_count else 0

        covered_indices = [
            int(index)
            for component in components
            for index in (component.get("node_indices") or [])
        ]
        unique_covered = set(covered_indices)
        components_with_reps = sum(count > 0 for count in rep_counts)
        components_without_reps = len(components) - components_with_reps

        profile_fields = set()
        profiled_components = 0
        for component in components:
            profile = component.get("node_feature_profile") or {}
            if profile:
                profiled_components += 1
                profile_fields.update(profile.keys())

        rank_groups = {}
        for start in range(0, len(sorted_sizes), 25):
            group = sorted_sizes[start:start + 25]
            rank_groups[f"rank_{start + 1}_{start + len(group)}"] = {
                "component_count": len(group),
                "mean_node_count": _mean(group),
                "min_node_count": min(group) if group else None,
                "max_node_count": max(group) if group else None,
                "mean_representatives": _mean(sorted_rep_counts[start:start + len(group)]),
            }

        size_bins = _bins(component_sizes)
        rep_bins = _bins(rep_counts)

        results = {
            "source_file": source_file,
            "graph": {
                "nodes": node_count,
                "edges": G.number_of_edges(),
                "connected_components": connected_count,
                "louvain_communities": louvain_count,
            },
            "stored_components": {
                "count": len(components),
                "size_distribution": _distribution(component_sizes),
                "size_bins": size_bins,
                "rank_groups_of_25": rank_groups,
                "singleton_components": sum(size == 1 for size in component_sizes),
            },
            "representatives": {
                "count": len(representatives),
                "ratio_to_nodes": len(representatives) / node_count if node_count else None,
                "components_with_representatives": components_with_reps,
                "components_without_representatives": components_without_reps,
                "component_representation_fraction": (
                    components_with_reps / len(components) if components else None
                ),
                "representative_count_distribution": _distribution(rep_counts),
                "representative_count_bins": rep_bins,
                "total_representatives_from_component_documents": sum(rep_counts),
            },
            "integrity": {
                "covered_node_indices": len(unique_covered),
                "expected_node_indices": node_count,
                "duplicate_node_index_entries": len(covered_indices) - len(unique_covered),
                "missing_node_indices": max(0, node_count - len(unique_covered)),
                "profiled_components": profiled_components,
                "components_without_node_feature_profile": len(components) - profiled_components,
                "profile_feature_fields": sorted(profile_fields),
            },
            "notes": [
                "Connected components and Louvain communities are distinct graph concepts and are reported separately.",
                "This command is read-only; it does not modify graph, component, or representative collections.",
                "Rank groups are sorted by component node_count descending.",
            ],
        }

        output_dir = Path(options["output_dir"]) if options["output_dir"] else (
            document_directory('component', source_file, day=graph.source_day) / 'layer1_component_structure'
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{source_file}_layer1_structure.json"
        txt_path = output_dir / f"{source_file}_layer1_structure.txt"
        json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

        lines = [
            f"LAYER-1 COMPONENT STRUCTURE AUDIT",
            f"source_file: {source_file}",
            "",
            "[GRAPH]",
            f"nodes: {node_count}",
            f"edges: {G.number_of_edges()}",
            f"connected_components: {connected_count}",
            f"louvain_communities: {louvain_count}",
            "",
            "[COMPONENT SIZE DISTRIBUTION]",
            f"components: {len(components)}",
            f"size_stats: {results['stored_components']['size_distribution']}",
            f"size_bins: {size_bins}",
            f"singletons: {results['stored_components']['singleton_components']}",
            "",
            "[RANK GROUPS - 25 COMPONENTS EACH]",
        ]
        for key, value in rank_groups.items():
            lines.append(f"{key}: {value}")
        lines.extend([
            "",
            "[REPRESENTATIVE ALLOCATION]",
            f"representatives: {len(representatives)}",
            f"components_with_reps: {components_with_reps}",
            f"components_without_reps: {components_without_reps}",
            f"component_representation_fraction: {results['representatives']['component_representation_fraction']}",
            f"representative_count_distribution: {results['representatives']['representative_count_distribution']}",
            f"representative_count_bins: {rep_bins}",
            f"sum_representative_count_in_components: {sum(rep_counts)}",
            "",
            "[INTEGRITY / PROFILE]",
            f"covered_node_indices: {len(unique_covered)}/{node_count}",
            f"duplicate_node_index_entries: {len(covered_indices) - len(unique_covered)}",
            f"missing_node_indices: {max(0, node_count - len(unique_covered))}",
            f"profiled_components: {profiled_components}/{len(components)}",
            f"profile_feature_fields: {sorted(profile_fields)}",
            "",
            "[NOTES]",
            *[f"- {note}" for note in results["notes"]],
        ])
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"[L1 AUDIT] JSON: {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"[L1 AUDIT] TXT:  {txt_path}"))
        self.stdout.write(json.dumps(results, indent=2, ensure_ascii=False))
