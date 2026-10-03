"""Naming helpers shared by private UE asset services."""

import re


def safe_id(value: str, fallback: str = "asset") -> str:
    cleaned = re.sub(
        r"[^0-9A-Za-z_]+",
        "_",
        str(value or "").strip(),
    ).strip("_").lower()
    return cleaned or fallback
