import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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
  title: {
    default: "SpendPilot",
    template: "%s · SpendPilot",
  },
  description: "Consumer shopping requests for SpendPilot.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <header className="border-b bg-card">
          <div className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between px-4">
            <Link href="/" className="font-semibold tracking-tight">
              SpendPilot
            </Link>
            <Link
              href="/shopping"
              className="text-sm font-medium text-muted-foreground"
            >
              Shopping
            </Link>
            <Link
              href="/enterprise"
              className="text-sm font-medium text-muted-foreground"
            >
              Enterprise
            </Link>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
