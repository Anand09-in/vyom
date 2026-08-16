"""POST /feedback — thumbs up/down on a query response.

Rating -1 = not helpful, 1 = helpful.
These ratings feed back into the golden eval set over time:
negative-rated queries become new test cases in golden.jsonl.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from vyom.api.auth import get_current_user
from vyom.api.deps import get_repo

router = APIRouter(prefix="/feedback", tags=["feedback"], dependencies=[Depends(get_current_user)])


class FeedbackRequest(BaseModel):
    query_log_id: int
    rating: int = Field(..., description="1 = helpful, -1 = not helpful")
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    status: str


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    req: FeedbackRequest,
    repo=Depends(get_repo),
) -> FeedbackResponse:
    await repo.log_feedback(req.query_log_id, req.rating, req.comment)
    return FeedbackResponse(status="recorded")