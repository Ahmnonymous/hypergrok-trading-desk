"""Errors for the demo desk. Gate results are values, not exceptions."""


class DeskError(Exception):
    """Base error for programmer or configuration mistakes."""


class ConfigError(DeskError):
    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


class DemoOnlyError(DeskError):
    """Raised when a path could leave the local simulator."""


class MalformedProposal(DeskError):
    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))
