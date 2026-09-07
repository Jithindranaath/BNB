import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { brand } from "@/config/brand";

export const metadata: Metadata = {
  title: brand.name,
  description: brand.tagline,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">
        <header className="border-b border-neutral-200">
          <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-3">
            <Link href="/" className="font-semibold tracking-tight">
              {brand.name}
            </Link>
            <nav className="flex gap-4 text-sm text-neutral-600">
              <Link href="/" className="hover:text-neutral-900">
                Marketplace
              </Link>
              <Link href="/report" className="hover:text-neutral-900">
                Advantage Report
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-4xl px-6 py-8">{children}</main>
        <footer className="mx-auto max-w-4xl px-6 py-10 text-xs text-neutral-400">
          Every number is measured against a named baseline, with sample size and window shown.
        </footer>
      </body>
    </html>
  );
}
