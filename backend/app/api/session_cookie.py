"""Browser session transport; credential rules remain in identity.auth."""

from fastapi import Request, Response

from app.core.config import settings

SESSION_COOKIE_NAME = "printstash_session"


def extract_access_token(
    request: Request, bearer_token: str | None = None
) -> str | None:
    """Canonical bearer/cookie token extraction for auth and audit paths."""
    if bearer_token:
        return bearer_token
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return request.cookies.get(SESSION_COOKIE_NAME)


def set_session_cookie(
    response: Response,
    token: str,
    *,
    max_age: int | None = None,
    secure: bool | None = None,
) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=bool(settings.session_cookie_secure if secure is None else secure),
        samesite="strict",
        path="/",
        max_age=max_age,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite="strict",
        path="/",
    )
