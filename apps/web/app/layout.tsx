import type { Metadata } from "next";
import "./globals.css";
import "./tokens.css";
import "./dashboard.css";
import "./beacon.css";

export const metadata: Metadata = {
  title: "mirgam mcp",
  description: "Smart farm AI agent dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko"><body>{children}</body></html>;
}
