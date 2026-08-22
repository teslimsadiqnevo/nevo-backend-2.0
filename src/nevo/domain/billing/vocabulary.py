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
