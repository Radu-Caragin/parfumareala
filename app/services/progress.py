"""In-memory progress tracking for background price-check runs.

Single-process, single-user app - a plain module-level dict is enough, no
external store needed. This exists only so the UI can poll "how far along
is this run" while it happens; it isn't persisted anywhere else. A run's
entry is simply overwritten by start_run() the next time that same key is
checked, so nothing needs explicit cleanup on a normal timeline - but
callers that want to drop a finished entry immediately (rather than
leaving it for the next start_run() to overwrite) can call clear().

Tracked per store, not per "the one current perfume": check_all_perfumes
now checks every monitored perfume concurrently (see its docstring) so
that a fast store isn't held idle waiting for the run's slowest store to
finish the perfume currently in front of it - which means many perfumes
can be in flight across different stores at the same moment, each store
working through its own queue at its own pace. A single global "currently
checking X (i/N)" field can't represent that without corrupting itself
every time a different store starts its next perfume, so each store
tracks its own completed/total count and whichever perfume label it's
on right now. check_perfume (one perfume) is just the total=1 case of
the same model.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.database.models import Store

StoreStatus = Literal["pending", "checking", "done"]


@dataclass
class StoreProgress:
    store_id: int
    store_name: str
    total: int
    completed: int = 0
    current_label: str | None = None

    @property
    def status(self) -> StoreStatus:
        if self.completed >= self.total:
            return "done"
        if self.current_label is not None:
            return "checking"
        return "pending"


@dataclass
class RunProgress:
    stores: dict[int, StoreProgress] = field(default_factory=dict)
    done: bool = False

    @property
    def completed_store_count(self) -> int:
        return sum(1 for s in self.stores.values() if s.status == "done")

    @property
    def total_store_count(self) -> int:
        return len(self.stores)

    @property
    def completed_check_count(self) -> int:
        return sum(s.completed for s in self.stores.values())

    @property
    def total_check_count(self) -> int:
        return sum(s.total for s in self.stores.values())


_progress: dict[str, RunProgress] = {}


def start_run(key: str, *, stores: list[Store], perfume_count: int) -> None:
    """Begins tracking one check run against the given stores - either one
    perfume (perfume_count=1) or many, checked concurrently. Each store
    gets its own independent counter (perfume_count checks to do)."""
    _progress[key] = RunProgress(
        stores={s.id: StoreProgress(store_id=s.id, store_name=s.name, total=perfume_count) for s in stores},
    )


def mark_checking(key: str, store_id: int, perfume_label: str) -> None:
    run = _progress.get(key)
    if run is not None and store_id in run.stores:
        run.stores[store_id].current_label = perfume_label


def mark_store_progress(key: str, store_id: int) -> None:
    """One (perfume, store) check finished - advances that store's own
    counter. Not "mark done": under concurrent perfumes a store may have
    more queued after this one."""
    run = _progress.get(key)
    if run is not None and store_id in run.stores:
        store_progress = run.stores[store_id]
        store_progress.completed += 1
        store_progress.current_label = None


def finish(key: str) -> None:
    run = _progress.get(key)
    if run is not None:
        run.done = True


def get(key: str) -> RunProgress | None:
    return _progress.get(key)


def clear(key: str) -> None:
    _progress.pop(key, None)
