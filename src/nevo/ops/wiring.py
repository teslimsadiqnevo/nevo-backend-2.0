from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ops.config import OpsSettings
from nevo.ops.heartbeat import HeartbeatLoop
from nevo.ops.keepalive import SelfPingLoop
from nevo.ops.repositories import SqlAlchemyHeartbeatRepository


def build_self_ping_loop(settings: OpsSettings) -> SelfPingLoop:
    health_url = (
        f"{settings.self_ping_url.rstrip('/')}/health"
        if settings.self_ping_url
        else None
    )
    return SelfPingLoop(
        health_url=health_url,
        interval_seconds=settings.self_ping_interval_seconds,
    )


def build_heartbeat_loop(
    sessions: async_sessionmaker[AsyncSession],
    settings: OpsSettings,
) -> HeartbeatLoop:
    return HeartbeatLoop(
        repository=SqlAlchemyHeartbeatRepository(sessions),
        check_interval_seconds=settings.heartbeat_check_interval_seconds,
    )
