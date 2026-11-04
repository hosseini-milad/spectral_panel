"""Constrained graph-geodesic spreading; never use plotting coordinates."""
from collections import Counter, deque
from functools import lru_cache
import numpy as np
import networkx as nx

POLICY = 'component_class_geodesic_spread_v1'


def feature_state(features, nodes, selected):
    if features is None:
        return None
    matrix=np.asarray(features,dtype=float)
    if matrix.ndim!=2 or not len(matrix) or not np.isfinite(matrix).all() or max(nodes)>=len(matrix):
        raise ValueError('Spread requires a finite graph-index-aligned feature matrix')
    full=matrix[nodes];scale=full.std(0);active=scale>1e-9
    matrix=(matrix[:,active]-full.mean(0)[active])/scale[active]
    return dict(matrix=matrix,full_mean=matrix[nodes].mean(0),full_std=matrix[nodes].std(0),
        sum=matrix[selected].sum(0),squared=(matrix[selected]**2).sum(0),count=len(selected))


def feature_error(state, total=None, squared=None):
    if state is None:return None
    if not state['matrix'].shape[1]:return 0.
    total=state['sum'] if total is None else total;squared=state['squared'] if squared is None else squared
    mean=total/state['count'];std=np.sqrt(np.maximum(squared/state['count']-mean**2,0))
    return float((np.abs(mean-state['full_mean']).mean()+np.abs(std-state['full_std']).mean())/2)


def coverage(graph, selected):
    """Exact unweighted cover and closest selected pair in O(V+E)."""
    selected=sorted(set(selected),key=int)
    if not selected:return dict(max_hops=None,mean_hops=None,min_rep_hops=None,adjacent_rep_pairs=0)
    queue=deque(selected);distance={n:0 for n in selected};owner={n:n for n in selected}
    while queue:
        u=queue.popleft()
        for v in graph[u]:
            if v not in distance:
                distance[v]=distance[u]+1;owner[v]=owner[u];queue.append(v)
    if len(distance)!=len(graph):raise ValueError('Coverage called on unrepresented disconnected graph')
    chosen=set(selected)
    pair=min((distance[a]+distance[b]+1 for a,b in graph.edges if owner[a]!=owner[b]),default=None)
    return dict(max_hops=max(distance.values()),mean_hops=float(np.mean(list(distance.values()))),min_rep_hops=pair,
        adjacent_rep_pairs=sum(a in chosen and b in chosen for a,b in graph.edges))


