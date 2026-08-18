import type { Metadata } from "next";
import {
  Bricolage_Grotesque,
  Manrope,
  Geist_Mono,
  Noto_Sans_Arabic,
  Noto_Sans_Devanagari,
} from "next/font/google";

import { Providers } from "@/components/providers";
import { ThemeScript } from "@/components/theme-script";
import { auth } from "@/auth";
import { LEGAL } from "@/lib/legal";
import { SITE } from "@/lib/site";
import { OrganizationData } from "@/components/marketing/structured-data";

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

// Manrope has no Arabic or Devanagari glyphs, and relying on a system fallback
// is not safe: verified in a clean browser that Devanagari rendered as tofu
// boxes with only the fallback named. These two are loaded explicitly so the
// greetings on the landing page render everywhere, on any machine.
const notoArabic = Noto_Sans_Arabic({
  variable: "--font-noto-arabic",
  subsets: ["arabic"],
  display: "swap",
});

const notoDevanagari = Noto_Sans_Devanagari({
  variable: "--font-noto-devanagari",
  subsets: ["devanagari"],
  display: "swap",
});

export const metadata: Metadata = {
  // Resolves every relative URL below, plus the opengraph-image route, against
  // the real origin. Without it Next warns and emits localhost into OG tags.
  metadataBase: new URL(SITE.url),
  title: {
    default: `${SITE.name}: never miss a customer`,
    template: `%s | ${SITE.name}`,
  },
  description: SITE.description,
  applicationName: SITE.name,
  openGraph: {
    type: "website",
    siteName: SITE.name,
    title: `${SITE.name}: never miss a customer`,
    description: SITE.description,
    url: SITE.url,
  },
  twitter: {
    card: "summary_large_image",
    title: `${SITE.name}: never miss a customer`,
    description: SITE.description,
  },
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
      className={`${bricolage.variable} ${manrope.variable} ${geistMono.variable} ${notoArabic.variable} ${notoDevanagari.variable}`}
    >
      <head>
        <ThemeScript />
        <OrganizationData />
      </head>
      <body className="min-h-screen antialiased">
        <Providers session={session}>{children}</Providers>
      </body>
    </html>
  );
}
