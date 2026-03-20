"""Custom exceptions for the scraper layer."""


class ScraperError(Exception):
    """Base class for all scraper errors."""


class RateLimitError(ScraperError):
    """Raised when the target site returns HTTP 429 or equivalent throttle signal."""


class AuthenticationError(ScraperError):
    """Raised when LinkedIn authentication fails, cookies are expired with no credentials,
    or a 2FA / CAPTCHA challenge is encountered."""


class ParseError(ScraperError):
    """Raised when expected markup or JSON structure is absent or malformed."""
