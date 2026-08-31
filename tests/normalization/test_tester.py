import pytest

from app.normalization.tester import is_tester, strip_tester_tokens


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tester", True),
        ("TESTER", True),
        ("tester perfume", True),
        ("100 ml tester", True),
        ("Xerjoff Naxos EDP 100 ml Tester", True),
        ("Xerjoff Naxos EDP 100 ml", False),
        ("Testerino Cosmetics", False),
    ],
)
def test_is_tester(raw, expected):
    assert is_tester(raw) == expected


def test_strip_tester_tokens_removes_the_word():
    assert "tester" not in strip_tester_tokens("erba gold tester 100 ml")


def test_is_tester_detects_word_glued_directly_onto_preceding_text():
    # Regression: Fragranza.ro's own raw HTML sometimes glues "Tester"
    # directly onto the preceding word with no space at all - confirmed
    # live, "Apă de parfumTester EDP" is literally in the page's markup,
    # not a BeautifulSoup text-concatenation artifact. \btester\b can't
    # match inside "parfumtester" (no boundary between two word
    # characters), which silently missed a real tester and made it
    # collide with the regular bottle as the exact same variant once
    # persisted (confirmed live on Xerjoff XJ 1861 Naxos - two separate
    # product pages upserted into a single StoreProduct row, one silently
    # overwriting the other).
    assert is_tester("Xerjoff Xj 1861 Naxos Apă de parfumTester EDP") is True


def test_is_tester_glued_detection_requires_capital_t_as_the_boundary_signal():
    # An already-lowercased string has no way to distinguish a genuinely
    # glued "tester" from an ordinary word ending the same way - the
    # capital "T" is the only real signal, so a lowercase "tester" glued
    # onto another lowercase word must NOT be treated as a match (this
    # never happens in practice - see strip_tester_tokens's own
    # docstring for why - but the pattern's own precision must not
    # silently degrade into a bare, unanchored substring search).
    assert is_tester("parfumtester") is False
