import pytest

from collector.names import better_name, name_score


@pytest.mark.parametrize(
    ("worse", "better"),
    [
        ("חלב 3%", "חלב טרה 3% בקרטון 1 ליטר"),
        ("חלב תנובה 3% 1 ל", "חלב תנובה 3% שומן בקרטון 1 ליטר"),
        ("קוטג' תנובה 5% 250 גר...", "קוטג' תנובה 5% 250 גרם"),  # cut off by the chain
        ("MILK TERA 1L", "חלב טרה 1 ליטר"),  # shouted, no Hebrew
        ("7290000042015", "חלב מהדרין 3% שקית 1 ליטר"),  # a code instead of a name
        ("", "לחם אחיד"),
        ("קולה * מבצע !!! " + "ממש זול " * 12, "קולה 1.5 ליטר"),  # promotion text pasted in
    ],
)
def test_the_clearer_name_scores_higher(worse, better):
    assert name_score(better) > name_score(worse)
    assert better_name(worse, better) == better
    assert better_name(better, worse) == better  # whichever chain comes first


def test_a_tie_keeps_the_name_already_chosen():
    assert better_name("חלב תנובה 3%", "חלב תנובה 3%") == "חלב תנובה 3%"
    assert better_name("חלב מלא 3%", "חלב כבש 3%") == "חלב מלא 3%"  # equal information


def test_spacing_does_not_matter():
    assert name_score("חלב   טרה  3%") == name_score("חלב טרה 3%")
