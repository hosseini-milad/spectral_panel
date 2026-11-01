from django.core.management.base import BaseCommand, CommandError

from ingestion.models.graph_metadata import GraphMetadata
from ingestion.models.graph_representative import GraphRepresentative
from ingestion.models.graph_component import GraphComponent
from ingestion.services.graph.components import build_component_graph, ordered_components


class Command(BaseCommand):
    help = "Read-only integrity audit for layer-1 component and representative entities."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--source-file", required=True)

    def handle(self, *args, **opts):
        source_file = opts["source_file"]
        graph = GraphMetadata.objects(source_file=source_file).first()
        if graph is None:
            raise CommandError(f"GraphMetadata not found: {source_file}")

        components = list(GraphComponent.objects(source_file=source_file).as_pymongo())
        reps = list(GraphRepresentative.objects(source_file=source_file).as_pymongo())
        graph_node_ids = [str(value) for value in (graph.node_ids or [])]
        n = len(graph_node_ids)

        self.stdout.write(
            f"[COMPONENT AUDIT] graph_nodes={n}; "
            f"components={len(components)}; representatives={len(reps)}"
        )

        issues = []
        if graph.component_status and graph.component_status != 'complete':
            issues.append(f'Component storage is not complete: {graph.component_status}')
        try:
            expected = {frozenset(nodes) for nodes in ordered_components(build_component_graph(graph_node_ids, graph.edges or []))}
            actual = {frozenset(row.get('node_indices') or []) for row in components}
            if actual != expected or len(actual) != len(components):
                issues.append('Stored components differ from the actual connected-component partition.')
        except ValueError as exc:
            issues.append(str(exc))
        component_ids = set()
        component_indexes = set()
        covered_indices = []
        covered_ids = []
        reps_by_id = {str(rep["_id"]): rep for rep in reps}
        rep_counts = {}
        linked_rep_ids = []

        for component in components:
            cid = str(component.get("component_id", ""))
            cindex = component.get("component_index")
            node_indices = component.get("node_indices") or []
            node_ids = [str(value) for value in (component.get("node_ids") or [])]
            representative_ids = [
                str(value) for value in (component.get("representative_ids") or [])
            ]
            representative_original_ids = [
                str(value)
                for value in (component.get("representative_original_ids") or [])
            ]

            if not cid:
                issues.append(f"Component {component.get('_id')} has empty component_id.")
            if cid in component_ids:
                issues.append(f"Duplicate component_id: {cid}")
            component_ids.add(cid)

            if cindex in component_indexes:
                issues.append(f"Duplicate component_index: {cindex}")
            component_indexes.add(cindex)

            if component.get("node_count") != len(node_ids):
                issues.append(f"{cid}: node_count does not match node_ids length.")
            if len(node_indices) != len(node_ids):
                issues.append(f"{cid}: node_indices/node_ids lengths differ.")

            covered_indices.extend(node_indices)
            covered_ids.extend(node_ids)

            for idx, node_id in zip(node_indices, node_ids):
                if not isinstance(idx, int) or not 0 <= idx < n:
                    issues.append(f"{cid}: invalid node_index {idx}.")
                elif graph_node_ids[idx] != node_id:
                    issues.append(f"{cid}: node index/id mismatch at index {idx}.")

            if component.get("representative_count") != len(representative_ids):
                issues.append(f"{cid}: representative_count does not match representative_ids.")
            if len(representative_ids) != len(representative_original_ids):
                issues.append(f"{cid}: representative ID/original ID lengths differ.")

            rep_counts[cid] = 0
            for rep_id, original_id in zip(representative_ids, representative_original_ids):
                linked_rep_ids.append(rep_id)
                rep = reps_by_id.get(rep_id)
                if rep is None:
                    issues.append(f"{cid}: referenced representative {rep_id} is missing.")
                    continue
                rep_counts[cid] += 1
                if str(rep.get("component_id")) != cid:
                    issues.append(f"{cid}: representative {rep_id} has wrong component_id.")
                if str(rep.get("original_id")) != original_id:
                    issues.append(f"{cid}: representative {rep_id} original_id mismatch.")
                if original_id not in node_ids or rep.get('node_index') not in node_indices:
                    issues.append(f'{cid}: representative {rep_id} is not a member of its component.')

        if len(covered_indices) != n:
            issues.append(f"Covered node-index count {len(covered_indices)} != graph nodes {n}.")
        if len(set(covered_indices)) != len(covered_indices):
            issues.append("A node index occurs in more than one component.")
        if set(covered_indices) != set(range(n)):
            issues.append("Component node indices do not cover exactly range(graph_nodes).")
        if len(set(covered_ids)) != len(covered_ids):
            issues.append("A node ID occurs in more than one component.")
        if set(covered_ids) != set(graph_node_ids):
            issues.append("Union of component node_ids differs from graph.node_ids.")

        orphan_reps = [
            str(rep["_id"])
            for rep in reps
            if str(rep.get("component_id")) not in component_ids
        ]
        if orphan_reps:
            issues.append(f"{len(orphan_reps)} representatives reference missing components.")
        if set(linked_rep_ids) != set(reps_by_id) or len(linked_rep_ids) != len(set(linked_rep_ids)):
            issues.append('Component representative lists do not reference every representative exactly once.')

        self.stdout.write(
            f"[COMPONENT AUDIT] covered_nodes={len(set(covered_indices))}/{n}; "
            f"linked_representatives={sum(rep_counts.values())}"
        )

        if issues:
            for issue in issues:
                self.stderr.write(self.style.ERROR(f"[FAIL] {issue}"))
            raise CommandError(f"Component integrity audit failed: {len(issues)} issue(s).")

        self.stdout.write(self.style.SUCCESS(
            "[COMPONENT AUDIT] PASS: node partition and representative references are consistent."
        ))
