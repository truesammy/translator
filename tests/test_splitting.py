from translator_bot.splitting import split_text, truncate


def test_short_text_is_one_part():
    assert split_text("hi") == ["hi"]


def test_empty_text_is_no_parts():
    assert split_text("") == []


def test_text_at_limit_is_one_part():
    assert split_text("a" * 2000) == ["a" * 2000]


def test_prefers_paragraph_boundary():
    a, b = "a" * 1500, "b" * 1500
    assert split_text(f"{a}\n\n{b}") == [a, b]


def test_falls_back_to_newline_then_space_then_hard_cut():
    assert split_text("a" * 1500 + "\n" + "b" * 1500) == ["a" * 1500, "b" * 1500]
    assert split_text("a" * 1500 + " " + "b" * 1500) == ["a" * 1500, "b" * 1500]
    assert [len(p) for p in split_text("a" * 4500)] == [2000, 2000, 500]


def test_every_part_within_limit_and_nothing_lost():
    text = "word " * 3000
    parts = split_text(text)
    assert all(0 < len(p) <= 2000 for p in parts)
    assert " ".join(parts).split() == text.split()


def test_custom_limit():
    assert split_text("aaa bbb", limit=4) == ["aaa", "bbb"]


def test_truncate():
    assert truncate("abc", 5) == "abc"
    assert truncate("abcde", 5) == "abcde"
    assert truncate("abcdefgh", 5) == "abcd…"
