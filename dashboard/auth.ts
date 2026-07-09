import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

import { ApiError, auth as apiAuth } from "@/lib/api";

export const { handlers, signIn, signOut, auth } = NextAuth({
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
  ],
  callbacks: {
    jwt({ token, user }) {
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
