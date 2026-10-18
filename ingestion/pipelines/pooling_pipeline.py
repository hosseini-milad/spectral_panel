import time
import sys
from ..services.pooling.centrality import (
    build_graph,
    compute_centralities
)

from ..services.pooling.scoring import (
    compute_score
)

from ..services.pooling.representative import (
    select_representatives
)

from ..models.graph_representative import (
    GraphRepresentative
)
from ..models.normalized_data import NormalizedSecurityData

from ..services.pooling.visualization import (
    save_representative_graph
)

from ..services.pooling.community import (
    detect_communities,
    get_community_statistics
)

import os
from django.conf import settings



def run_pooling(
    source_file,
    edges,
    features,
    docs,
    ratio=0.05,
    labels=None,
    anomaly_scores=None,
    attack_ratio=None,
    create_visualization=True,
):
    started_at = time.perf_counter()

    def log_progress(message):
        elapsed = time.perf_counter() - started_at
        print(
            f"[POOLING +{elapsed:8.1f}s] {message}",
            flush=True,
        )
    # ==================================================
    # 1. ساخت Graph
    # ==================================================
    log_progress("STEP 1/5: Building graph...")

    G = build_graph(
        edges
    )
    # Keep sampled nodes with no mutual-kNN edge eligible for representation.
    G.add_nodes_from(range(len(docs)))

    log_progress(
        f"Graph ready: nodes={G.number_of_nodes()}, "
        f"edges={G.number_of_edges()}"
    )

    log_progress("Detecting communities...")

    print(
        "Graph:",
        G.number_of_nodes(),
        G.number_of_edges()
    )

    partition = detect_communities(
        G
    )


    community_stats = get_community_statistics(
        G,
        partition
    )


    print(
        "Communities:",
        len(community_stats)
    )


    # ==================================================
    # 2. محاسبه چند نوع Centrality
    # ==================================================
    log_progress("STEP 2/5: Computing centralities...")

    centrality_started = time.perf_counter()

    centralities = compute_centralities(G)

    log_progress(
        "Centralities completed in "
        f"{time.perf_counter() - centrality_started:.1f}s"
    )


    # ==================================================
    # 3. ساخت امتیاز ترکیبی
    # ==================================================

    log_progress("STEP 3/5: Computing node scores...")
    scores = compute_score(
        centralities,
        anomaly_scores
    )
    log_progress(f"Scores completed: {len(scores)} nodes")


    # ==================================================
    # 4. انتخاب نماینده‌ها
    #
    # خروجی:
    #
    # [
    #   549,
    #   812,
    #   ...
    # ]
    #
    # node index در Graph
    #
    # ==================================================

    k = max(1, int(len(docs) * ratio + 0.5))

    node_mapping = {}

    if labels is None:
        labels = {
            index: int(doc.get("label", 0))
            for index, doc in enumerate(docs)
        }

    if attack_ratio is None:
        normalized_labels = [
            doc.get("label")
            for doc in NormalizedSecurityData.objects(source_file=source_file).as_pymongo()
            if doc.get("label") in (0, 1)
        ]
        attack_ratio = (
            sum(label == 1 for label in normalized_labels) / len(normalized_labels)
            if normalized_labels else 0.0
        )

    for i,doc in enumerate(docs):
        node_mapping[i] = {
            "original_id": str(doc["_id"]),
            "label": doc.get(
                "label",0
            )
        }

        log_progress(
        f"STEP 4/5: Selecting representatives, target={k}..."
    )

    selection_started = time.perf_counter()
    selected_nodes = select_representatives(
        score=scores,
        G=G,
        k=k,
        labels=labels,
        attack_ratio=attack_ratio,
        eigenvector_scores=centralities.get("eigenvector", {}),
    )
    log_progress(
        f"Selection completed: {len(selected_nodes)} representatives "
        f"in {time.perf_counter() - selection_started:.1f}s"
    )


    print(
        "Selected representatives:",
        len(selected_nodes)
    )


    # ==================================================
    # 5. حذف نتایج قبلی
    # ==================================================

    GraphRepresentative.objects(
        source_file=source_file
    ).delete()



    reps = []


    # ==================================================
    # 6. ذخیره Representative ها
    # ==================================================
    log_progress(
        f"STEP 5/5: Saving {len(selected_nodes)} representatives..."
    )

    total_to_save = len(selected_nodes)
    for node_index in selected_nodes:


        # جلوگیری از خطای index
        node_index = int(node_index)


        if node_index >= len(docs):

            print(
                "Invalid node index:",
                node_index
            )

            continue



        original = node_mapping.get(
            node_index
        )
        if not original:
            print(
                "Missing mapping:",
                node_index
            )
            continue

        item = {

            "node_index": node_index,


            "original_id": str(
                original["original_id"]
            ),

            "label": original["label"],

            "score": float(
                scores.get(
                    node_index,
                    0
                )
            ),


            "centrality": {

                "eigenvector": float(
                    centralities["eigenvector"].get(
                        node_index,
                        0
                    )
                ),


                "degree": float(
                    centralities["degree"].get(
                        node_index,
                        0
                    )
                ),


                "betweenness": float(
                    centralities.get("betweenness", {}).get(node_index, 0.0)
                )
            }
        }



        # Mongo Document

        GraphRepresentative(
            source_file=source_file,

            original_id=item["original_id"],

            node_index=node_index,
    
            label=item["label"],

            attention=item["score"],

            centrality=item["centrality"]["eigenvector"]

        ).save()



        reps.append(
            item
        )
        saved = len(reps)

        if saved % 100 == 0 or saved == total_to_save:
            log_progress(
                f"Saved {saved}/{total_to_save} representatives "
                f"({100 * saved / max(1, total_to_save):.1f}%)"
            )


    # ==================================================
    # 7. رسم گراف Representative
    #
    # فقط یک بار بعد از ذخیره همه
    #
    # ==================================================


    if create_visualization:
        image_path = os.path.join(
            settings.BASE_DIR,
            "files",
            "nominal",
            f"{source_file}_representatives.png",
        )
        save_representative_graph(edges, reps, image_path)
        print("Representative graph:", image_path)

    log_progress(
        f"ALL STEPS COMPLETED in "
        f"{time.perf_counter() - started_at:.1f}s"
    )

    return reps
