"""In-memory progress tracking for background price-check runs.

Single-process, single-user app - a plain module-level dict is enough, no
external store needed. This exists only so the UI can poll "how far along
is this run" while it happens; it isn't persisted anywhere else. A run's
entry is simply overwritten by start() the next time that same key is
checked, so nothing needs explicit cleanup on a normal timeline - but
callers that want to drop a finished entry immediately (rather than
leaving it for the next start() to overwrite) can call clear().
"""

from dataclasses import dataclass, field
from typing import Literal

from app.database.models import Store

StoreStatus = Literal["pending", "checking", "done"]


@dataclass
class StoreProgress:
    store_id: int
    store_name: str
    status: StoreStatus = "pending"


@dataclass
class RunProgress:
    total_perfumes: int
    current_perfume_index: int
    current_perfume_label: str
    stores: dict[int, StoreProgress] = field(default_factory=dict)
    done: bool = False

    @property
    def completed_store_count(self) -> int:
        return sum(1 for s in self.stores.values() if s.status == "done")

    @property
    def total_store_count(self) -> int:
        return len(self.stores)


_progress: dict[str, RunProgress] = {}


def start_perfume(
    key: str, *, index: int, total: int, label: str, stores: list[Store]
) -> None:
    """Begins tracking (or resets, for check_all_perfumes moving on to its
    next perfume) one perfume's pass over the given stores."""
    _progress[key] = RunProgress(
        total_perfumes=total,
        current_perfume_index=index,
        current_perfume_label=label,
        stores={s.id: StoreProgress(store_id=s.id, store_name=s.name) for s in stores},
    )


def mark_checking(key: str, store_id: int) -> None:
    run = _progress.get(key)
    if run is not None and store_id in run.stores:
        run.stores[store_id].status = "checking"


def mark_store_done(key: str, store_id: int) -> None:
    run = _progress.get(key)
    if run is not None and store_id in run.stores:
        run.stores[store_id].status = "done"


def finish(key: str) -> None:
    run = _progress.get(key)
    if run is not None:
        run.done = True


def get(key: str) -> RunProgress | None:
    return _progress.get(key)


def clear(key: str) -> None:
    _progress.pop(key, None)
