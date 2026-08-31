"""Tests for progress_service's run-exclusivity mechanism (claim_check_all/
claim_check_perfume and their release counterparts) - see its own module
docstring for the full rationale. Display-side behavior (RunProgress/
StoreProgress bookkeeping) isn't covered here; these tests are only about
whether a claim is granted or refused.
"""

from app.services import progress as progress_service


def test_claim_check_all_succeeds_when_nothing_active():
    assert progress_service.claim_check_all() is True


def test_claim_check_all_refused_while_already_active():
    progress_service.claim_check_all()

    assert progress_service.claim_check_all() is False


def test_claim_check_all_succeeds_again_after_release():
    progress_service.claim_check_all()
    progress_service.release_check_all()

    assert progress_service.claim_check_all() is True


def test_claim_check_perfume_succeeds_when_nothing_active():
    assert progress_service.claim_check_perfume(1) is True


def test_claim_check_perfume_refused_for_same_perfume_while_active():
    progress_service.claim_check_perfume(1)

    assert progress_service.claim_check_perfume(1) is False


def test_claim_check_perfume_succeeds_for_a_different_perfume():
    # Two different perfumes never touch each other's rows, so both may
    # be checked concurrently - only the *same* perfume is exclusive.
    progress_service.claim_check_perfume(1)

    assert progress_service.claim_check_perfume(2) is True


def test_claim_check_perfume_succeeds_again_after_release():
    progress_service.claim_check_perfume(1)
    progress_service.release_check_perfume(1)

    assert progress_service.claim_check_perfume(1) is True


def test_release_check_perfume_does_not_affect_a_different_perfumes_claim():
    progress_service.claim_check_perfume(1)
    progress_service.claim_check_perfume(2)

    progress_service.release_check_perfume(1)

    assert progress_service.claim_check_perfume(1) is True
    assert progress_service.claim_check_perfume(2) is False


def test_check_all_refused_while_a_single_perfume_check_is_active():
    # A check-all touches every perfume, including whichever one already
    # has its own check in flight - letting both run would race that
    # perfume's writes the same way two check-alls would race each other.
    progress_service.claim_check_perfume(1)

    assert progress_service.claim_check_all() is False


def test_single_perfume_check_refused_while_check_all_is_active():
    progress_service.claim_check_all()

    assert progress_service.claim_check_perfume(1) is False


def test_check_all_succeeds_after_the_only_active_perfume_check_releases():
    progress_service.claim_check_perfume(1)
    progress_service.release_check_perfume(1)

    assert progress_service.claim_check_all() is True
