class PartnerInquiryError(Exception):
    code = "partner_inquiry_error"
    public_message = "The inquiry could not be submitted."


class InvalidPartnerContactError(PartnerInquiryError):
    code = "invalid_partner_contact"
    public_message = "Enter a valid email address or phone number."
