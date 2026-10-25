import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "SpendPilot",
    template: "%s · SpendPilot",
  },
  description: "Consumer shopping requests for SpendPilot.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="border-b bg-card">
          <div className="mx-auto flex h-14 w-full max-w-3xl items-center justify-between px-4">
            <Link href="/" className="font-semibold tracking-tight">
              SpendPilot
            </Link>

            <nav className="flex items-center gap-5">
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
            </nav>
          </div>
        </header>

        {children}
      </body>
    </html>
  );
}
