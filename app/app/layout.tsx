import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Aether Forex Lab" };

const nav = [
  ["/", "Overview"], ["/rankings", "Strategy Rankings"], ["/strategy-profile", "Strategy Profile"],
  ["/signals", "Trade Signals"], ["/paper-trades", "Paper Trades"], ["/journal", "Decision Journal"],
  ["/performance", "Performance"], ["/rules", "Rules"], ["/reports", "Reports"],
  ["/markets", "Markets"], ["/market-profile", "Market Profile"],
  ["/imports", "External Imports"], ["/cross-market", "Cross-Market Matrix"],
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", background: "#0b0e14", color: "#e6e6e6" }}>
        <header style={{ padding: "12px 20px", borderBottom: "1px solid #1f2937", display: "flex", gap: 16, alignItems: "center" }}>
          <strong style={{ color: "#5eead4" }}>Aether Forex Lab</strong>
          <span style={{ fontSize: 12, color: "#f59e0b" }}>PAPER ONLY · no live trades</span>
        </header>
        <nav style={{ display: "flex", flexWrap: "wrap", gap: 12, padding: "10px 20px", borderBottom: "1px solid #1f2937", fontSize: 14 }}>
          {nav.map(([href, label]) => (
            <Link key={href} href={href} style={{ color: "#93c5fd", textDecoration: "none" }}>{label}</Link>
          ))}
        </nav>
        <main style={{ padding: 20 }}>{children}</main>
      </body>
    </html>
  );
}
