"""Demo-only, Shariah-gated research desk.

Derivative of HyperGrok Trading Desk (copyright (c) 2026 Galleon Labs, MIT).
See NOTICE.md. This package never enables network orders.
"""

NETWORK_ORDERS_ALLOWED = False
__version__ = "0.0.0-demo"


def network_orders_allowed() -> bool:
    """Hard switch. Tests depend on this staying false."""
    return NETWORK_ORDERS_ALLOWED
