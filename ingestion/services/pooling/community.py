import networkx as nx
import community.community_louvain as community_louvain



def build_weighted_graph(edges):

    """
    ساخت گراف وزن دار از خروجی similarity graph

    edges:
    [
        {
            source:0,
            target:512,
            weight:0.96
        }
    ]

    """

    G = nx.Graph()


    for edge in edges:

        try:

            source = int(
                edge["source"]
            )

            target = int(
                edge["target"]
            )

            weight = float(
                edge.get(
                    "weight",
                    1.0
                )
            )


            G.add_edge(
                source,
                target,
                weight=weight
            )


        except Exception:

            continue



    return G




def detect_communities(G):

    """
    Community Detection

    خروجی:

    {
        node_id : community_id
    }

    """


    if G.number_of_nodes()==0:

        return {}



    partition = community_louvain.best_partition(
        G,
        weight="weight",
        random_state=42
    )


    return partition





def get_community_statistics(
    G,
    partition
):

    """
    استخراج اطلاعات هر community

    برای تحلیل و ذخیره Mongo

    """

    communities={}



    for node,community_id in partition.items():


        if community_id not in communities:

            communities[community_id]={

                "nodes":[],
                "size":0,
                "internal_edges":0

            }


        communities[community_id]["nodes"].append(
            node
        )



    for cid,data in communities.items():


        subgraph = G.subgraph(
            data["nodes"]
        )


        data["size"] = (
            subgraph.number_of_nodes()
        )


        data["internal_edges"] = (
            subgraph.number_of_edges()
        )


        try:

            data["density"] = (
                nx.density(
                    subgraph
                )
            )

        except:

            data["density"]=0



    return communities





def assign_node_communities(
    nodes,
    partition
):

    """
    اتصال community به nodeها

    برای استفاده در pooling

    """

    result={}


    for node in nodes:

        result[node]=partition.get(
            node,
            -1
        )


    return result