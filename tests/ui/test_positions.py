"""Testy przeliczania pozycji Python (punkty kodowe) ↔ Qt (UTF-16)."""

import pytest

from transkryptor.ui.positions import PositionMap, utf16_len


def test_bmp_text_maps_identically() -> None:
    positions = PositionMap("bendzie uóna")
    assert [positions.to_qt(i) for i in range(13)] == list(range(13))
    assert [positions.to_py(i) for i in range(13)] == list(range(13))


@pytest.mark.parametrize(
    ("text", "py", "qt"),
    [
        ("😀 bendzie", 0, 0),
        ("😀 bendzie", 1, 2),
        ("😀 bendzie", 4, 5),
        ("ab😀cd", 2, 2),
        ("ab😀cd", 3, 4),
        ("😀𝑎x", 2, 4),
        ("😀𝑎x", 3, 5),
    ],
)
def test_astral_characters_shift_positions(text, py, qt) -> None:
    positions = PositionMap(text)
    assert positions.to_qt(py) == qt
    assert positions.to_py(qt) == py


def test_position_inside_surrogate_pair_points_to_character_start() -> None:
    positions = PositionMap("a😀b")
    assert positions.to_py(2) == 1


def test_utf16_len() -> None:
    assert utf16_len("abc") == 3
    assert utf16_len("😀 bendzie") == 10
