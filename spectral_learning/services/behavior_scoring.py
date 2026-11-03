"""Normal-only calibration of reconstruction and model-disagreement scores."""
from dataclasses import dataclass
from datetime import date
import csv
import hashlib
import io
from pathlib import Path
import zipfile

import numpy as np
from sklearn.metrics import roc_auc_score, average_precision_score

from .normal_behavior import calibration_threshold, tail_probabilities


VARIANTS = ('feature', 'graph', 'spectral')
POLICIES = ('spectral_reconstruction', 'graph_reconstruction', 'feature_reconstruction',
            'feature_spectral_gap', 'feature_graph_gap', 'joint_spectral_gap')


@dataclass
class ScoreDataset:
    metadata: list
    residuals: np.ndarray
    valid: np.ndarray


def load_score_dataset(path):
    """Read plain CSV or one zipped node_scores.csv; never extract archive paths."""
    path = Path(path)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('Score input exceeds 512 MiB')
    grouped = {}
    archive = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else None
    if archive:
        members = [m for m in archive.infolist() if Path(m.filename).name == 'node_scores.csv']
        if len(members) != 1 or members[0].file_size > 512 * 1024 * 1024:
            archive.close()
            raise ValueError('Archive must contain one node_scores.csv no larger than 512 MiB')
        stream = io.TextIOWrapper(archive.open(members[0]), encoding='utf-8-sig')
    else:
        stream = path.open(encoding='utf-8-sig', newline='')
    try:
        reader = csv.DictReader(stream)
        required = {'day', 'graph_key', 'split', 'model', 'node_id', 'raw_record_id', 'score', 'valid', 'raw_label'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Missing required node_scores.csv columns')
        for row in reader:
            if row['model'] not in VARIANTS:
                raise ValueError('Unknown model in node scores')
            if row['valid'] not in ('True', 'False'):
                raise ValueError('Expected valid=True/False')
            key = (row['day'], row['graph_key'], row['node_id'])
            meta = {field: row[field] for field in ('day', 'graph_key', 'split', 'node_id', 'raw_record_id', 'raw_label')}
            if date.fromisoformat(meta['day']).isoformat() != meta['day']:
                raise ValueError('Score days must use YYYY-MM-DD format')
            if meta['split'] not in ('train', 'validation', 'calibration', 'test', 'external_test'):
                raise ValueError('Unknown score split')
            entry = grouped.setdefault(key, dict(metadata=meta, scores={}, valid={}))
            if entry['metadata'] != meta or row['model'] in entry['scores']:
                raise ValueError('Duplicate model row or inconsistent node metadata')
            valid = row['valid'] == 'True'
            score = float(row['score']) if valid else np.nan
            if valid and (not np.isfinite(score) or score < 0):
                raise ValueError('Valid reconstruction scores must be finite and nonnegative')
            entry['scores'][row['model']] = score
            entry['valid'][row['model']] = valid
    finally:
        stream.close()
        if archive:
            archive.close()
    entries = list(grouped.values())
    if not entries or any(set(e['scores']) != set(VARIANTS) for e in entries):
        raise ValueError('Each candidate needs feature, graph and spectral rows')
    metadata = [e['metadata'] for e in entries]
    residuals = np.asarray([[e['scores'][variant] for variant in VARIANTS] for e in entries])
    valid = np.asarray([all(e['valid'].values()) for e in entries])
    return ScoreDataset(metadata, residuals, valid)


def fit_score_channels(dataset, normal_day):
    rows = dataset.metadata; x = np.asarray(dataset.residuals, dtype=float)
    if x.shape != (len(rows), 3) or dataset.valid.shape != (len(rows),):
        raise ValueError('Invalid aligned residual matrix')
    reference_ids = set()
    for row in rows:
        if row['day'] == normal_day:
            if str(row['raw_label']) == '1':
                raise ValueError('Normal reference contains label=1')
            if row['raw_record_id'] in reference_ids:
                raise ValueError('Repeated raw record ID across normal reference rows/splits')
            reference_ids.add(row['raw_record_id'])
    if any(row['day'] != normal_day and row['raw_record_id'] in reference_ids for row in rows):
        raise ValueError('External raw IDs overlap the normal reference; use the full lineage-filtered evaluation first')
    train = np.asarray([r['day'] == normal_day and r['split'] == 'train' for r in rows]) & dataset.valid
    calibration = np.asarray([r['day'] == normal_day and r['split'] == 'calibration' for r in rows]) & dataset.valid
    if not train.any() or not calibration.any():
        raise ValueError('Need normal-reference train and calibration rows')
    if np.any(~np.isfinite(x[dataset.valid])) or np.any(x[dataset.valid] < 0):
        raise ValueError('Nonfinite or negative valid residual')
    # Fixed numerical regularizer, fitted only to normal TRAIN residual scales.
    floors = np.maximum(np.median(x[train], axis=0) * .01, 1e-8)
    logged = np.log(x + floors[None, :])
    channels = dict(spectral_reconstruction=x[:, 2], graph_reconstruction=x[:, 1],
                    feature_reconstruction=x[:, 0],
                    feature_spectral_gap=logged[:, 0] - logged[:, 2],
                    feature_graph_gap=logged[:, 0] - logged[:, 1])
    train_distributions = {name: np.sort(channels[name][train]).tolist()
                           for name in ('spectral_reconstruction', 'feature_spectral_gap')}
    channels['joint_spectral_gap'] = np.maximum(*[
        -np.log(tail_probabilities(distribution, channels[name]))
        for name, distribution in train_distributions.items()])
    state = dict(version='normal_residual_disagreement_v1', variant_order=list(VARIANTS),
                 floors=floors.tolist(), numerical_regularizer='.01 * normal-training median, minimum 1e-8',
                 formula='log(feature_residual + feature_floor) - log(graph_or_spectral_residual + corresponding_floor)',
                 fit_population='normal training rows only; labels and external scores are not fitted',
                 calibration_population='separate normal calibration rows only',
                 normal_day=normal_day, train_nodes=int(train.sum()), calibration_nodes=int(calibration.sum()),
                 normal_training_distributions=train_distributions,
                 joint_formula='max(-log(normal-train right-tail rank of spectral residual), -log(normal-train right-tail rank of feature/spectral gap)); calibrate the joint score separately',
                 interpretation='Model disagreement, not an attack probability or a proven mechanism of graph oversmoothing')
    return channels, calibration, state


def evaluate_score_channels(dataset, normal_day, alphas=(.01, .05, .1)):
    if not alphas or len(set(alphas)) != len(alphas) or any(not 0 < a < 1 for a in alphas):
        raise ValueError('Alphas must be distinct numbers between 0 and 1')
    channels, calibration, state = fit_score_channels(dataset, normal_day)
    groups = sorted({(row['day'], row['split']) for row in dataset.metadata})
    thresholds = {name: {str(alpha): calibration_threshold(values[calibration], alpha) for alpha in alphas}
                  for name, values in channels.items()}
    labels = np.asarray([int(r['raw_label']) if str(r['raw_label']) in ('0', '1') else -1 for r in dataset.metadata])
    rows = []
    for day, split in groups:
        chosen = np.asarray([r['day'] == day and r['split'] == split for r in dataset.metadata]) & dataset.valid
        benign = chosen & (labels == 0); tagged = chosen & (labels == 1)
        known = chosen & (labels >= 0)
        for name, score in channels.items():
            both = benign.any() and tagged.any()
            auc = float(roc_auc_score(labels[known], score[known])) if both else None
            ap = float(average_precision_score(labels[known], score[known])) if both else None
            for alpha in alphas:
                cutoff = thresholds[name][str(alpha)]
                alert = chosen & (score > cutoff)
                baseline_alert = chosen & (channels['spectral_reconstruction'] > thresholds['spectral_reconstruction'][str(alpha)])
                tp, fp = int((alert & tagged).sum()), int((alert & benign).sum())
                rows.append(dict(day=day, split=split, score_policy=name, alpha=alpha, threshold=cutoff,
                    scored_nodes=int(chosen.sum()), alert_nodes=int(alert.sum()),
                    label0_nodes=int(benign.sum()), label1_nodes=int(tagged.sum()),
                    label1_alerts=tp, label0_alerts=fp, label1_missed=int(tagged.sum())-tp,
                    recall_label1=tp/int(tagged.sum()) if tagged.any() else None,
                    false_alert_fraction_label0=fp/int(benign.sum()) if benign.any() else None,
                    precision_label1=tp/(tp+fp) if tp+fp else None,
                    original_alerts_retained=int((alert & baseline_alert).sum()),
                    original_alerts_lost=int((~alert & baseline_alert).sum()),
                    new_alerts=int((alert & ~baseline_alert).sum()),
                    original_label1_alerts_lost=int((~alert & baseline_alert & tagged).sum()),
                    new_label1_alerts=int((alert & ~baseline_alert & tagged).sum()),
                    label1_prevalence=float(labels[known].mean()) if known.any() else None,
                    node_score_roc_auc=auc, node_score_average_precision=ap,
                    heldout_normal_false_alert_fraction=float(alert[chosen].mean()) if day == normal_day and split == 'test' and chosen.any() else None))
    state['thresholds'] = thresholds
    state['alphas'] = list(alphas)
    return channels, rows, state


def source_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
