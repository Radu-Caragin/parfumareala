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

# --- run exclusivity -------------------------------------------------------
#
# Separate from _progress above (which only exists once a run has actually
# started executing, inside its background task, well after the route that
# scheduled it has already returned) - a route posting /check-all or
# /perfumes/{id}/check must refuse a second overlapping run *before*
# scheduling the background task, or a duplicate slips through the gap
# between "request received" and "background task actually starts running".
# Claimed synchronously in the route handler itself; released in a finally
# block once the background task (success or failure) is done. A single
# in-memory set is enough for the same reason _progress is a plain dict -
# single-process, single-user app, no external store needed, and a stuck
# claim from a hard crash clears itself on the next restart.
#
# Only one "check all" may be active at a time, and it excludes every
# single-perfume check (a check-all touches every perfume, so it would
# race a perfume's own in-flight check the same way two check-alls would
# race each other) - but two *different* perfumes' own checks may run
# concurrently, since they never touch each other's rows.

ALL_CHECK_KEY = "all"
_PERFUME_KEY_PREFIX = "perfume:"

_active: set[str] = set()


def perfume_check_key(perfume_id: int) -> str:
    return f"{_PERFUME_KEY_PREFIX}{perfume_id}"


def claim_check_all() -> bool:
    """Reserves the "check all" slot. False (claim refused) if a check-all
    is already active, or if any single-perfume check is active."""
    if _active:
        return False
    _active.add(ALL_CHECK_KEY)
    return True


def release_check_all() -> None:
    _active.discard(ALL_CHECK_KEY)


def claim_check_perfume(perfume_id: int) -> bool:
    """Reserves the single-perfume slot for `perfume_id`. False (claim
    refused) if that perfume already has an active check, or a check-all
    is running (which already covers every perfume, including this one).
    """
    if ALL_CHECK_KEY in _active:
        return False
    key = perfume_check_key(perfume_id)
    if key in _active:
        return False
    _active.add(key)
    return True


def release_check_perfume(perfume_id: int) -> None:
    _active.discard(perfume_check_key(perfume_id))


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
