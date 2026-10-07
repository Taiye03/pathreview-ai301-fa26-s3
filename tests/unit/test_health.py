"""Regression tests for the health route's database probe."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routes.health import health_check


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reachable_database_reports_healthy():
    """Report a reachable database as healthy using a real SQLAlchemy session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1

            # Prevent external Redis connections; its status is outside issue #61.
            with patch("redis.Redis", side_effect=ConnectionError("Redis unavailable")):
                try:
                    body = await health_check(db=session)
                except HTTPException as exc:
                    body = exc.detail

            assert body["dependencies"]["postgres"] == "healthy"
    finally:
        await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_database_failure_reports_unhealthy():
    """Keep database failures unhealthy and return service unavailable."""
    session = Mock()
    session.execute = AsyncMock(side_effect=ConnectionError("Database unavailable"))

    with (
        patch("redis.Redis", side_effect=ConnectionError("Redis unavailable")),
        pytest.raises(HTTPException) as caught,
    ):
        await health_check(db=session)

    assert caught.value.status_code == 503
    assert caught.value.detail["dependencies"]["postgres"] == "unhealthy"
    assert caught.value.detail["status"] == "unhealthy"
    session.execute.assert_awaited_once()
