"""app-a: uses pydantic, tested with pytest 7."""

import pydantic

from common import user_agent


class Greeting(pydantic.BaseModel):
    message: str


def greet(name: str) -> Greeting:
    return Greeting(message=f"hello {name} from {user_agent()}")
