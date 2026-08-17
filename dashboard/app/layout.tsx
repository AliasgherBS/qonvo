import type { Metadata } from "next";
import { Bricolage_Grotesque, Manrope, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { ThemeScript } from "@/components/theme-script";
import { auth } from "@/auth";
import { LEGAL } from "@/lib/legal";

import "./globals.css";

// Both faces are variable fonts on Google Fonts, so `weight` is deliberately
// omitted: that loads the full axis and gives us 500 and 600 for hierarchy
// rather than pinning a couple of discrete cuts.
const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  display: "swap",
});

const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Qonvo: never miss a customer",
  description: "The AI representative that lives on your WhatsApp number.",
  // Emits <meta name="google-site-verification" ...> into <head>. Search Console
  // ownership is a prerequisite for Google OAuth app verification.
  verification: { google: LEGAL.googleSiteVerification },
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const session = await auth();

  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${bricolage.variable} ${manrope.variable} ${geistMono.variable}`}
    >
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-screen antialiased">
        <Providers session={session}>{children}</Providers>
      </body>
    </html>
  );
}
