"""Offset-based pagination helper for list tools."""

from __future__ import annotations

from typing import Annotated, Generic, TypedDict, TypeVar

from pydantic import Field

T = TypeVar("T")


class PaginationEnvelope(TypedDict, Generic[T]):  # noqa: UP046
    """Fixed shape returned by :func:`paginate`."""

    items: list[T]
    total: int
    offset: int
    limit: int
    has_more: bool


def paginate(  # noqa: UP047
    items: list[T],
    offset: int = 0,
    limit: int | None = None,
    default_limit: int = 25,
    max_limit: int = 100,
) -> PaginationEnvelope[T]:
    """Slice a list and return a pagination envelope.

    Args:
        items: Full list to paginate.
        offset: Starting index (clamped to 0 if negative).
        limit: Requested page size. ``None``, ``0``, or negative uses *default_limit*.
        default_limit: Page size when *limit* is not positive.
        max_limit: Hard cap on page size.

    Returns:
        Dict with keys: ``items``, ``total``, ``offset``, ``limit``, ``has_more``.
    """
    effective_limit = min(limit if limit and limit > 0 else default_limit, max_limit)
    effective_offset = max(offset, 0)
    total = len(items)
    page = items[effective_offset : effective_offset + effective_limit]
    return {
        "items": page,
        "total": total,
        "offset": effective_offset,
        "limit": effective_limit,
        "has_more": (effective_offset + effective_limit) < total,
    }


LimitField = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Maximum number of results to return (1-100, default varies by tool).",
    ),
]


OffsetField = Annotated[
    int,
    Field(
        ge=0,
        description="Zero-based starting index for pagination.",
    ),
]
