import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tajari AI Trading",
  description: "Autonomous AI-powered day trading platform — Tajari",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased" style={{ background: "#050913" }}>
        {/* Scanning sweep line */}
        <div className="scan-line" />
        <div style={{ position: "relative", zIndex: 1 }}>{children}</div>
      </body>
    </html>
  );
}
