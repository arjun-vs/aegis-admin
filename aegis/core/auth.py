from fastapi import Request
from typing import Any, Optional


class AuthBackend:
    """
    Base class for Aegis authentication backends.

    To integrate Aegis with your existing FastAPI project's auth system,
    subclass this and implement the two methods below.

    Your implementation controls:
      - How the current user is resolved from a request (cookie, JWT, session, OAuth2, etc.)
      - Whether that user is considered an admin and allowed into the admin panel

    Examples
    --------
    **Cookie / session-based (e.g. using itsdangerous or your own session middleware):**

        class SessionAuthBackend(AuthBackend):
            async def get_current_user(self, request: Request):
                user_id = request.session.get("user_id")  # requires SessionMiddleware
                if not user_id:
                    return None
                return await db.get_user(user_id)

            async def is_authenticated(self, user) -> bool:
                return user is not None and user.is_admin

    **JWT Bearer token (e.g. FastAPI's OAuth2PasswordBearer):**

        class JWTAuthBackend(AuthBackend):
            async def get_current_user(self, request: Request):
                token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                if not token:
                    token = request.cookies.get("access_token", "")
                try:
                    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
                    return await db.get_user(payload["sub"])
                except Exception:
                    return None

            async def is_authenticated(self, user) -> bool:
                return user is not None and "admin" in user.roles

    **Reusing FastAPI's existing dependency (e.g. get_current_user from your auth module):**

        from myapp.auth import verify_token

        class AppAuthBackend(AuthBackend):
            async def get_current_user(self, request: Request):
                token = request.cookies.get("session_token")
                return await verify_token(token)   # your existing function

            async def is_authenticated(self, user) -> bool:
                return user is not None and user.role in ("admin", "superuser")

    The resolved user object is stored on ``request.state.aegis_user`` and is
    available to any downstream code within the request lifecycle.
    """

    async def get_current_user(self, request: Request) -> Optional[Any]:
        """
        Resolve the current user from the request.

        Return the user object (any type your app uses — ORM model, dict, Pydantic
        schema, etc.) or ``None`` if no authenticated user can be identified.
        """
        raise NotImplementedError

    async def is_authenticated(self, user: Optional[Any]) -> bool:
        """
        Decide whether ``user`` is allowed to access the Aegis admin panel.

        Return ``True`` to grant access, ``False`` to redirect to the login URL.
        This is where you enforce role/permission checks (e.g. ``user.is_admin``).
        """
        raise NotImplementedError


class AllowAllAuthBackend(AuthBackend):
    """Auth backend that always authenticates. Useful for testing."""

    async def get_current_user(self, request: Request) -> dict:
        return {"username": "admin"}

    async def is_authenticated(self, user) -> bool:
        return True


class RejectAllAuthBackend(AuthBackend):
    """Auth backend that never authenticates. Useful for testing."""

    async def get_current_user(self, request: Request) -> None:
        return None

    async def is_authenticated(self, user) -> bool:
        return False
