from app.database.repositories import perfumes as perfumes_repo
from app.services.perfume_service import create_perfume, update_perfume


def test_create_perfume_sets_normalized_fields(db_session):
    perfume = create_perfume(db_session, brand="  Xerjoff  ", name="  Erba Gold  ")

    assert perfume.brand == "Xerjoff"
    assert perfume.name == "Erba Gold"
    assert perfume.normalized_brand == "xerjoff"
    assert perfume.normalized_name == "erba gold"


def test_update_perfume_recomputes_normalized_fields(db_session):
    perfume = create_perfume(db_session, brand="Xerjoff", name="Erba Gold")

    updated = update_perfume(db_session, perfume, brand="Xerjoff", name="Naxos")

    assert updated.normalized_name == "naxos"
    assert perfumes_repo.get(db_session, perfume.id).name == "Naxos"
