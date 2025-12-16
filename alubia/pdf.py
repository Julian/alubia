"""
Helpers for extracting data from PDFs.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
import re
import reprlib

from attrs import field, mutable
import pymupdf  # type: ignore[reportMissingTypeStubs]

from alubia.data import Amount

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path


class NotFound(LookupError):
    """
    A pattern was not found.
    """


type Block = tuple[Any, Any, Any, Any, str, Any, Any]


@mutable(repr=False)
class IncrementalParser:
    """
    An incremental PDF parser.
    """

    _blocks: Iterator[Block] = field(converter=iter, alias="blocks")
    current: Block | None = None

    def __iter__(self):
        return self

    def __next__(self):
        self.current = block = next(self._blocks)
        return block

    def __repr__(self):
        block = "start" if self.current is None else reprlib.repr(self.current)
        return f"<{self.__class__.__name__} at {block}>"

    @classmethod
    @contextmanager
    def from_path(cls, path: Path):
        """
        Start parsing a PDF from the given path.
        """
        with pymupdf.open(path) as document:
            page = document[0]
            blocks: list[Block] = page.get_text("blocks", sort=False)  # type: ignore[reportUnknownVariableType]
            yield cls(blocks=blocks)

    def rest(self):
        """
        The remaining blocks.
        """
        return [block[4] for block in self]

    def find(self, prefix: str):
        """
        Find the next block which starts with the given string.
        """
        for _, _, _, _, content, _, _ in self:
            if content.startswith(prefix):
                return content.strip()
        raise NotFound(prefix)

    def find_range(self, start: str, end: str) -> Iterable[str]:
        """
        Find the blocks spanning between the given start and end.
        """
        for _, _, _, _, content, _, _ in self:
            if content.startswith(start):
                break
        else:
            raise NotFound(start)

        blocks: list[str] = []
        for _, _, _, _, content, _, _ in self:
            blocks.append(content)
            if content.startswith(end):
                return blocks
        raise NotFound(end)

    def extract(self, pattern: str):
        """
        Find the next block matching the given pattern, advancing forward.
        """
        for _, _, _, _, content, _, _ in self:
            match = re.search(pattern, content)
            if match:
                return match
        raise NotFound(pattern)

    def extract_amount(
        self,
        pattern: str,
        commodity: Callable[[str], Amount] = Amount.from_str,
    ):
        """
        Extract an amount using the given pattern.
        """
        match = self.extract(pattern)
        if match.lastindex != 1:
            raise ValueError(f"{pattern} does not have 1 capture group.")
        return commodity(match.group(1))
