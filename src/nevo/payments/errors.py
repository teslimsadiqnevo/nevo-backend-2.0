class PaymentError(Exception):
    code = "payment_error"
    public_message = "The payment could not be processed."


class PaymentProviderUnavailableError(PaymentError):
    code = "payment_provider_unavailable"
    public_message = "Card payments are not configured."


class PaymentProviderRejectedError(PaymentError):
    code = "payment_provider_rejected"
    public_message = "The payment provider rejected the request."


class PaymentNotFoundError(PaymentError):
    code = "payment_not_found"
    public_message = "That payment could not be found."


class InvoiceNotPayableError(PaymentError):
    code = "invoice_not_payable"
    public_message = "That invoice is not awaiting payment."


class MissingBillingContactError(PaymentError):
    code = "missing_billing_contact"
    public_message = "Add a billing contact email before starting a payment."


class NoReusablePaymentMethodError(PaymentError):
    code = "no_reusable_payment_method"
    public_message = "No saved payment method is available to charge."


class InvalidWebhookSignatureError(PaymentError):
    code = "invalid_webhook_signature"
    public_message = "The webhook signature was not valid."
