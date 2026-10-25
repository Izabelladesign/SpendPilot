from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.task_parser import (
    ParserResult,
    TaskParser,
    configured_openai_client,
)

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


class TaskParseRequest(BaseModel):
    raw_task: str = Field(min_length=1)


@router.post("/parse", response_model=ParserResult)
async def parse_task(payload: TaskParseRequest):
    parser = TaskParser(configured_openai_client())
    return await parser.parse(payload.raw_task)
