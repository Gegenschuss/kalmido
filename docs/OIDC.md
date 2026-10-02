# Single sign-on with OpenID Connect

Kalmido logs in with any OpenID Connect provider and needs no plugin:

- Authorization Code flow with PKCE (S256), state and nonce.
- The ID token is checked against the provider's keys. RSA, RSA-PSS, ECDSA and Ed25519 are accepted; `none` and HMAC never are.

A "Log in with …" button appears next to the password login. Passwords, passkeys and two-factor keep working for accounts that have them.

## Setting it up

**Redirect URI** to register at the provider (shown with a Copy button in the settings):

```
https://<your Kalmido address>/api/auth/oidc/callback
```

It is built from `PUBLIC_URL`, so set that first.

You can set the provider up in **Settings › Administration › Sign-in › Set up the provider**, or with environment variables. The two can be mixed: a variable that is set **always wins** for its field, and the settings show that field locked. The client secret entered in the settings is stored encrypted with `KALMIDO_SECRET_KEY` (32 random bytes, base64). Without that key, the secret can only come from the environment.

| Setting | Variable | Default | Meaning |
| --- | --- | --- | --- |
| Provider | `KALMIDO_OIDC_ISSUER` | – | Issuer URL (its `/.well-known/openid-configuration` is fetched). |
| Client ID | `KALMIDO_OIDC_CLIENT_ID` | – | Provider and client ID together switch the login on. |
| Client secret | `KALMIDO_OIDC_CLIENT_SECRET` | – | Empty = public client (PKCE only). |
| Scopes | `KALMIDO_OIDC_SCOPES` | `openid profile email` | Add `groups` where the provider needs it for group claims. |
| User name claim | `KALMIDO_OIDC_USERNAME_CLAIM` | `preferred_username` | Links the first login to the Kalmido user with that name. |
| Groups claim | `KALMIDO_OIDC_GROUPS_CLAIM` | `groups` | A list or a comma-separated string. |
| Required group | `KALMIDO_OIDC_REQUIRED_GROUP` | – | Only members may log in. |
| Admin group | `KALMIDO_OIDC_ADMIN_GROUP` | – | Members become admins; leaving the group removes admin rights. |
| Admin e-mail domains | `KALMIDO_OIDC_ADMIN_DOMAINS` | – | Comma-separated. A **verified** e-mail of one of these domains makes the person an admin, like the admin group, and it works together with the group. |
| Button label | `KALMIDO_OIDC_BUTTON_LABEL` | `OpenID Connect` | The text on the login button. |
| – | `KALMIDO_OIDC_ALLOW_HOSTS` | – | Internal provider hosts (`host` or `host:port`). Kalmido only talks to public addresses unless a host is listed here, or in the internal hosts of the calendar subscriptions (Settings › Administration). |

**Admin rights.** When an admin group or admin domains are set up, each OIDC login sets the admin flag: admin if either rule matches, otherwise not. The last active admin is never demoted.

**Check provider** in the settings fetches the discovery document and the signing keys right away and shows the result.

### Who may log in

- An account linked to the provider's subject (`issuer|sub`) logs in directly.
- Otherwise the **first** login links one existing account: the one whose user name equals the user name claim, or the one whose e-mail equals the **verified** e-mail claim (`email_verified: true`; for Microsoft Entra also `xms_edov`). Accounts are never linked any other way.
- Nobody matches: "no account". The exception is when **Create accounts on the first OIDC login** is on, in which case the person gets a new account. When the user name claim is not a valid Kalmido user name (Google sends none, Entra sends `anna@corp.example`), the new account is named after the local part of the verified e-mail. That name is used only for creating, never for matching an existing account.
- Unlink an account under Settings › Administration › Users › edit. The next login links it again.

Calendar apps (CalDAV) do not use OIDC: every person creates an app password (see [CALDAV.md](CALDAV.md)).

## Provider guides

The examples below use `https://kalmido.example.com`. Replace it with your `PUBLIC_URL`.

### Authentik

1. **Applications › Providers › Create › OAuth2/OpenID Provider.**
   - Client type: Confidential.
   - Redirect URIs (strict): `https://kalmido.example.com/api/auth/oidc/callback`.
   - **Signing key:** pick a certificate, for example the self-signed one. Without it Authentik signs with HS256, which Kalmido refuses.
