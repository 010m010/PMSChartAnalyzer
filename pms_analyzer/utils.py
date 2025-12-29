from __future__ import annotations

import re
from typing import Tuple


def difficulty_sort_key(value: str) -> Tuple[int, float | str, str]:
    """
    Sort difficulties by their numeric value when present, otherwise by label.

    Returns a tuple so that numeric difficulties are ordered before non-numeric
    labels, and ties fall back to the original string.
    """

    digits = re.findall(r"[0-9]+(?:\.[0-9]+)?", value)
    if digits:
        try:
            return (0, float(digits[0]), value)
        except ValueError:
            pass
    return (1, value, value)


__all__ = ["difficulty_sort_key"]
