class MMError(Exception):
    """Base error type for this prototype."""


class ValidationError(MMError):
    pass


class CollisionError(MMError):
    pass


class RegistryError(MMError):
    pass


class ConfigError(MMError):
    pass
