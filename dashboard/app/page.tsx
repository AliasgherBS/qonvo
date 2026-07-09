import { redirect } from "next/navigation";

// Middleware already guarantees an authenticated session reaches here —
// send it straight to the inbox, the default landing surface.
export default function RootPage() {
  redirect("/inbox");
}
