"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  ["/", "Overview"], ["/rankings", "Strategy Rankings"], ["/strategy-profile", "Strategy Profile"],
  ["/signals", "Trade Signals"], ["/paper-trades", "Paper Trades"], ["/journal", "Decision Journal"],
  ["/performance", "Performance"], ["/rules", "Rules"], ["/reports", "Reports"],
  ["/markets", "Markets"], ["/market-profile", "Market Profile"],
  ["/imports", "External Imports"], ["/cross-market", "Cross-Market Matrix"],
  ["/market-trends", "Market Trends"], ["/demo-execution", "Demo Execution"],
  ["/broker-demo", "Broker Demo"], ["/research-reviews", "Research Reviews"],
];

export default function Nav() {
  const path = usePathname() || "/";
  return (
    <nav className="nav">
      {NAV.map(([href, label]) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} className={active ? "active" : ""}>{label}</Link>
        );
      })}
    </nav>
  );
}