2. **Applications › Create**, using this provider. The slug, for example `kalmido`, is part of the issuer.
3. Kalmido:
   - Provider `https://authentik.example.com/application/o/kalmido/` (with the trailing slash, exactly as shown in the provider's "OpenID Configuration Issuer").
   - The client ID and secret from the provider.
4. Groups are in the `profile` scope as `groups`, so set the required or admin group by group name.

### Keycloak

1. **Clients › Create client.**
   - OpenID Connect, client ID `kalmido`.
   - Client authentication **on**, Standard flow **on**, Direct access grants off.
   - Valid redirect URIs: `https://kalmido.example.com/api/auth/oidc/callback`.
   - Optionally, Advanced › Proof Key for Code Exchange: S256.
2. Credentials tab: copy the client secret.
3. For groups: **Client scopes › kalmido-dedicated › Add mapper › By configuration › Group Membership**.
   - Token claim name `groups`.
   - Full group path **off**.
   - Add to ID token and userinfo **on**.
4. Kalmido: provider `https://keycloak.example.com/realms/<realm>`, the client ID and the secret. The user name claim stays `preferred_username`.

### Authelia

Authelia 4.38 and newer, `configuration.yml`:

```yaml
identity_providers:
  oidc:
    # hmac_secret + jwks as in the Authelia docs
    clients:
      - client_id: kalmido
        client_name: Kalmido
        client_secret: '$pbkdf2-sha512$310000$...'   # authelia crypto hash generate pbkdf2 --variant sha512
        public: false
        authorization_policy: two_factor
        require_pkce: true
        pkce_challenge_method: S256
        redirect_uris:
          - https://kalmido.example.com/api/auth/oidc/callback
        scopes: [openid, profile, email, groups]
        response_types: [code]
        grant_types: [authorization_code]
        token_endpoint_auth_method: client_secret_basic
```

Kalmido settings:

- Provider `https://auth.example.com` (Authelia's own address).
- Client ID `kalmido`, and the **plain** secret (Authelia stores only its hash).
- Scopes `openid profile email groups`.

Newer Authelia versions put user name, e-mail and groups only into the userinfo answer. Kalmido reads userinfo, so this works as is.

If Kalmido sits behind Authelia's forward auth as well, the paths `/api/auth/oidc/*` stay behind it. That is fine: the browser is logged in there already. Calendar apps need `/dav` past the gate (see [CALDAV.md](CALDAV.md)).

### PocketID

1. **Administration › OIDC Clients › Add OIDC Client.**
   - Name Kalmido.
   - Callback URL `https://kalmido.example.com/api/auth/oidc/callback`.
   - PKCE on.
2. Copy the client ID and secret, which are shown once.
3. Kalmido: provider `https://id.example.com` (PocketID's address), the client ID and the secret.
4. For groups, add `groups` to the scopes (`openid profile email groups`). User groups are sent as `groups`.
5. The user name claim stays `preferred_username`.

PocketID logs in with passkeys only, so Kalmido accounts that use it need no password at all.

### Google Workspace

1. Google Cloud console › **APIs & Services › OAuth consent screen**: user type **Internal**, so that only your Workspace accounts get through.
2. **Credentials › Create credentials › OAuth client ID.**
   - Type Web application.
   - Authorized redirect URI `https://kalmido.example.com/api/auth/oidc/callback`.
3. Kalmido:
   - Provider `https://accounts.google.com`.
   - The client ID and secret.
   - Scopes `openid profile email`.
4. Google sends no user name and no groups:
   - Create the Kalmido users with their Workspace e-mail; the first login links them by the verified e-mail.
   - Or switch on "Create accounts on the first OIDC login". The account is named after the e-mail's local part.
   - For admins, use **Admin e-mail domains** with your Workspace domain. This only makes sense together with the Internal consent screen, because with "External" any Google account could log in.

### Microsoft Entra ID

1. **Entra admin center › App registrations › New registration.**
   - Accounts in this organizational directory only.
   - Redirect URI: platform Web, `https://kalmido.example.com/api/auth/oidc/callback`.
2. **Certificates & secrets › New client secret.** Copy the *value*.
3. **Token configuration › Add optional claim › ID:** `email` and `xms_edov`. The latter tells Kalmido the e-mail is verified, which it needs for linking.
4. For groups: **Token configuration › Add groups claim** (security groups). Entra sends group **object IDs**, so put the ID of the group into "Required group" / "Admin group".
5. Kalmido:
   - Provider `https://login.microsoftonline.com/<tenant ID>/v2.0`.
   - The application (client) ID and the secret.
   - Scopes `openid profile email`.
   - The user name claim `preferred_username` holds `name@domain`. Existing users are linked by their verified e-mail, and new ones are named after the e-mail's local part.

## Troubleshooting

- **"The login with the provider failed"**: the reason is under Settings › Administration › Sign-in ("Last problem with the provider") and in the container log. Common causes:
  - The issuer differs by a trailing slash.
  - The provider signs with HS256 (Authentik without a signing key).
  - An internal provider is not on the allow-list (`KALMIDO_OIDC_ALLOW_HOSTS`).
- **"There is no account for this login yet"**: create the user first (same user name or e-mail), or switch on auto-create.
- **"Your account at the login provider is not allowed"**: the person is not in the required group. Check that the groups claim actually arrives (scope `groups`, the claim name).
- **The redirect URI does not match**: `PUBLIC_URL` must be the address the browser uses, including `https://`.
