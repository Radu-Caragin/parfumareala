import pytest

from app.normalization.exclusions import check_exclusion, is_excluded


@pytest.mark.parametrize(
    "raw",
    [
        "Xerjoff Erba Gold Refill 100ml",
        "Dior Gift Set EDT 100ml + Body Lotion",
        "Set cadou Xerjoff Erba Gold",
        "Coffret Dior Sauvage",
        "Discovery Set Xerjoff",
        "Sample Xerjoff Erba Gold 2ml",
        "Sample Set - 5 x 2ml",
        "Miniature Collection Xerjoff",
        "Xerjoff Miniaturi",
        "Bundle Xerjoff Naxos + Erba Gold",
        'Xerjoff " V " Erba Gold Apă de parfum decant 1 ml',
        "Xerjoff Erba Gold decant 5ml",
        "Xerjoff Erba Gold esantion 2ml",
        "Xerjoff Erba Gold mostra 2ml",
    ],
)
def test_excluded_products(raw):
    assert is_excluded(raw) is True


@pytest.mark.parametrize(
    "raw",
    [
        "Xerjoff Erba Gold EDP 100 ml",
        "Xerjoff Erba Gold EDP 100 ml Tester",
        "Sticla refillable Xerjoff Erba Gold 100ml",
        "Dior Sauvage EDT 100 ml",
    ],
)
def test_valid_products_not_excluded(raw):
    assert is_excluded(raw) is False


def test_check_exclusion_returns_reason():
    assert check_exclusion("Xerjoff Erba Gold Refill 100ml") == "refill"
    assert check_exclusion("Xerjoff Erba Gold decant 5ml") == "decant"
