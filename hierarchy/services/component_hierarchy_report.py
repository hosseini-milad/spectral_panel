"""Standalone lineage explorer, complete paginated diagrams and numerical audits."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

from ingestion.utils.document_paths import document_directory


def save_figure(fig, base):
    try:
        for extension in ('png', 'svg'):
            fig.savefig(str(base) + '.' + extension, dpi=150, bbox_inches='tight')
    finally:
        plt.close(fig)


def write_lineage_pages(folder, nodes, metas):
    """Every child appears exactly once; a large meta may span multiple pages."""
    pages, current = [], []
    for meta in metas:
        for index in meta['node_indices']:
            current.append((index, meta['meta_index']))
            if len(current) == 80:
                pages.append(current); current = []
    if current:
        pages.append(current)
    colors = plt.get_cmap('tab20')
    chunk_colors = lambda index: colors((2 * (index % 10) + index // 10 % 2) % 20)
    manifest = []
    for number, page in enumerate(pages, 1):
        page.sort(key=lambda pair: (nodes[pair[0]]['chunk_index'], nodes[pair[0]]['component_index']))
        fig, ax = plt.subplots(figsize=(15, max(6, len(page) * .31)))
        positions = {index: len(page) - rank for rank, (index, _) in enumerate(page)}
        chunks = sorted({nodes[index]['chunk_index'] for index, _ in page})
        visible_metas = sorted({meta for _, meta in page})
        meta_y = dict(zip(visible_metas, np.linspace(len(page), 1, len(visible_metas))))
        for chunk in chunks:
            members = [index for index, _ in page if nodes[index]['chunk_index'] == chunk]
            y = np.mean([positions[index] for index in members])
            ax.scatter([0], [y], s=170, color=chunk_colors(chunk % 20), zorder=3)
            ax.text(-.08, y, f'Chunk {chunk}\n{len(members)} components on this page', ha='right', va='center', fontsize=8)
            for index in members:
                ax.plot([0, 1], [y, positions[index]], color=chunk_colors(chunk % 20), alpha=.35, lw=.8)
        for index, meta_index in page:
            node = nodes[index]; y = positions[index]
            ax.scatter([1], [y], s=32, color=chunk_colors(node['chunk_index'] % 20), zorder=3)
            ax.text(1.04, y, f"ch{node['chunk_index']}:C{node['component_index']}  …{node['component_id'][-10:]}  n={node['node_count']}",
                    va='center', fontsize=7)
            ax.plot([1, 2.7], [y, meta_y[meta_index]], color=chunk_colors(meta_index % 20), alpha=.35, lw=.8, zorder=0)
        for index in visible_metas:
            meta = metas[index]; y = meta_y[index]
            shown = sum(value == index for _, value in page)
            ax.scatter([2.7], [y], s=160, marker='s', color=chunk_colors(index % 20), zorder=3)
            ax.text(2.78, y, f"M{index}  {meta['meta_component_id'][:10]}\nchildren={meta['component_count']}, shown={shown}\n"
                    f"candidate nodes={meta['member_node_count']}", fontsize=8, va='center')
        ax.set_xlim(-.7, 3.65); ax.set_ylim(-1, len(page) + 3); ax.axis('off')
        ax.set_title(f'Lineage page {number}/{len(pages)} — Chunk → Layer-1 component → Meta-component\n'
                     'n = candidate nodes in the child component; line crossings do not mean graph edges', pad=20)
        base = folder / f'lineage_page_{number:03d}'
        save_figure(fig, base)
        manifest.append({'page': number, 'node_indices': [index for index, _ in page],
                         'png': base.name + '.png', 'svg': base.name + '.svg'})
    return manifest


def write_dashboard(folder, evaluation, nodes, graph):
    metas = evaluation['meta_components']; chunks = sorted({node['chunk_index'] for node in nodes})
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    meta_for = {index: meta['meta_index'] for meta in metas for index in meta['node_indices']}
    matrix = np.array([[sum(node['chunk_index'] == chunk and meta_for[node['node_index']] == meta['meta_index'] for node in nodes)
                        for meta in metas] for chunk in chunks])
    # Full matrix is retained as CSV and in the explorer; bound static label clutter.
    shown = matrix[:, :30]
    if matrix.shape[1] > 30:
        shown = np.column_stack([shown, matrix[:, 30:].sum(axis=1)])
    image = axes[0, 0].imshow(shown, aspect='auto', cmap='Blues', interpolation='nearest')
    axes[0, 0].set_yticks(range(len(chunks)), [f'chunk {value}' for value in chunks])
    labels = [f'M{i}' for i in range(min(30, len(metas)))] + (['Other metas'] if len(metas) > 30 else [])
    axes[0, 0].set_xticks(range(len(labels)), labels, rotation=90, fontsize=7)
    axes[0, 0].set_title('Chunk → Meta-component membership (number of child components)')
    fig.colorbar(image, ax=axes[0, 0])
    axes[0, 1].bar(range(len(metas)), [meta['component_count'] for meta in metas])
    axes[0, 1].set(xlabel='Meta-component index', ylabel='Child components', title='All meta-component sizes')
    axes[0, 1].set_yscale('log')
    hist = evaluation['diagnostics']
    bins = np.array(hist['histogram_bins'])
    axes[1, 0].bar(bins[:-1], hist['histogram_counts'], width=.01, align='edge')
    axes[1, 0].axvline(evaluation['parameters']['threshold'], color='red', label='Threshold')
    axes[1, 0].set(xlabel='Component similarity', ylabel='Comparable pairs', title='All-pair similarity distribution')
    axes[1, 0].legend()
    ax = axes[1, 1]; ax.axis('off')
    lines = [f"Chunks: {evaluation['chunk_count']}", f"Input components: {len(nodes)} (including unrepresented)",
             f"Candidate nodes traced: {evaluation['candidate_node_count']}",
             f"Edges: {graph.number_of_edges()} | max degree: {evaluation['max_degree']}",
             f"Meta-components: {len(metas)} | singletons: {evaluation['singleton_meta_components']}",
             f"Cross-chunk meta-components: {evaluation['cross_chunk_meta_components']}",
             f"Chaining warnings: {sum(meta['chaining_warning'] for meta in metas)}",
             f"Components with categorical data: {evaluation['components_with_categorical_data']}/{len(nodes)}",
             'Membership coverage: all input components assigned exactly once',
             'These diagnostics do not establish attack detection accuracy.']
    ax.text(0, .95, '\n\n'.join(lines), va='top', fontsize=11)
    fig.suptitle(evaluation['source_file'] + '\nLayer-2 nodes are layer-1 components, not representative flows')
    fig.tight_layout()
    save_figure(fig, folder / 'overview')

    fig, ax = plt.subplots(figsize=(15, 12))
    positions = nx.spring_layout(graph, seed=42, iterations=30, weight='weight')
    palette = plt.get_cmap('tab20')
    colors = lambda index: palette((2 * (index % 10) + index // 10 % 2) % 20)
    nx.draw_networkx_edges(graph, positions, ax=ax, alpha=.2, width=.5)
    for chunk in chunks:
        indices = [node['node_index'] for node in nodes if node['chunk_index'] == chunk]
        nx.draw_networkx_nodes(graph, positions, nodelist=indices, ax=ax,
                               node_color=[colors(chunk % 20)], node_size=25, label=f'chunk {chunk}')
    if len(nodes) <= 40:
        nx.draw_networkx_labels(graph, positions, {node['node_index']: f"ch{node['chunk_index']}:C{node['component_index']}" for node in nodes}, ax=ax, font_size=7)
    ax.legend(fontsize=7, ncol=max(1, len(chunks) // 15 + 1))
    ax.set_title('Component similarity graph — nodes colored by source chunk\nUse lineage.html for exact IDs and memberships')
    ax.axis('off')
    save_figure(fig, folder / 'component_graph')
    return matrix, chunks


def write_html(path, evaluation, nodes, graph):
    meta_for = {index: meta['meta_index'] for meta in evaluation['meta_components'] for index in meta['node_indices']}
    payload = {'nodes': [{key: value for key, value in node.items() if key not in ('member_node_ids', 'member_original_ids')}
                         for node in nodes], 'metas': evaluation['meta_components'],
               'meta_for': meta_for, 'edges': [{'source': a, 'target': b, **data} for a, b, data in graph.edges(data=True)],
               'title': evaluation['source_file']}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('&', '\\u0026')
    template = r'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Component lineage explorer</title>
<style>body{font:14px system-ui;margin:20px;background:#f8fafc;color:#172033}h1{font-size:21px}label{margin-right:18px}select,input,button{padding:7px;margin:5px}#chart{max-height:68vh;overflow:auto;background:white;border:1px solid #cbd5e1}svg text{font:12px system-ui}pre{white-space:pre-wrap;max-height:35vh;overflow:auto;background:white;padding:12px}.click{cursor:pointer}</style>
<h1 id="title"></h1><p>Chunk → original layer-1 component → new Meta-component. Every child is retained, including components without representatives.</p>
<label>Chunk <select id="chunk"><option value="">All</option></select></label><label>Meta <select id="meta"><option value="">All</option></select></label>
<label>Component ID <input id="search" placeholder="Search full/partial ID"></label><button id="reset">Reset</button><span id="counts"></span>
<p>Click a child or Meta-component for details. Hover for IDs. Scroll for all rows. Lines are membership, not similarity edges. No external connection is needed.</p>
<div id="chart"></div><pre id="details">Select a component or Meta-component.</pre>
<script>const D=__DATA__;const $=id=>document.getElementById(id);$('title').textContent=D.title;
const NS='http://www.w3.org/2000/svg';const color=i=>`hsl(${(i*137.508)%360} 58% 44%)`;
function el(tag,attrs,parent,text){const node=document.createElementNS(NS,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);if(text!==undefined)node.textContent=text;parent.appendChild(node);return node;}
function option(select,value,text){const node=document.createElement('option');node.value=value;node.textContent=text;select.appendChild(node);}
for(const chunk of [...new Set(D.nodes.map(n=>n.chunk_index))].sort((a,b)=>a-b))option($('chunk'),chunk,`Chunk ${chunk}`);
for(const meta of D.metas)option($('meta'),meta.meta_index,`M${meta.meta_index}: ${meta.component_count} components / ${meta.source_chunks.length} chunks`);
function details(data){$('details').textContent=JSON.stringify(data,null,2);}
function render(){const chunk=$('chunk').value,meta=$('meta').value,search=$('search').value.trim();
const nodes=D.nodes.filter(n=>(chunk===''||n.chunk_index===Number(chunk))&&(meta===''||D.meta_for[n.node_index]===Number(meta))&&(!search||n.component_id.includes(search)));
nodes.sort((a,b)=>a.chunk_index-b.chunk_index||a.component_index-b.component_index);$('chart').replaceChildren();
const height=Math.max(240,nodes.length*30+90),svg=el('svg',{width:1250,height,viewBox:`0 0 1250 ${height}`},$('chart'));
el('text',{x:45,y:25},svg,'Source chunks');el('text',{x:345,y:25},svg,'Layer-1 components');el('text',{x:960,y:25},svg,'Meta-components');
const ypos=new Map(nodes.map((n,i)=>[n.node_index,60+i*30]));const chunks=[...new Set(nodes.map(n=>n.chunk_index))];const metas=[...new Set(nodes.map(n=>D.meta_for[n.node_index]))].sort((a,b)=>a-b);
const my=new Map(metas.map((m,i)=>[m,80+i*(height-130)/Math.max(1,metas.length-1)]));
for(const c of chunks){const group=nodes.filter(n=>n.chunk_index===c),y=group.reduce((s,n)=>s+ypos.get(n.node_index),0)/group.length;
for(const n of group)el('line',{x1:185,y1:y,x2:340,y2:ypos.get(n.node_index),stroke:color(c),'stroke-opacity':.35},svg);
el('circle',{cx:175,cy:y,r:12,fill:color(c)},svg);el('text',{x:30,y:y+4},svg,`Chunk ${c} (${group.length} shown)`);}
for(const n of nodes){const y=ypos.get(n.node_index),m=D.meta_for[n.node_index];el('line',{x1:350,y1:y,x2:950,y2:my.get(m),stroke:color(m),'stroke-opacity':.18},svg);
const g=el('g',{class:'click'},svg);el('circle',{cx:345,cy:y,r:6,fill:color(n.chunk_index)},g);el('text',{x:360,y:y+4},g,`ch${n.chunk_index}:C${n.component_index}  …${n.component_id.slice(-10)}  n=${n.node_count}`);
el('title',{},g,n.component_id);g.onclick=()=>details({...n,meta_component_id:D.metas[m].meta_component_id,similarity_neighbors:D.edges.filter(e=>e.source===n.node_index||e.target===n.node_index)});}
for(const m of metas){const item=D.metas[m],y=my.get(m),g=el('g',{class:'click'},svg);el('rect',{x:940,y:y-10,width:20,height:20,fill:color(m)},g);
el('text',{x:970,y:y+4},g,`M${m} (${item.component_count} children)`);el('title',{},g,item.meta_component_id);
g.onclick=()=>{details(item);$('meta').value=String(m);render();};}
$('counts').textContent=`${nodes.length}/${D.nodes.length} components shown; ${metas.length} metas`;}
for(const id of ['chunk','meta','search'])$(id).addEventListener('input',render);$('reset').onclick=()=>{$('chunk').value='';$('meta').value='';$('search').value='';render();};render();
</script></html>'''
    path.write_text(template.replace('__DATA__', encoded), encoding='utf-8')


def write_reports(evaluation, nodes, graph):
    root = document_directory('hierarchy', evaluation['source_file'], layer=2, day=evaluation['source_day'])
    folder = root / 'runs' / evaluation['run_id']; folder.mkdir(parents=True, exist_ok=True)
    matrix, chunks = write_dashboard(folder, evaluation, nodes, graph)
    pages = write_lineage_pages(folder, nodes, evaluation['meta_components'])
    write_html(folder / 'lineage.html', evaluation, nodes, graph)
    evaluation['lineage_pages'] = pages
    with (folder / 'evaluation.json').open('w', encoding='utf-8') as stream:
        json.dump(evaluation, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (folder / 'lineage.json').open('w', encoding='utf-8') as stream:
        json.dump({'nodes': nodes, 'meta_components': evaluation['meta_components'],
                   'edges': [{'source': a, 'target': b, **data} for a, b, data in graph.edges(data=True)]},
                  stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (folder / 'chunk_meta_matrix.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['chunk_index'] + [meta['meta_component_id'] for meta in evaluation['meta_components']])
        for chunk, row in zip(chunks, matrix):
            writer.writerow([chunk] + row.tolist())
    with (folder / 'component_membership.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream); writer.writerow(['chunk', 'component_id', 'source_file', 'candidate_nodes', 'meta_component_id'])
        for meta in evaluation['meta_components']:
            for index in meta['node_indices']:
                node = nodes[index]
                writer.writerow([node['chunk_index'], node['component_id'], node['source_file'], node['node_count'], meta['meta_component_id']])
    lines = [evaluation['source_file'], f"run_id: {evaluation['run_id']}",
             f"chunks={len(chunks)} components={len(nodes)} edges={graph.number_of_edges()} metas={len(evaluation['meta_components'])}",
             f"candidate_nodes_traced={evaluation['candidate_node_count']}",
             f"unrepresented_components_included={evaluation['components_without_representatives']}",
             f"integrity={evaluation['integrity']}", 'Meta | Children | Candidate nodes | Chunks | Min pair similarity | Chaining warning']
    for meta in evaluation['meta_components']:
        lines.append(f"M{meta['meta_index']} | {meta['component_count']} | {meta['member_node_count']} | "
                     f"{meta['source_chunks']} | {meta['pair_similarity_min']} | {meta['chaining_warning']}")
    lines.extend(['', 'Limitations:', *evaluation['limitations']])
    (folder / 'evaluation.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'directory': str(folder), 'evaluation': str(folder / 'evaluation.json'),
            'text': str(folder / 'evaluation.txt'), 'overview': str(folder / 'overview.png'),
            'interactive_lineage': str(folder / 'lineage.html'), 'lineage': str(folder / 'lineage.json'),
            'graph': str(folder / 'component_graph.png'), 'lineage_page_count': len(pages)}
