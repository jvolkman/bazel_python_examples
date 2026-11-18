"""Code shared by app-a and app-b."""

import requests


def user_agent() -> str:
    return f"monorepo (requests {requests.__version__})"
