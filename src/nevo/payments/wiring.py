from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.payments.config import PaystackSettings
from nevo.payments.paystack import PaystackClient
from nevo.payments.repositories import SqlAlchemyPaymentRepository
from nevo.payments.service import PaymentService


def build_payment_service(
    sessions: async_sessionmaker[AsyncSession],
    settings: PaystackSettings | None = None,
) -> PaymentService:
    resolved = settings or PaystackSettings()
    return PaymentService(
        repository=SqlAlchemyPaymentRepository(sessions),
        client=PaystackClient(resolved),
        settings=resolved,
    )
