from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    location: Optional[str] = None
    hint: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.location:
            data["location"] = self.location
        if self.hint:
            data["hint"] = self.hint
        return data

    def format(self) -> str:
        location = f"\n  at {self.location}" if self.location else ""
        hint = f"\n  hint: {self.hint}" if self.hint else ""
        return f"{self.severity}[{self.code}]: {self.message}{location}{hint}"


class Diagnostics:
    def __init__(self, items: Optional[Iterable[Diagnostic]] = None) -> None:
        self.items: List[Diagnostic] = list(items or [])

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        location: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> None:
        self.items.append(Diagnostic(severity, code, message, location, hint))

    def error(self, code: str, message: str, location: Optional[str] = None, hint: Optional[str] = None) -> None:
        self.add("error", code, message, location, hint)

    def warning(self, code: str, message: str, location: Optional[str] = None, hint: Optional[str] = None) -> None:
        self.add("warning", code, message, location, hint)

    def extend(self, items: Iterable[Diagnostic]) -> None:
        self.items.extend(items)

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "error" for item in self.items)

    def to_list(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.items]

    def format(self) -> str:
        if not self.items:
            return "No diagnostics."
        return "\n".join(item.format() for item in self.items)
