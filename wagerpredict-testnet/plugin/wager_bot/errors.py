from __future__ import annotations


class SoftError(RuntimeError):
    """Expected per-account failure with a stable public code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BlockedError(SoftError):
    pass
