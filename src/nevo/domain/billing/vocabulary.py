from enum import StrEnum


class SubscriptionTier(StrEnum):
    BOUTIQUE = "boutique"
    MID_MARKET = "mid_market"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class InvoiceStatus(StrEnum):
    PAID = "paid"
    PENDING = "pending"
    OVERDUE = "overdue"


class PaymentMethodType(StrEnum):
    CARD = "card"
    DIRECT_DEBIT = "direct_debit"


class PricingCurrency(StrEnum):
    USD = "USD"
    NGN = "NGN"
    GBP = "GBP"


class ContractStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    PENDING_RENEWAL = "pending_renewal"


class PaymentSource(StrEnum):
    DIRECT = "direct"
    STERLING = "sterling"
    PARTNER = "partner"


class PaymentTransactionStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"


class WebhookEventStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"
