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
  session: { strategy: "jwt" },
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
          return token;
        } catch {
          // No Qonvo token means no usable session; blank the access token so
          // middleware bounces the user back to /login instead of landing them
          // on an inbox that 401s on every request. Empty rather than deleted so
          // the JWT shape stays typed, and it's falsy either way.
          token.accessToken = "";
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
      return session;
    },
  },
});