def spread_representatives(graph, selected, *, labels=None, priorities=None, novelty=None,
                           features=None, max_swaps=12, diagnostics=None, fixed_nodes=()):
    """Keep every component/class quota; accept only measured improvements.

    Preserve one selected importance anchor per class and, when quota>=3, one
    selected novelty anchor. Candidate centers use farthest-first hop coverage.
    Accept only non-worsening global mean/std feature error and no increase in
    any class or component cover radius or selected-adjacency count. Reduce
    adjacent representatives, then maximize separation and minimize inverse-hop
    pair proximity; mean coverage breaks remaining ties. No all-node distance matrix.
    """
    selected=list(selected);labels=labels or {};priorities=priorities or {};novelty=novelty or {}
    if len(set(selected))!=len(selected) or any(n not in graph for n in selected):
        raise ValueError('Invalid representative identity')
    if max_swaps<0:raise ValueError('max_swaps must be nonnegative')
    fixed=set(fixed_nodes)
    if not fixed.issubset(selected):raise ValueError('Fixed anchors must already be selected')
    nodes=sorted(graph,key=int)
    if not selected:return []
    state=feature_state(features,nodes,selected);initial_feature=feature_error(state)
    rows=[];before_set=set(selected)
    for part in sorted(nx.connected_components(graph),key=lambda p:(-len(p),min(p))):
        members=sorted(part,key=int);sub=graph.subgraph(members);current=[n for n in selected if n in part]
        before=current[:];before_metrics=coverage(sub,current) if current else None
        if len(current)<2 or len(current)==len(members):
            rows.append(dict(component_min_node=int(min(members)),nodes=len(members),representatives=len(current),
                changed=0,reason='fewer_than_two_representatives' if len(current)<2 else 'all_nodes_selected',before=before_metrics,after=before_metrics))
            continue
        index={node:i for i,node in enumerate(members)};width=len(members)
        # Cap cache memory, even when this helper is used by candidate sampling.
        @lru_cache(maxsize=max(2,min(256,2_000_000//width)))
        def hops(node):
            distances=nx.single_source_shortest_path_length(sub,node)
            return np.asarray([distances[n] for n in members],dtype=np.int32)
        component_swaps=0;feature_rejections=0;greedy_accepted=0
        for label in sorted({labels.get(n) for n in current},key=str):
            old=[n for n in current if labels.get(n)==label]
            pool=[n for n in members if labels.get(n)==label]
            quota=len(old)
            if quota<2 or quota==len(pool) or set(old).issubset(fixed):continue
            target=np.asarray([index[n] for n in pool]);others=[n for n in current if labels.get(n)!=label]
            outside=np.minimum.reduce([hops(n) for n in others]) if others else np.full(width,width+1)
            anchor=max(old,key=lambda n:(float(priorities.get(n,0)),-int(n)))
            protected={anchor} | (set(old) & fixed)
            if quota>=3 and novelty:
                protected.add(max(old,key=lambda n:(float(novelty.get(n,0)),-int(n))))
            trial=sorted(protected,key=int);nearest=np.minimum.reduce([hops(n) for n in trial])
            while len(trial)<quota:
                candidate=max((n for n in pool if n not in trial),key=lambda n:(nearest[index[n]],float(priorities.get(n,0)),-int(n)))
                trial.append(candidate);nearest=np.minimum(nearest,hops(candidate))
            def objective(reps,nearest_values=None):
                near=np.minimum.reduce([hops(n) for n in reps]) if nearest_values is None else nearest_values
                ids=np.asarray([index[n] for n in reps])
                pair_matrix=np.stack([hops(n)[ids] for n in reps])
                pairs=pair_matrix[np.triu_indices(len(reps),k=1)]
                pair=int(pairs.min()) if len(pairs) else width+1
                adjacent=int((pairs==1).sum())
                energy=float(np.mean(1./pairs.astype(float)**2)) if len(pairs) else 0.
                return (int(near[target].max()),adjacent,-pair,energy,int(near[target].sum())),near
            old_objective,old_near=objective(old)
            overall_radius=int(np.minimum(old_near,outside).max())
            others_set=set(others)
            cross={n:sum(v in others_set for v in sub[n]) for n in pool}
            adjacent_limit=old_objective[1]+sum(cross[n] for n in old)
            def feature_trial(reps):
                if state is None:return True,None,None
                x=state['matrix'];total=state['sum']-x[old].sum(0)+x[reps].sum(0)
                squares=state['squared']-(x[old]**2).sum(0)+(x[reps]**2).sum(0)
                good=feature_error(state,total,squares)<=feature_error(state)+1e-10
                return good,total,squares
            new_objective,new_near=objective(trial,nearest)
            good,total,squares=feature_trial(trial)
            if (new_objective<old_objective and int(np.minimum(new_near,outside).max())<=overall_radius
                    and new_objective[1]+sum(cross[n] for n in trial)<=adjacent_limit and good):
                current=[n for n in current if labels.get(n)!=label]+trial
                if state is not None:state['sum']=total;state['squared']=squares
                old=trial;old_objective=new_objective;old_near=new_near;greedy_accepted+=1
            elif not good:feature_rejections+=1
            # Bounded exchanges refine greedy centers or repair the original set
            # when a large replacement would perturb the feature distribution.
            if width*quota<=2_000_000:
                for _ in range(max_swaps):
                    candidates=sorted((n for n in pool if n not in old),key=lambda n:(-old_near[index[n]],-float(priorities.get(n,0)),int(n)))[:8]
                    if not candidates:break
                    matrix=np.stack([hops(n) for n in old]);argmin=matrix.argmin(0)
                    first=matrix.min(0);second=np.partition(matrix,1,axis=0)[1]
                    best=None;best_objective=old_objective
                    for candidate in candidates:
                        candidate_hops=hops(candidate)
                        for j,donor in enumerate(old):
                            if donor in protected:continue
                            near=np.minimum(np.where(argmin==j,second,first),candidate_hops)
                            # Avoid expensive tie diagnostics for clearly worse cover.
                            if int(near[target].max())>best_objective[0] or int(np.minimum(near,outside).max())>overall_radius:continue
                            proposal=old[:];proposal[j]=candidate
                            obj,_=objective(proposal,near)
                            if obj>=best_objective or obj[1]+sum(cross[n] for n in proposal)>adjacent_limit:continue
                            good,total,squares=feature_trial(proposal)
                            if not good:feature_rejections+=1;continue
                            best=(proposal,near,total,squares);best_objective=obj
                    if best is None:break
                    proposal,old_near,total,squares=best
                    current=[n for n in current if labels.get(n)!=label]+proposal
                    if state is not None:state['sum']=total;state['squared']=squares
                    old=proposal;old_objective=best_objective;component_swaps+=1
        after_metrics=coverage(sub,current)
        if Counter(labels.get(n) for n in before)!=Counter(labels.get(n) for n in current) or len(set(current))!=len(before):
            raise AssertionError('Spread changed component/class quotas')
        if after_metrics['adjacent_rep_pairs']>before_metrics['adjacent_rep_pairs']:
            raise AssertionError('Spread increased adjacent representatives')
        if after_metrics['max_hops']>before_metrics['max_hops']:
            raise AssertionError('Spread worsened graph cover radius')
        slots=[i for i,n in enumerate(selected) if n in part]
        for slot,node in zip(slots,current):selected[slot]=node
        class_metrics=[]
        for label in sorted({labels.get(n) for n in before},key=str):
            a=[n for n in before if labels.get(n)==label];b=[n for n in current if labels.get(n)==label]
            targets=[n for n in members if labels.get(n)==label]
            da=nx.multi_source_dijkstra_path_length(sub,a,weight=None)
            db=nx.multi_source_dijkstra_path_length(sub,b,weight=None)
            if max(db[n] for n in targets)>max(da[n] for n in targets):
                raise AssertionError('Spread worsened class cover radius')
            class_metrics.append(dict(label=label,count_before=len(a),count_after=len(b),
                max_hops_before=max(da[n] for n in targets),max_hops_after=max(db[n] for n in targets),
                mean_hops_before=float(np.mean([da[n] for n in targets])),mean_hops_after=float(np.mean([db[n] for n in targets]))))
        rows.append(dict(component_min_node=int(min(members)),nodes=len(members),representatives=len(current),
            class_coverage=class_metrics,
            changed=len(set(current)-set(before)),reason='measured_constrained_spread',greedy_updates=greedy_accepted,
            swaps=component_swaps,feature_rejections=feature_rejections,before=before_metrics,after=after_metrics))
    final_feature=feature_error(state)
    if initial_feature is not None and final_feature>initial_feature+1e-8:raise AssertionError('Feature distribution guard failed')
    if diagnostics is not None:
        diagnostics.update(policy=POLICY,feature_metric='mean_absolute_standardized_mean_and_std_error_nonconstant_columns',
            feature_error_before=initial_feature,feature_error_after=final_feature,
            selected_before=sorted(before_set,key=int),selected_after=selected,changed=len(set(selected)-before_set),components=rows,
            component_class_quotas_preserved=True,plot_coordinates_used=False,
            fixed_nodes_preserved=fixed.issubset(selected),fixed_selected_nodes=sorted(fixed,key=int))
    return selected
