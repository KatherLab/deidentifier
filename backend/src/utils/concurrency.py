"""Process-global concurrency slots.

When several documents are processed in parallel (multi-file upload), the
model endpoints must not receive documents × per-request-limit concurrent
calls. These semaphores are shared across ALL in-flight requests, so the
configured limits are true totals and work interleaves at the stage level
(one document's OCR pages run while another's detection chunks are in
flight).

Scoped per event loop: asyncio primitives cannot be shared across loops, and
the test suite creates a fresh loop per test. Production runs a single loop.
"""

import asyncio

_semaphores: dict[tuple[int, str, int], asyncio.Semaphore] = {}


def global_semaphore(name: str, limit: int) -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, name, limit)
    semaphore = _semaphores.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _semaphores[key] = semaphore
        if len(_semaphores) > 64:  # prune entries from finished (test) loops
            for stale in [k for k in _semaphores if k[0] != loop_id]:
                _semaphores.pop(stale, None)
    return semaphore
