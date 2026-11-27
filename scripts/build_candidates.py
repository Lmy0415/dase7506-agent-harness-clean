"""Prepare disjoint seeded family pools from the pinned AppWorld release."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / '.upstream/InterventionBench/data/appworld_interventions.jsonl'
APPWORLD_TASKS = ROOT / '.appworld/data/tasks'
UPSTREAM_DATA_SHA256 = '4212365f457fda19dbb642888990e1dff2c63bb4a3724998d3ae2362a588a4c1'
UPSTREAM_COMMIT = '7fe53126b93e8d3ef7e28bafbf8db6c6060e679e'
SEED = 7506
DIAGNOSTIC_FAMILIES = {'31dc501', '771d8fc'}
PILOT_POOL_PER_TYPE = 8
STRATA = ('Drop', 'Swap')


def rank(namespace, identifier):
    return hashlib.sha256(f'{SEED}|{namespace}|{identifier}'.encode()).hexdigest()


def weave(queues):
    """Start with the scarce stratum and alternate until one queue is exhausted."""
    for index in range(max(map(len, queues.values()))):
        for kind in STRATA:
            if index < len(queues[kind]):
                yield kind, queues[kind][index]


def write_jsonl(path, rows):
    with path.open('w', encoding='utf-8') as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def main():
    if hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() != UPSTREAM_DATA_SHA256:
        raise RuntimeError('InterventionBench input is different from the pinned release.')
    families = defaultdict(lambda: defaultdict(list))
    census = Counter()
    for row in map(json.loads, UPSTREAM.read_text().splitlines()):
        if row.get('skip') or row.get('_skipped'):
            census['official_skip'] += 1
            continue
        kind = next((kind for kind in STRATA if row['type'].endswith(kind)), None)
        if kind is None:
            census['out_of_scope'] += 1
            continue
        task_id = row['base_task_id']
        family, separator, variant = task_id.rpartition('_')
        if not (separator and family and variant.isdigit()):
            raise ValueError(f'Unexpected AppWorld task ID {task_id!r}.')
        if family in DIAGNOSTIC_FAMILIES:
            census['diagnostic_family'] += 1
            continue
        specs = APPWORLD_TASKS / task_id / 'specs.json'
        fields = ('evaluation_code', 'modified_spec_b', 'intervention_text')
        if not specs.is_file() or not all(row.get(field) for field in fields):
            census['missing_data'] += 1
            continue
        families[family][kind].append(row)
        census['candidate_variant'] += 1

    for choices in families.values():
        for rows in choices.values():
            rows.sort(key=lambda row: rank('variant', row['intervention_idx']))

    assigned = set()
    ordered = sorted(families, key=lambda family: rank('family', family))
    pools = {split: {kind: [] for kind in STRATA} for split in ('pilot', 'formal')}
    for kind in STRATA:
        eligible = [family for family in ordered if kind in families[family] and family not in assigned]
        pools['pilot'][kind] = eligible[:PILOT_POOL_PER_TYPE]
        assigned.update(pools['pilot'][kind])

    formal_families = [family for family in ordered if family not in assigned]
    for family in formal_families:
        options = families[family]
        if len(options) == 1:
            pools['formal'][next(iter(options))].append(family)
    for family in formal_families:
        if len(families[family]) > 1:
            queues = pools['formal']
            kind = min(STRATA, key=lambda kind: len(queues[kind]))
            queues[kind].append(family)
    for queue in pools['formal'].values():
        queue.sort(key=lambda family: rank('family', family))

    protocol = ROOT / 'protocol'
    protocol.mkdir(exist_ok=True)
    index, records = [], []
    for split, groups in pools.items():
        for queue_position, (kind, family) in enumerate(weave(groups), start=1):
            for variant_order, row in enumerate(families[family][kind], start=1):
                task_id = row['base_task_id']
                public_item = {
                    'split': split,
                    'family_id': family,
                    'queue_position': queue_position,
                    'stratum': kind,
                    'type': row['type'],
                    'task_id': task_id,
                    'intervention_id': row['intervention_idx'],
                    'variant_order': variant_order,
                }
                index.append(public_item)
                records.append({
                    **public_item,
                    'original_goal': json.loads((APPWORLD_TASKS / task_id / 'specs.json').read_text())['instruction'],
                    'intervention_text': row['intervention_text'],
                    'standalone_revised_goal': row['modified_spec_b'],
                    'evaluator': {'commit': UPSTREAM_COMMIT, 'dataset_row': row['intervention_idx']},
                    'checkpoint_rule': 'before first confirmed withdrawn write',
                })
    write_jsonl(protocol / 'candidate_index.jsonl', index)
    write_jsonl(protocol / 'candidates.jsonl', records)
    counts = {split: {kind: len(items) for kind, items in groups.items()} for split, groups in pools.items()}
    summary = {
        'seed': SEED, 'upstream_commit': UPSTREAM_COMMIT, 'appworld_jsonl_sha256': UPSTREAM_DATA_SHA256,
        'diagnostic_families': sorted(DIAGNOSTIC_FAMILIES),
        'family_counts': counts, 'row_counts': dict(census),
        'indexed_variants': len(index), 'unassigned_stratum_variants': census['candidate_variant'] - len(index),
    }
    (protocol / 'candidate_census.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
