from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live(request: Request) -> dict[str, str]:
    return {"status": "live", "server_time_utc": request.app.state.clock.now().isoformat()}


@router.get("/health/ready")
async def ready(request: Request) -> dict[str, str]:
    try:
        async with request.app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail={"code": "DATABASE_UNAVAILABLE"}) from None
    return {"status": "ready", "server_time_utc": request.app.state.clock.now().isoformat()}
