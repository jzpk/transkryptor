"""Klik i przeciągnięcie na osi czasu (fala, spektrogram).

``DragSelection`` rozróżnia klik (przewinięcie nagrania) od przeciągnięcia
(nowa pętla A-B) i podaje bieżące zaznaczenie do narysowania. Widżet
przekazuje pozycje myszy w pikselach i funkcję ``ms_at`` swojej osi.
"""

from __future__ import annotations

from collections.abc import Callable

# Przeciągnięcie krótsze niż tyle pikseli to klik (przewinięcie).
DRAG_THRESHOLD_PX = 4

SEEK = "seek"
LOOP = "loop"


class DragSelection:
    """Stan przeciągania myszą po osi czasu."""

    def __init__(self, ms_at: Callable[[float], int]) -> None:
        self._ms_at = ms_at
        self._press_x: float | None = None
        self._drag_x: float | None = None

    @property
    def dragging(self) -> bool:
        return self._drag_x is not None

    def press(self, x: float) -> None:
        self._press_x = x
        self._drag_x = None

    def move(self, x: float) -> bool:
        """True - zaznaczenie się zmieniło (widżet się odświeża)."""
        if self._press_x is None:
            return False
        if self._drag_x is not None or abs(x - self._press_x) > DRAG_THRESHOLD_PX:
            self._drag_x = x
            return True
        return False

    def selection(self) -> tuple[int, int] | None:
        if self._press_x is None or self._drag_x is None:
            return None
        a, b = sorted((self._ms_at(self._press_x), self._ms_at(self._drag_x)))
        return (a, b) if b > a else None

    def release(self) -> tuple[str, int, int] | None:
        """Wynik: ``(SEEK, ms, ms)``, ``(LOOP, początek, koniec)`` albo None."""
        if self._press_x is None:
            return None
        selection = self.selection()
        press, dragged = self._press_x, self.dragging
        self._press_x = self._drag_x = None
        if selection is not None:
            return LOOP, *selection
        if dragged:
            return None
        position = self._ms_at(press)
        return SEEK, position, position
