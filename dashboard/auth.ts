import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

import { ApiError, auth as apiAuth } from "@/lib/api";

// Google SSO is optional — without a client id configured, only the email +
// password provider is offered, so a deployment that hasn't set up Google still
// has a working login rather than a broken button.
const googleEnabled = Boolean(
  process.env.AUTH_GOOGLE_ID && process.env.AUTH_GOOGLE_SECRET,
);

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
      },
      authorize: async (credentials) => {
        const email = typeof credentials?.email === "string" ? credentials.email : "";
        const password = typeof credentials?.password === "string" ? credentials.password : "";
        if (!email || !password) return null;

        try {
          // Login returns the access token + role/tenant/name; /api/me fills in
          // email + tenant_name (not present on the login response).
          const login = await apiAuth.login({ email, password });
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
          // Backend not reachable yet in Phase 0 — surface as invalid credentials
          // rather than a 500 so the login form can render a clean error state.
          if (err instanceof ApiError) return null;
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
      }
      return token;
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
