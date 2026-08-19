# Single sign-on (OIDC)

The anonymizer ships with **no sign-in at all**. That is the intended default:
it is built to run inside the hospital network behind whatever authenticating
proxy you already operate, and it stores nothing, so there is no account to
protect.

Where that proxy does not exist — a departmental server, a pilot on a VM, a
deployment your identity team would rather see integrated directly — the app
can require a sign-in at your **OpenID Connect** provider itself. Keycloak,
Entra ID (Azure AD), Authentik, Okta, Google Workspace and anything else that
speaks OIDC discovery all work.

!!! note "A gate, not an authorisation model"
    Everyone who can sign in gets the same, whole application. There are no
    roles, no per-user settings and no user records — signing in decides
    *whether* you get in and nothing else. Restricting *who* may sign in is
    done at the provider, by only assigning the application to the group that
    should have it.

## What it protects

With `OIDC_ENABLED=true`, every route under `/api/` requires a valid session —
anonymizing, exporting, page rendering, status, the cached-result routes, all
of it. The exceptions are deliberate and short:

- `/api/v1/auth/*` — the sign-in routes themselves.
- `/health/live` and `/health/ready` — a readiness probe has no browser and no
  cookie.
- The static frontend (HTML, JS, CSS). It is served by nginx and contains no
  patient data; someone who loads it without a session sees the sign-in screen
  and nothing else.

## Setting it up

### 1. Register a client at your provider

Create a **confidential** client (one with a secret) using the **authorization
code** flow with **PKCE**, and register exactly one redirect URI:

```
https://<your APP_PUBLIC_URL>/api/v1/auth/callback
```

A mismatch here is the single most common cause of a failed sign-in — the URL
must be the one the browser actually uses, including scheme and any port.

If your provider also wants a post-logout redirect URI (only relevant with
`OIDC_END_SESSION=true`), register `APP_PUBLIC_URL` itself.

### 2. Configure the app

In `.env`:

```bash
OIDC_ENABLED=true
OIDC_ISSUER=https://keycloak.klinik.de/realms/intranet
OIDC_CLIENT_ID=deidentifier
OIDC_CLIENT_SECRET=…
OIDC_SESSION_SECRET=…            # openssl rand -hex 32
APP_PUBLIC_URL=https://deid.klinik.de
```

`OIDC_ISSUER` is the base URL, **not** the discovery URL: the app appends
`/.well-known/openid-configuration` itself. Use the value the provider reports
as its `issuer` — for Keycloak that is
`https://host/realms/<realm>`, for Entra ID
`https://login.microsoftonline.com/<tenant-id>/v2.0`.

Every optional knob (`OIDC_SCOPES`, `OIDC_SESSION_MINUTES`,
`OIDC_END_SESSION`, `OIDC_HTTP_TIMEOUT_SECONDS`) is in the
[configuration reference](configuration.md#sign-in-oidc).

### 3. Restart and check the log

```
docker compose up -d
docker compose logs backend | head
```

A half-configured gate **refuses to start** and says what is missing:

```
Refusing to start: OIDC_ENABLED is true but OIDC_CLIENT_SECRET,
APP_PUBLIC_URL are not set
```

That is on purpose. An access gate that silently does not gate is worse than
one that never came up.

You should also see `startup … auth=oidc` in the log. If `APP_PUBLIC_URL` is
not `https://`, a warning follows it: the session cookie cannot be marked
`Secure` over plain HTTP, so anything on the path can read it. Terminate TLS in
front of the app.

### Trying it in development

The Vite dev server proxies `/api` to the backend, so point `APP_PUBLIC_URL` at
the dev server rather than at the backend port:

```bash
APP_PUBLIC_URL=http://localhost:3000
```

and register `http://localhost:3000/api/v1/auth/callback` at the provider. The
startup warning about a non-`https` cookie is expected here.

## What signing in looks like

1. The app shows a sign-in screen instead of the drop zone.
2. **Anmelden** sends the browser to your provider (a full page navigation —
   your provider owns the tab, including any second factor).
3. The provider returns to `/api/v1/auth/callback`; the app verifies the
   response and sets a session cookie.
4. The header shows the signed-in name, with **Abmelden** behind it.

The name and email in the header come from the provider's `name`/`email`
claims and are used for that display only. Nothing is stored — refresh the
page and they are read from the cookie again.

### When something goes wrong

A failed sign-in returns to the app with a message rather than an API error
page. What the messages mean:

| On screen | Cause | Where to look |
|---|---|---|
| The sign-in was cancelled | The user declined at the provider | Nothing to fix |
| The sign-in expired or could not be matched | More than 10 minutes between starting and finishing, or the login was started in a different browser/tab-session | Just sign in again |
| The sign-in service cannot be reached | Discovery failed | `OIDC_ISSUER`, network path from the backend container to the provider |
| The sign-in could not be completed | The token exchange was rejected | `OIDC_CLIENT_SECRET`, and whether the redirect URI matches exactly |
| The response could not be verified | The id_token failed signature, issuer, audience or nonce checks | `OIDC_ISSUER` vs. the provider's actual `iss`, and `OIDC_CLIENT_ID` |

The backend log carries the matching `oidc_login_failed reason=…` line. It
never contains the provider's raw response — those bodies can echo the client
secret back.

## How the session works

- The session is a **signed cookie**, `HttpOnly` + `SameSite=Lax` + `Secure`
  (over https), scoped to `/api`. There is no server-side session store, so
  restarts and multiple workers are not a problem.
- Its lifetime is **absolute** (`OIDC_SESSION_MINUTES`, 8 hours by default) and
  does not renew on activity — the same rule the
  [result cache](../DATA_RETENTION.md) follows.
- When it runs out mid-review, the next request returns 401 and the sign-in
  screen comes back with "Your session has expired". The result cache is
  unaffected; after signing in again the document is re-submitted from the
  browser as usual.
- Rotating `OIDC_SESSION_SECRET` invalidates every session immediately. That is
  the way to sign everybody out.
- **Sign-out** clears the cookie and reloads the page, which is also what
  clears the document currently open from browser memory. With
  `OIDC_END_SESSION=true` the browser then continues to the provider's own
  sign-out.

## What the app sends to the provider

Only what OIDC requires: the client id, the redirect URI, the requested scopes,
a PKCE challenge and a nonce. **No document content, no file name and no
result ever reaches the identity provider** — it is contacted only during
sign-in, never during processing. See [Data flow](../DATA_FLOW.md).
