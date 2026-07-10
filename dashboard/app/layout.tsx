import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { ThemeScript } from "@/components/theme-script";
import { auth } from "@/auth";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Qonvo — Never miss a customer",
  description: "The AI representative that lives on your WhatsApp number.",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const session = await auth();

  return (
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable}`}>
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-screen antialiased">
        <Providers session={session}>{children}</Providers>
      </body>
    </html>
  );
}
