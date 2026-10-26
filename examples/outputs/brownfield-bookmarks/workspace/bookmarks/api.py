"""HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from bookmarks.models import Bookmark, BookmarkIn, Page
from bookmarks.store import BookmarkStore

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


def _store(request: Request) -> BookmarkStore:
    return request.app.state.store


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Bookmark)
def create_bookmark(body: BookmarkIn, request: Request) -> Bookmark:
    return _store(request).add(body)


@router.get("", response_model=Page)
def list_bookmarks(request: Request, page: Annotated[int, Query(ge=1)] = 1,
                   size: Annotated[int, Query(ge=1, le=100)] = 20,
                   tag: Annotated[str | None, Query(min_length=1, max_length=50,
                                                    description="Only bookmarks with this tag (case-insensitive)")]
                   = None) -> Page:
    items, total = _store(request).list(page, size, tag)
    return Page(items=items, total=total, page=page, size=size)


@router.get("/{bookmark_id}", response_model=Bookmark)
def get_bookmark(bookmark_id: int, request: Request) -> Bookmark:
    bookmark = _store(request).get(bookmark_id)
    if bookmark is None:
        raise HTTPException(status_code=404, detail="bookmark not found")
    return bookmark


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(bookmark_id: int, request: Request) -> Response:
    if not _store(request).delete(bookmark_id):
        raise HTTPException(status_code=404, detail="bookmark not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
