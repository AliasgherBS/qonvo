import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

import { CredentialsSignin } from "next-auth";
import type { JWT } from "@auth/core/jwt";

import { ApiError, auth as apiAuth } from "@/lib/api";

// Google SSO is optional — without a client id configured, only the email +
// password provider is offered, so a deployment that hasn't set up Google still
// has a working login rather than a broken button.
const googleEnabled = Boolean(
  process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET,
);

/**
 * Thrown when the password was right and a second factor is still needed.
 *
 * `authorize` can only return a user or nothing, so "correct password, now give
 * me the code" has no natural channel. Auth.js surfaces the `code` of a
 * `CredentialsSignin` subclass on the client result, which is exactly the
 * narrow channel this needs.
 */
class TotpRequired extends CredentialsSignin {
  constructor(code: string) {
    super();
    this.code = code;
  }
}

/**
 * When a backend token expires, read from the token itself.
 *
 * Decoded rather than assumed: hard-coding "now plus 24 hours" here would drift
 * the moment `QONVO_JWT_EXPIRY_HOURS` changed, and drift silently -- the
 * refresh would fire too late and the user would be signed out anyway, which is
 * the bug this exists to fix. `exp` is not trusted for anything but scheduling;
 * the API verifies the signature on every call.
 */
function expiryOf(accessToken: string): number | undefined {
  try {
    const [, payload] = accessToken.split(".");
    const claims = JSON.parse(Buffer.from(payload, "base64url").toString()) as { exp?: number };
    return claims.exp ? claims.exp * 1000 : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Renew the backend token before it dies (teardown X6).
 *
 * The token lasts a day and nothing renewed it, so every owner was thrown back
 * to the login screen once a day, mid-task. Aligning the Auth.js session to the
 * token's life fixed the half where the browser lied about being signed in, and
 * left the interruption.
 *
 * Runs in the `jwt` callback, which fires whenever the session is read, so a
 * user who is using the product refreshes as a side effect of using it. There
 * is no timer: a background timer in one tab does not help the other four, and
 * a closed laptop misses it entirely.
 *
 * A failed refresh blanks the token rather than keeping the old one. Middleware
 * treats a session with no access token as signed out, so the user lands on
 * /login once -- which is the correct outcome when the session has genuinely
 * reached its fortnight cap, and no worse than today's behaviour when the
 * failure was transient.
 */
async function refreshIfNearlyExpired(token: JWT): Promise<JWT> {
  if (!token.accessToken) return token;

  const expires = token.accessTokenExpires;
  // An hour of margin. Long enough that a slow or briefly-failing refresh has
  // several more chances before anything breaks; short enough that a token is
  // not rotated on every page view.
  if (expires && Date.now() < expires - 60 * 60 * 1000) return token;

  try {
    const renewed = await apiAuth.refresh({ token: token.accessToken });
    token.accessToken = renewed.accessToken;
    token.accessTokenExpires = expiryOf(renewed.accessToken);
    token.role = renewed.role;
    if (renewed.tenantId) token.tenantId = renewed.tenantId;
    delete token.authError;
  } catch {
    token.accessToken = "";
    token.authError = "session_expired";
  }
  return token;
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  // Behind our own reverse proxy (Caddy) or on localhost — the Host header is
  // ours to trust; without this Auth.js hard-fails on non-configured hosts.
  trustHost: true,
  // Aligned with the backend token's own life (teardown X6).
  //
  // Auth.js defaults to thirty days. The Qonvo JWT it wraps lasts twenty-four
  // hours, so for twenty-nine of those days the browser believed it was signed
  // in while every API call returned 401 -- a signed-in shell over a dead
  // credential, which reads as the product being broken rather than as a
  // session having ended.
  //
  // Keep this in step with QONVO_JWT_EXPIRY_HOURS. There is no refresh flow
  // yet, so this is the honest expiry rather than a shorter one that would
  // sign people out mid-session.
  session: { strategy: "jwt", maxAge: 24 * 60 * 60 },
  jwt: { maxAge: 24 * 60 * 60 },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
        totpCode: { label: "Authentication code", type: "text" },
      },
      authorize: async (credentials) => {
        const email = typeof credentials?.email === "string" ? credentials.email : "";
        const password = typeof credentials?.password === "string" ? credentials.password : "";
        const totpCode = typeof credentials?.totpCode === "string" ? credentials.totpCode : "";
        if (!email || !password) return null;

        try {
          // Login returns the access token + role/tenant/name; /api/me fills in
          // email + tenant_name (not present on the login response).
          const login = await apiAuth.login({ email, password, totpCode });
          const me = await apiAuth.me({ token: login.accessToken });

          return {
            id: login.tenantId,
            email: me.email,
            name: login.name,
            tenantId: login.tenantId,
            tenantName: me.tenantName,
            role: login.role,
            accessToken: login.accessToken,
          };
        } catch (err) {
          // A second factor is not a failed password, and collapsing the two
          // was a lockout: an account with 2FA enabled could not sign in at
          // all, because `authorize` returned null and the form said "check
          // your email and password" for a password that was correct. The code
          // is rethrown so the form can ask for the six digits.
          const code = err instanceof ApiError ? err.detail?.code : undefined;
          if (code === "totp_required" || code === "totp_invalid" || code === "totp_replayed") {
            throw new TotpRequired(code);
          }
          // Anything else really is "we could not sign you in": a wrong
          // password, a disabled account, or the API being unreachable. Null
          // renders the form's generic error, which is correct for all three
          // and deliberately does not say which.
          return null;
        }
      },
    }),
    ...(googleEnabled
      ? [
          Google({
            clientId: process.env.AUTH_GOOGLE_ID,
            clientSecret: process.env.AUTH_GOOGLE_SECRET,
            // Identity only. Calendar/Sheets scopes are requested later, from the
            // Integrations page — asking for them here would put a scary
            // permissions screen in front of every signup.
            authorization: { params: { scope: "openid email profile" } },
          }),
        ]
      : []),
  ],
  callbacks: {
    async jwt({ token, user, account }) {
      // Google sign-in: trade the id_token for a Qonvo JWT. The backend verifies
      // it against Google's JWKS and provisions a tenant if the account is new.
      if (account?.provider === "google" && account.id_token) {
        try {
          const login = await apiAuth.google(account.id_token);
          const me = await apiAuth.me({ token: login.accessToken });
          token.tenantId = login.tenantId;
          token.tenantName = me.tenantName;
          token.role = login.role;
          token.accessToken = login.accessToken;
          token.email = me.email;
          if (login.name) token.name = login.name;
          token.accessTokenExpires = expiryOf(login.accessToken);
          delete token.authError;
          return token;
        } catch (err) {
          // No Qonvo token means no usable session; blank the access token so
          // middleware bounces the user back to /login instead of landing them
          // on an inbox that 401s on every request. Empty rather than deleted so
          // the JWT shape stays typed, and it's falsy either way.
          token.accessToken = "";
          // A 409 here is not a broken sign-in, it is a refusal with a reason:
          // an account with this address exists, was created with a password,
          // and has never confirmed the address, so adopting it could hand a
          // stranger's workspace over (teardown X2). Carrying the code lets
          // /login explain it rather than silently showing itself again, which
          // is indistinguishable from the product being broken.
          const status = (err as { status?: number } | null)?.status;
          token.authError = status === 409 ? "password_account_unverified" : "google_exchange";
          return token;
        }
      }

      if (user) {
        token.tenantId = user.tenantId;
        token.tenantName = user.tenantName;
        token.role = user.role;
        token.accessToken = user.accessToken;
        token.accessTokenExpires = expiryOf(user.accessToken);
        return token;
      }

      return await refreshIfNearlyExpired(token);
    },
    session({ session, token }) {
      session.user.tenantId = token.tenantId;
      session.user.tenantName = token.tenantName;
      session.user.role = token.role;
      session.accessToken = token.accessToken;
      if (token.authError) session.authError = token.authError;
      return session;
    },
  },
});
