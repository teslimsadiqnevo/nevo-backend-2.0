from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nevo.ai_gateway.compliance import ZeroTagCompliancePolicy
from nevo.ai_gateway.service import AiGatewayService
from nevo.exports.repositories import SqlAlchemyIepExportRepository
from nevo.exports.service import IepExportService


def build_iep_export_service(
    sessions: async_sessionmaker[AsyncSession],
    ai_gateway: AiGatewayService,
) -> IepExportService:
    return IepExportService(
        repository=SqlAlchemyIepExportRepository(sessions),
        gateway=ai_gateway,
        compliance=ZeroTagCompliancePolicy(),
    )
