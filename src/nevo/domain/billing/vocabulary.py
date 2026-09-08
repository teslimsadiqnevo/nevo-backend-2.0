from enum import StrEnum


class PricingPlan(StrEnum):
    """How a school buys Nevo. Pricing is per student on both."""

    ANNUAL = "annual"
    PER_TERM = "per_term"


class RateType(StrEnum):
    """Which rate card a school is held to."""

    FOUNDING_PARTNER = "founding_partner"
    STANDARD = "standard"


class AccessWindow(StrEnum):
    """What the school's fee buys access to.

    Annual covers the calendar including breaks; per-term covers only the
    school's own session, so it is a fact the cost sheet has to state.
    """

    YEAR_ROUND = "year_round"
    SCHOOL_SESSION = "school_session"


class SubscriptionTier(StrEnum):
    """Superseded by per-student pricing. Retained only to read old rows."""

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
