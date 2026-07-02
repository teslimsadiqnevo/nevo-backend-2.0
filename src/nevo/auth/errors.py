class AuthError(Exception):
    code = "authentication_failed"
    public_message = "Unable to authenticate with the supplied credentials."


class InvalidCredentialsError(AuthError):
    pass


class RateLimitExceededError(AuthError):
    code = "too_many_attempts"
    public_message = "Too many attempts. Please wait before trying again."


class InvalidSessionError(AuthError):
    code = "invalid_session"
    public_message = "Your session is no longer valid. Please sign in again."


class SessionExpiredError(InvalidSessionError):
    code = "session_expired"
    public_message = "Your session has expired. Please sign in again."


class SessionReplacedError(InvalidSessionError):
    code = "session_replaced"
    public_message = (
        "You logged in on another device, your progress has been saved."
    )
