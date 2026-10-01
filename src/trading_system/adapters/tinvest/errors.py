class TInvestClientError(RuntimeError):
    """Base error for T-Invest Python SDK / gRPC access."""


class TInvestAuthenticationError(TInvestClientError):
    """Raised when an API token is not configured."""


class TInvestResponseError(TInvestClientError):
    """Raised when a T-Invest SDK request fails or returns invalid data."""
