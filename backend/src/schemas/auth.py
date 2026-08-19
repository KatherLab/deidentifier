"""Contracts for the optional sign-in gate.

Deliberately thin: the app has no user records, no roles and no permissions.
`AuthUser` exists so the header can say who is signed in, and for nothing else.
"""

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    name: str = ""
    email: str = ""


class SessionResponse(BaseModel):
    #: False when no gate is configured — then `authenticated` is always true
    #: and the frontend behaves exactly as it did before OIDC existed.
    enabled: bool
    authenticated: bool
    user: AuthUser | None = None
    #: Where the browser goes to start a sign-in; empty when the gate is off.
    login_url: str = ""


class LogoutResponse(BaseModel):
    #: Set when the provider should end its own session too
    #: (OIDC_END_SESSION); the browser navigates there after signing out here.
    redirect_url: str | None = Field(default=None)
