"""Testy odczytu zasobów komputera dla ASR."""

import sys
import types

from transkryptor.asr import system


def test_total_memory_is_positive_or_unknown() -> None:
    memory = system.total_memory_bytes()
    assert memory is None or memory > 0


def test_cuda_device_count_without_ctranslate2(monkeypatch) -> None:
    broken = types.ModuleType("ctranslate2")
    monkeypatch.setitem(sys.modules, "ctranslate2", broken)
    assert system.cuda_device_count() == 0


def test_cuda_device_count_reads_ctranslate2(monkeypatch) -> None:
    fake = types.ModuleType("ctranslate2")
    fake.get_cuda_device_count = lambda: 2  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    assert system.cuda_device_count() == 2
