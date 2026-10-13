import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import { TopBar } from "@/components/nav/top-bar";
import { THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

// UI face and figures face from the `ant` foundations: Plus Jakarta Sans for text, JetBrains Mono for numbers and ids.
const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Cytonn Weekly review",
  description: "Coordinator review of each drafted section of the Cytonn Weekly.",
};

// The top edge of every screen is the top bar, which is the band's colour in both themes, so the browser chrome
// matches that, not the paper below it. (It follows the device's setting; the two values are near enough alike that
// a theme chosen on the bar against the device's setting does not show a seam.)
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0a2b29" },
    { media: "(prefers-color-scheme: dark)", color: "#0e2421" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The inline script below may set data-theme before React hydrates, so <html> differs from what the server sent.
    <html lang="en" className={`${jakarta.variable} ${jetbrains.variable} h-full antialiased`} suppressHydrationWarning>
      <body className="min-h-full">
        {/* Restores a stored Light or Dark before the first paint, so a reload never flashes the other theme. It runs
            as the browser parses the page; on the client React must not run it again, hence the type switch. */}
        <script
          type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }}
        />
        <a
          href="#main"
          className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to main content
        </a>
        <TopBar />
        {children}
      </body>
    </html>
  );
}
