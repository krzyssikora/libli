"""One hierarchy, referenced by all three consumers: the command maps each to a
CommandError, PR 3's form maps InvalidBounds to a FIELD error, and the tests
assert on these classes rather than on ValueError.

The vendor guard's ImproperlyConfigured deliberately sits OUTSIDE this
hierarchy: it signals misconfiguration, not bad input, so a caller catching
DemoKitError does not swallow it."""


class DemoKitError(Exception):
    """Base for every demo-provisioning failure."""


class InvalidLabel(DemoKitError):
    pass


class InvalidBounds(DemoKitError):
    """Carries the offending field so a form can attach the message to it."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


class InvalidFrontierPart(InvalidBounds):
    """A subclass of InvalidBounds, so PR 3's form attaches it to a FIELD like
    the other two bounds errors rather than surfacing it as a form-wide error."""

    def __init__(self, message):
        super().__init__("frontier_part", message)


class UsernameCollision(DemoKitError):
    pass


class EmptyCourse(DemoKitError):
    pass


class EmptyKit(DemoKitError):
    pass


class KitNotFound(DemoKitError):
    pass


class KitAlreadyClosed(DemoKitError):
    pass


class NamePoolExhausted(DemoKitError):
    pass


class PurgeFailed(DemoKitError):
    """Raised AFTER purge_expired has attempted every due kit, so one bad kit
    cannot strand the rest. Carries the kits that DID close, so the command can
    still report them before the non-zero exit."""

    def __init__(self, message, purged):
        self.purged = purged
        super().__init__(message)
