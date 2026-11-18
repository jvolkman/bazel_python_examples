"""app-b: uses attrs, tested with pytest 8."""

import attrs

from common import user_agent


@attrs.frozen
class Greeting:
    message: str


def greet(name: str) -> Greeting:
    return Greeting(message=f"hi {name} from {user_agent()}")
