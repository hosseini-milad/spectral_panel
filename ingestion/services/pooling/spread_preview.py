"""Read-only preview on a pinned stored representative set; same plot layout."""
import uuid
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt

from ingestion.utils.document_paths import document_directory
from ingestion.services.graph.components import load_node_documents
from .spread import spread_representatives
from .visualization import _pack_component_positions


def _snapshot(db, source):
    graphs=list(db.graph_metadata.find({'source_file':source}))
    if len(graphs)!=1:raise ValueError('Require exactly one stored graph for this chunk')
    reps=sorted(db.graph_representatives.find({'source_file':source}),key=lambda r:r['node_index'])
    if not reps:raise ValueError('No existing representatives to preview')
    return graphs[0],reps


def preview_spread(db,source):
    from spectral_learning.services.spectral_inputs import fingerprint
    from spectral_learning.services.spectral_reports import dump_json,save
    from .evaluation import evaluate_representatives
    from types import SimpleNamespace
    graph,reps=_snapshot(db,source);snapshot=fingerprint(dict(graph=graph,reps=reps))
    ids=graph['node_ids'];n=len(ids);labels=graph.get('node_labels') or []
    if len(labels)!=n or any(v not in (0,1) for v in labels):
        docs=load_node_documents(db,ids,'sampled_security_data')
        if len(docs)!=n:raise ValueError('Missing candidate labels')
        labels=[docs[value].get('label') for value in ids]
    if any(v not in (0,1) for v in labels):raise ValueError('Binary labels required')
    G=nx.Graph();G.add_nodes_from(range(n))
    for edge in graph['edges']:
        a,b=int(edge['source']),int(edge['target'])
        if not(0<=a<n and 0<=b<n):raise ValueError('Invalid edge index')
        G.add_edge(a,b,weight=float(edge.get('weight',1)))
    before=[r['node_index'] for r in reps]
    if any(str(r['original_id'])!=ids[r['node_index']] for r in reps):raise ValueError('Representative/node mapping differs')
    priority={node:G.degree(node) for node in G}
    # Existing attention/centrality preserves the stored high-priority anchor.
    for row in reps:priority[row['node_index']]=float(row.get('attention',row.get('centrality',G.degree(row['node_index']))) or 0)
    diagnostics={}
    after=spread_representatives(G,before,labels=dict(enumerate(labels)),priorities=priority,
        features=graph.get('features') or None,diagnostics=diagnostics,
        fixed_nodes=[i for i in before if labels[i]==1])
    folder=document_directory('nominal',source,day=graph.get('source_day'))/'spread_preview'/'runs'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    dump_json(folder/'run_status.json',dict(status='building'))
    try:
        positions=_pack_component_positions(G,sorted(nx.connected_components(G),key=lambda p:(-len(p),min(p))))
        fig,axes=plt.subplots(1,2,figsize=(20,9))
        for ax,chosen,title in zip(axes,[before,after],['Stored representatives','Proposed geodesic spread']):
            nx.draw_networkx_edges(G,positions,ax=ax,width=.25,alpha=.15)
            nx.draw_networkx_nodes(G,positions,ax=ax,node_size=3,node_color=['#f28e2b' if labels[i] else '#2583bd' for i in G])
            nx.draw_networkx_nodes(G,positions,ax=ax,nodelist=chosen,node_size=35,
                node_color=['#f28e2b' if labels[i] else '#2583bd' for i in chosen],
                edgecolors=['red' if labels[i] else 'green' for i in chosen],linewidths=1.3)
            ax.set_title(f'{title}: {len(chosen)} reps');ax.axis('off')
        from matplotlib.lines import Line2D
        fig.legend(handles=[
            Line2D([],[],marker='o',linestyle='',color='#2583bd',label='Normal node'),
            Line2D([],[],marker='o',linestyle='',color='#f28e2b',label='Attack-labelled node'),
            Line2D([],[],marker='o',linestyle='',markerfacecolor='#2583bd',markeredgecolor='green',label='Normal representative'),
            Line2D([],[],marker='o',linestyle='',markerfacecolor='#f28e2b',markeredgecolor='red',label='Attack representative')],loc='lower center',ncol=4)
        fig.suptitle('Identical graph and layout; selection only changes. No database writes.')
        save(fig,folder/'representative_spread_comparison')
        dump_json(folder/'representative_spread.json',diagnostics)
        matrix=np.asarray(graph.get('features') or [],dtype=float)
        if matrix.ndim==2 and len(matrix)==n and np.isfinite(matrix).all():
            import csv
            from scipy.stats import ks_2samp,wasserstein_distance
            names=(graph.get('graph_parameters') or {}).get('feature_fields') or []
            with (folder/'feature_distribution.csv').open('w',newline='',encoding='utf-8-sig') as output:
                writer=csv.DictWriter(output,fieldnames=['feature','full_mean','full_std','before_mean','after_mean',
                    'before_std','after_std','before_ks_distance','after_ks_distance','before_wasserstein','after_wasserstein'])
                writer.writeheader()
                for col in range(matrix.shape[1]):
                    full=matrix[:,col];old=full[before];new=full[after]
                    writer.writerow(dict(feature=names[col] if col<len(names) else f'feature_{col}',full_mean=float(full.mean()),
                        full_std=float(full.std()),before_mean=float(old.mean()),after_mean=float(new.mean()),
                        before_std=float(old.std()),after_std=float(new.std()),
                        before_ks_distance=float(ks_2samp(full,old).statistic),after_ks_distance=float(ks_2samp(full,new).statistic),
                        before_wasserstein=float(wasserstein_distance(full,old)),after_wasserstein=float(wasserstein_distance(full,new))))
        dump_json(folder/'selection_plan.json',dict(source_file=source,snapshot=snapshot,before=before,after=after,
            node_ids_before=[ids[i] for i in before],node_ids_after=[ids[i] for i in after]))
        # Run the established feature/topology evaluation on both exact sets.
        view=SimpleNamespace(node_ids=ids,node_labels=labels,edges=graph['edges'],features=graph.get('features') or [])
        for name,chosen in [('before',before),('after',after)]:
            metrics=evaluate_representatives(view,[dict(node_index=i,label=labels[i]) for i in chosen],with_eigen=False,report=lambda *args,**kwargs:None)
            dump_json(folder/f'{name}_evaluation.json',metrics)
        current_graph,current_reps=_snapshot(db,source)
        if fingerprint(dict(graph=current_graph,reps=current_reps))!=snapshot:raise ValueError('Graph/representatives changed during preview')
        dump_json(folder/'run_status.json',dict(status='complete',database_written=False,source_unchanged_verified=True))
    except BaseException as exc:
        dump_json(folder/'run_status.json',dict(status='failed',error=str(exc)));raise
    return str(folder)
