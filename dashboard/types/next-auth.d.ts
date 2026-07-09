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
  }
}
