"""Postęp pracy: czas pracy w projekcie, pokrycie nagrania i statystyki."""

import json

import pytest

from transkryptor.document.anchors import MANUAL, SEGMENT, Anchor
from transkryptor.document.comments import Comment
from transkryptor.document.progress import (
    ProjectStats,
    covered_ranges,
    format_duration,
    project_stats,
    stats_rows,
    words_by_speaker,
)
from transkryptor.document.project import (
    SCHEMA_VERSION,
    ProjectState,
    dumps,
    loads,
    migrate,
)
from transkryptor.document.project.errors import InvalidProjectError
from transkryptor.document.speakers import (
    INFORMANT,
    RESEARCHER,
    Speaker,
    role_label,
)
from transkryptor.document.work_log import MAX_DAYS, WorkDay, WorkLog


class TestWorkLog:
    def test_add_counts_total_and_day(self) -> None:
        log = WorkLog().add(30, "2026-10-30", covered_ms=1000).add(15, "2026-10-30")
        log = log.add(5, "2026-10-31", covered_ms=4000)
        assert log.seconds == 50
        assert log.days == (
            WorkDay("2026-10-30", 45, 1000),
            WorkDay("2026-10-31", 5, 4000),
        )

    def test_start_day_keeps_first_coverage(self) -> None:
        log = WorkLog().start_day("2026-10-31", 1000).start_day("2026-10-31", 9000)
        assert log.day("2026-10-31") == WorkDay("2026-10-31", 0, 1000)

    def test_zero_seconds_change_nothing(self) -> None:
        assert WorkLog().add(0, "2026-10-31") == WorkLog()

    def test_days_are_limited(self) -> None:
        log = WorkLog()
        for number in range(MAX_DAYS + 5):
            log = log.start_day(f"d{number}", 0)
        assert len(log.days) == MAX_DAYS
        assert log.days[-1].date == f"d{MAX_DAYS + 4}"

    def test_duration_only_when_known(self) -> None:
        assert WorkLog().with_duration(0).audio_duration_ms is None
        assert WorkLog().with_duration(90_000).audio_duration_ms == 90_000


class TestProjectFile:
    def test_work_round_trip(self) -> None:
        work = WorkLog(3600, 90_000, (WorkDay("2026-10-31", 600, 12_000),))
        state = ProjectState(text="tekst", work=work)
        assert loads(dumps(state)).work == work

    def test_schema_6_project_gets_empty_work_log(self) -> None:
        data = {"schema_version": 6, "document": {"text": "ab"}}
        migrated = migrate(data)
        assert migrated["schema_version"] == SCHEMA_VERSION == 7
        assert migrated["work"] == {"seconds": 0, "days": []}
        assert "work" not in data
        assert loads(json.dumps(data)).work == WorkLog()

    @pytest.mark.parametrize(
        "work",
        [
            {"seconds": "10", "days": []},
            {"seconds": 1, "days": [{"seconds": 1}]},
            {
                "seconds": 1,
                "days": [{"date": "2026-10-31"}, {"date": "2026-10-31"}],
            },
        ],
    )
    def test_invalid_work_log_is_rejected(self, work) -> None:
        data = {"schema_version": 7, "document": {"text": ""}, "work": work}
        with pytest.raises(InvalidProjectError):
            loads(json.dumps(data))


class TestCoverage:
    def test_segments_and_gaps_with_text(self) -> None:
        text = "raz dwa\ntrzy"
        anchors = [
            Anchor(0, 7, 0, 2000, SEGMENT),
            # Między segmentami jest tylko nowa linia - luka nie jest pokryta.
            Anchor(8, 12, 3000, 4000, SEGMENT),
        ]
        assert covered_ranges(text, anchors) == ((0, 2000), (3000, 4000))

    def test_text_between_manual_timestamps_covers_the_gap(self) -> None:
        text = "[00:00] raz dwa [00:10] trzy"
        anchors = [
            Anchor(0, 0, 0, 0, MANUAL),
            Anchor(16, 16, 10_000, 10_000, MANUAL),
        ]
        assert covered_ranges(text, anchors) == ((0, 10_000),)

    def test_text_without_anchors_has_no_coverage(self) -> None:
        assert covered_ranges("tekst bez kotwic", []) == ()


class TestStats:
    def state(self) -> ProjectState:
        text = "Jak było?\nDobrze było tu."
        return ProjectState(
            text=text,
            anchors=(Anchor(0, len(text), 0, 30_000, SEGMENT),),
            verified=((0, 15_000),),
            speakers=(Speaker("B", "", RESEARCHER), Speaker("I", "Ala", INFORMANT)),
            paragraph_speakers={0: "B", 1: "I"},
            comments=(
                Comment("c1", 0, 3, "A", "", "?"),
                Comment("c2", 0, 3, "A", "", "!", resolved=True),
            ),
            work=WorkLog(
                1800, 120_000, (WorkDay("2026-10-31", 600, covered_start_ms=10_000),)
            ),
        )

    def test_project_stats(self) -> None:
        stats = project_stats(self.state(), "2026-10-31", warnings=2)
        assert stats.words == 5
        assert stats.transcribed_ms == 30_000
        assert stats.transcribed_ratio == 0.25
        assert stats.verified_ratio == 0.125
        assert stats.open_comments == 1
        assert stats.warnings == 2
        assert stats.today_seconds == 600
        assert stats.today_covered_ms == 20_000
        # 0,5 min nagrania w 0,5 h pracy - minuta na godzinę.
        assert stats.pace == pytest.approx(1.0)
        # Zostało 1,5 min nagrania → 1,5 h pracy.
        assert stats.remaining_seconds == 5400

    def test_words_by_speaker(self) -> None:
        state = self.state()
        assert words_by_speaker(state) == (
            (f"B ({role_label(RESEARCHER)})", 2),
            ("I (Ala)", 3),
        )
        plain = ProjectState(text="raz dwa")
        assert words_by_speaker(plain) == ()

    def test_unknown_duration_and_no_work(self) -> None:
        stats = ProjectStats(words=3, work_seconds=0, transcribed_ms=0, verified_ms=0)
        assert stats.transcribed_ratio is None
        assert stats.pace is None
        assert stats.remaining_seconds is None
        values = dict(stats_rows(stats))
        assert all(value == "-" for key, value in values.items() if "%" in str(value))

    def test_rows_contain_speakers(self) -> None:
        rows = dict(stats_rows(project_stats(self.state(), "2026-10-31")))
        assert rows["Przetranskrybowano"] == "25%"
        assert rows["Czas pracy"] == "0:30:00"
        assert rows["Słowa: I (Ala)"] == 3

    def test_format_duration(self) -> None:
        assert format_duration(3909) == "1:05:09"
        assert format_duration(-5) == "0:00:00"
