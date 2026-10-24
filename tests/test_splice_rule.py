"""Rule B (2026-10-20): a "..."-spliced quote is found when its parts appear in the text in the quote's order."""

from src.evaluation.claim_verification import match_quote

TEXT = ("Firms must give customers clear information. This applies to all products. "
        "Firms must also check that customers understand it.")


def test_parts_in_order_are_found_as_spliced():
    m = match_quote("give customers clear information ... check that customers understand it", TEXT)
    assert m["match_type"] == "spliced"
    assert match_quote("give customers clear information … check that customers understand it", TEXT)["match_type"] == "spliced"


def test_parts_out_of_order_or_invented_are_not_found():
    assert match_quote("check that customers understand it ... give customers clear information", TEXT)["match_type"] == "none"
    assert match_quote("give customers clear information ... and refund every fee at once", TEXT)["match_type"] == "none"


def test_parts_match_whole_words_and_every_part_needs_three_words():
    assert match_quote("give customers clear info ... check that customers understand it", TEXT)["match_type"] == "none"
    # 2026-10-24: a part under 3 words fails the splice, even though it is in the text
    assert match_quote("It ... give customers clear information", TEXT)["match_type"] == "none"
    assert match_quote("give customers clear information ... understand it", TEXT)["match_type"] == "none"
    # exactly 3 words is enough
    assert match_quote("customers clear information ... customers understand it", TEXT)["match_type"] == "spliced"
    # a leading "..." is not a part
    assert match_quote("... give customers clear information ... check that customers understand it",
                       TEXT)["match_type"] == "spliced"


def test_ordinary_matches_are_unchanged():
    assert match_quote("Firms must give customers clear information.", TEXT)["match_type"] == "exact"
    assert match_quote("firms must give customers clear information", TEXT)["match_type"] == "normalised"
    assert match_quote("nothing like this is in the text at all", TEXT)["match_type"] == "none"
