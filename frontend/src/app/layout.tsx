import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Tajari · Evidence workspace",
  description:
    "Research evidence, technical evaluation and trading readiness for Tajari.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
