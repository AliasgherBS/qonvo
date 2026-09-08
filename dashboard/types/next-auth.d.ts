import type { Role } from "@/lib/api";
import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface User {
    tenantId: string;
    tenantName: string;
    role: Role;
    accessToken: string;
  }

  interface Session {
    accessToken: string;
    /**
     * Why the Google exchange refused, when it did. Present only for a failed
     * sign-in, so that /login can say what happened instead of just showing
     * itself again.
     */
    authError?: string;
    user: DefaultSession["user"] & {
      tenantId: string;
      tenantName: string;
      role: Role;
    };
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    tenantId: string;
    tenantName: string;
    role: Role;
    accessToken: string;
    authError?: string;
  }
}
