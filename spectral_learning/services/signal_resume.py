"""Validate/reuse a completed JSONL export after a source/persistence outage.

An incomplete .tmp export is never promoted or silently truncated.
"""
import json
import numpy as np
from .spectral_inputs import fingerprint
from .normal_behavior import tail_probabilities


def collect_row(row, summaries, samples, channels):
    key=(row['entity']['source_day'],row['split'],row['isolated'])
    if len(samples.setdefault(key,[]))<2:samples[key].append(row)
    for name in channels:
        signal=row['signals'][name];key=(row['entity']['source_day'],row['split'],name,signal['calibration_group'])
        counts=summaries.setdefault(key,dict(nodes=0,valid=0,unavailable=0,uncalibrated=0,tail_exceedances=0))
        counts['nodes']+=1;counts[signal['status']]+=1;counts['tail_exceedances']+=signal['exceeds_tail'] is True


def reuse_completed_export(folder, graphs, splits, identity, run_id, calibration_id, reference_id, alpha):
    from .behavior_signal_inputs import CHANNELS,validate_observation,fit_calibration
    path=folder/'observations.jsonl'
    if not path.is_file():
        raise ValueError('Resume requires a completed observations.jsonl; an incomplete .tmp file cannot be reused. Rerun without --resume-signal-bundle.')
    expected=((graph,graph.signature) for graph in graphs)
    expected=((graph,i,signature) for graph,signature in expected for i in range(len(graph.node_ids)))
    summaries={};samples={};calibration_rows=[];count=0
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line);validate_observation(row)
            if fingerprint({k:v for k,v in row.items() if k!='content_sha256'})!=row['content_sha256']:
                raise ValueError('Resume observation checksum mismatch')
            item=next(expected,None)
            if item is None:raise ValueError('Resume export has unexpected extra observations')
            graph,i,signature=item
            expected_id=fingerprint(dict(run_id=run_id,graph=graph.key,node=str(graph.node_ids[i])))
            if (row['_id']!=expected_id or row['run_id']!=run_id or row['model_id']!=identity['checkpoint']
                    or row['reference_run_id']!=reference_id or row['calibration_id']!=calibration_id
                    or row['split']!=splits[graph.key] or row['entity']['graph_key']!=graph.key
                    or row['entity']['source_day']!=graph.day or row['entity']['node_id']!=str(graph.node_ids[i])
                    or row['raw_source']['record_id']!=str(graph.lineage[i]['original_id'])
                    or row['source_signature']!=identity['source_signatures'][graph.day][graph.key]
                    or row['inference_graph_signature']!=signature
                    or row['raw_lineage_signature']!=identity['lineage_signatures'][graph.key]):
                raise ValueError('Resume export differs from pinned model/source/roles')
            if row['split']=='calibration':calibration_rows.append(row)
            collect_row(row,summaries,samples,CHANNELS);count+=1
    if next(expected,None) is not None:raise ValueError('Resume export is incomplete; source candidate count differs')
    arrays={'isolated':np.asarray([r['isolated'] for r in calibration_rows],dtype=bool)}
    for channel in CHANNELS:
        values=[r['signals'][channel]['residual'] for r in calibration_rows]
        arrays[channel+'_valid']=np.asarray([v is not None for v in values],dtype=bool)
        arrays[channel+'_mse']=np.asarray([v if v is not None else 0 for v in values],dtype=float)
    calibration=fit_calibration([('calibration',arrays)],alpha)
    metadata=json.loads((folder/'calibration.json').read_text(encoding='utf-8'))
    expected_metadata={k:{n:v for n,v in state.items() if n!='values'} for k,state in calibration.items()}
    if metadata!=expected_metadata:raise ValueError('Resume calibration metadata differs from exported calibration rows')
    with np.load(folder/'calibration_arrays.npz',allow_pickle=False) as stored:
        if set(stored.files)!={k.replace(':','_') for k in calibration}:
            raise ValueError('Resume calibration schema mismatch')
        if any(not np.array_equal(stored[k.replace(':','_')],state['values']) for k,state in calibration.items()):
            raise ValueError('Resume calibration arrays differ from exported calibration rows')
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            for channel in CHANNELS:
                signal=row['signals'][channel]
                if signal['residual'] is None:continue
                state=calibration[channel+':'+signal['calibration_group']]
                if state['status']=='calibrated':
                    tail=float(tail_probabilities(state['values'],[signal['residual']])[0])
                    if (signal['status']!='valid' or signal['threshold']!=state['threshold']
                            or signal['calibration_id']!=calibration_id
                            or not np.isclose(signal['tail_probability'],tail,rtol=0,atol=1e-12)):
                        raise ValueError('Resume calibrated signal differs from pinned distribution')
                elif signal['status']!='uncalibrated':
                    raise ValueError('Resume signal is incorrectly marked calibrated')
    return count,summaries,samples
