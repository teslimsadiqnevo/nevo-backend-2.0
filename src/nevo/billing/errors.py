class BillingError(Exception):
    code = "billing_error"
    public_message = "Billing is temporarily unavailable."


class BillingSchoolContextError(BillingError):
    code = "missing_school_context"
    public_message = "A school context is required for billing."


class BillingNotFoundError(BillingError):
    code = "billing_not_found"
    public_message = "Billing details were not found for this school."


class BillingPaymentMethodError(BillingError):
    code = "invalid_payment_method"
    public_message = "Payment method details could not be saved."
