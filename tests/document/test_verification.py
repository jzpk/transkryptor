"""Postęp weryfikacji: sprawdzone zakresy nagrania (bez Qt)."""

import pytest

from transkryptor.document import verification as v
from transkryptor.document.project import ProjectState, dumps, loads


class TestRanges:
    def test_normalized_sorts_merges_and_drops_empty(self) -> None:
        assert v.normalized(
            [(5000, 9000), (0, 1000), (1000, 2000), (8000, 12_000)]
        ) == (
            (0, 2000),
            (5000, 12_000),
        )
        assert v.normalized([(3000, 3000), (-500, 200)]) == ((0, 200),)

    def test_add_and_remove(self) -> None:
        ranges = v.add((), 0, 10_000)
        assert v.remove(ranges, 2000, 4000) == ((0, 2000), (4000, 10_000))
        assert v.remove(ranges, 0, 20_000) == ()
        assert v.remove(ranges, 20_000, 30_000) == ranges

    def test_mark_until_fills_gap_before_position(self) -> None:
        assert v.mark_until((), 30_000) == ((0, 30_000),)
        ranges = ((0, 10_000), (40_000, 50_000))
        assert v.mark_until(ranges, 25_000) == ((0, 25_000), (40_000, 50_000))
        assert v.mark_until(ranges, 60_000) == ((0, 10_000), (40_000, 60_000))
        # Pozycja w sprawdzonym fragmencie niczego nie zmienia.
        assert v.mark_until(ranges, 45_000) == ranges

    def test_coverage(self) -> None:
        ranges = ((0, 30_000), (60_000, 90_000))
        assert v.covered_ms(ranges, 120_000) == 60_000
        assert v.coverage(ranges, 120_000) == pytest.approx(0.5)
        # Zakres dłuższy niż nagranie jest obcinany.
        assert v.coverage(((0, 200_000),), 120_000) == 1.0
        assert v.coverage(ranges, 0) == 0.0

    def test_gaps_skip_slivers(self) -> None:
        ranges = ((0, 30_000), (30_500, 60_000))
        assert v.gaps(ranges, 60_400) == []
        assert v.gaps(ranges, 90_000) == [(60_000, 90_000)]
        assert v.gaps((), 5000) == [(0, 5000)]

    def test_next_gap(self) -> None:
        ranges = ((0, 30_000), (60_000, 90_000))
        duration = 120_000
        # W luce - jej początek; w sprawdzonym - następna luka.
        assert v.next_gap(ranges, 45_000, duration) == (30_000, False)
        assert v.next_gap(ranges, 10_000, duration) == (30_000, False)
        assert v.next_gap(ranges, 70_000, duration) == (90_000, False)
        assert v.next_gap(((30_000, 120_000),), 50_000, duration) == (0, True)
        assert v.next_gap(((0, 120_000),), 0, duration) is None

    def test_overlaps_and_contains(self) -> None:
        ranges = ((1000, 2000),)
        assert v.overlaps(ranges, 1500, 3000)
        assert not v.overlaps(ranges, 2000, 3000)
        assert v.contains(ranges, 1000)
        assert not v.contains(ranges, 2000)


class TestProject:
    def test_ranges_survive_project_file(self) -> None:
        state = ProjectState(text="x", verified=((0, 1000), (5000, 9000)))
        assert loads(dumps(state)).verified == ((0, 1000), (5000, 9000))

    def test_older_project_has_no_ranges(self) -> None:
        raw = dumps(ProjectState(text="x")).replace('"verified": []', '"x": 1')
        assert loads(raw).verified == ()

    def test_invalid_range_is_rejected(self) -> None:
        from transkryptor.errors import ProjectError

        raw = dumps(ProjectState(text="x")).replace(
            '"verified": []', '"verified": [[5, 1]]'
        )
        with pytest.raises(ProjectError):
            loads(raw)
