from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.billing.repositories import SqlAlchemyBillingRepository
from nevo.billing.service import BillingService


def build_billing_service(
    sessions: async_sessionmaker[AsyncSession],
) -> BillingService:
    return BillingService(repository=SqlAlchemyBillingRepository(sessions))
