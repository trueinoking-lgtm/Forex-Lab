import type { Metadata } from "next";
import Nav from "./components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aether Forex Lab — Multi-Market Research Hub",
  description:
    "Local-first forex research & paper-trading dashboard. Walk-forward scored strategies across forex, metals and crypto. Paper-only, no live execution.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="aurora"><div className="aurora-3" /></div>
        <div className="grain" />
        <div className="shell">
          <header className="topbar">
            <span className="brandmark"><span className="dot" />Aether Forex Lab</span>
            <span className="paper-badge">Paper Only · No Live Trades</span>
          </header>
          <Nav />
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
