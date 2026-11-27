"""Persist a pre-write AppWorld checkpoint and its exact model-visible context."""

import hashlib
import json
import random
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def state_signature(world):
    return {
        'task_id': world.task_id,
        'clock': datetime.now().isoformat(),
        'model_hashes_sha256': digest(world.models.model_hashes()),
    }


def directory_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.iterdir())}


def save(world, destination, *, history, old_plan, pending, tool_log, adapter_state=None):
    """Export the state before applying pending. AppWorld owns the temporary checkpoint."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    checkpoint_id = world.save_state(f'export-{uuid4().hex}')
    snapshot = Path(world.output_checkpoints_directory) / checkpoint_id
    try:
        with TemporaryDirectory(dir=destination.parent) as directory:
            staged = Path(directory) / 'state'
            shutil.copytree(snapshot, staged / 'db')
            manifest = {
                'state': state_signature(world),
                'db_hashes': directory_hashes(staged / 'db'),
                'rng': random.getstate(),
                'history': history,
                'old_plan': old_plan,
                'pending': pending,
                'tool_log': tool_log,
                'adapter_state': adapter_state,
                'adapter_state_sha256': digest(adapter_state),
                'context_sha256': digest([history, old_plan, pending]),
            }
            (staged / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False) + '\n')
            staged.rename(destination)
    finally:
        shutil.rmtree(snapshot)
    return manifest


def restore(world, source):
    """Load an independent copy into a fresh branch and verify state and context."""
    source = Path(source)
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest['state']['task_id'] != world.task_id:
        raise ValueError('Checkpoint belongs to a different AppWorld task.')
    context = [manifest[name] for name in ('history', 'old_plan', 'pending')]
    if manifest['context_sha256'] != digest(context):
        raise ValueError('Checkpoint context checksum mismatch.')
    if 'adapter_state_sha256' in manifest and manifest['adapter_state_sha256'] != digest(manifest['adapter_state']):
        raise ValueError('Checkpoint adapter state checksum mismatch.')
    if manifest['db_hashes'] != directory_hashes(source / 'db'):
        raise ValueError('Checkpoint database checksum mismatch.')
    checkpoint_id = f'restore-{uuid4().hex}'
    branch_copy = Path(world.output_checkpoints_directory) / checkpoint_id
    shutil.copytree(source / 'db', branch_copy)
    world.load_state(checkpoint_id)
    # AppWorld 0.1.3.post1 clears the simulator clock during load_state.
    world._set_datetime()
    version, rng, gauss = manifest['rng']
    random.setstate((version, tuple(rng), gauss))
    if state_signature(world) != manifest['state']:
        raise RuntimeError('The restored simulator state differs from the common prefix.')
    return manifest
