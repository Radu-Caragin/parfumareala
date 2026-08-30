"""Data-access functions for ScrapeRun and ScrapeResult."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import RunStatus, RunType, ScrapeResult, ScrapeResultStatus, ScrapeRun
from app.utils.helpers import utcnow


def get(db: Session, run_id: int) -> ScrapeRun | None:
    return db.get(ScrapeRun, run_id)


def get_latest(db: Session) -> ScrapeRun | None:
    return db.scalar(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(1))


def start_run(db: Session, *, run_type: RunType, perfume_count: int, store_count: int) -> ScrapeRun:
    run = ScrapeRun(
        run_type=run_type,
        status=RunStatus.RUNNING,
        perfume_count=perfume_count,
        store_count=store_count,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(db: Session, run: ScrapeRun, *, status: RunStatus) -> ScrapeRun:
    run.status = status
    run.finished_at = utcnow()
    db.commit()
    db.refresh(run)
    return run


def add_result(
    db: Session,
    *,
    scrape_run_id: int,
    perfume_id: int,
    store_id: int,
    status: ScrapeResultStatus,
    offers_found: int = 0,
    error_message: str | None = None,
) -> ScrapeResult:
    result = ScrapeResult(
        scrape_run_id=scrape_run_id,
        perfume_id=perfume_id,
        store_id=store_id,
        status=status,
        offers_found=offers_found,
        error_message=error_message,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def list_for_perfume(db: Session, perfume_id: int, *, limit: int = 50) -> list[ScrapeResult]:
    return list(
        db.scalars(
            select(ScrapeResult)
            .where(ScrapeResult.perfume_id == perfume_id)
            .order_by(ScrapeResult.created_at.desc())
            .limit(limit)
        )
    )


def get_latest_results_for_perfume(db: Session, perfume_id: int) -> list[ScrapeResult]:
    """One ScrapeResult per store: the most recent check for this perfume.

    Used to show current per-store status (instructions.md section 55 -
    current comparison must reflect the most recent completed check, not
    an arbitrary historical row).
    """
    latest_per_store = (
        select(ScrapeResult.store_id, func.max(ScrapeResult.created_at).label("max_created_at"))
        .where(ScrapeResult.perfume_id == perfume_id)
        .group_by(ScrapeResult.store_id)
        .subquery()
    )

    return list(
        db.scalars(
            select(ScrapeResult).join(
                latest_per_store,
                (ScrapeResult.store_id == latest_per_store.c.store_id)
                & (ScrapeResult.created_at == latest_per_store.c.max_created_at)
                & (ScrapeResult.perfume_id == perfume_id),
            )
        )
    )
