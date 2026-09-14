import Link from "next/link";

const items = [["Overview", "/"], ["Backtest", "/backtest"], ["Strategies", "/strategies"], ["Shadow", "/shadow"], ["Real", "/real"], ["Journal", "/journal"], ["Risk", "/risk"], ["Data / System", "/data-system"]] as const;

export function Navigation() {
  return <aside className="sidebar"><div className="brand-mark" aria-hidden="true">TS</div><nav aria-label="Primary navigation">{items.map(([label, href]) => <Link key={href} href={href}>{label}</Link>)}</nav><div className="sidebar__footer"><span>D0+D1 through D4.7 STABLE</span><strong>D5 CONTRACTS FROZEN</strong><small>V1.0.0 · execution locked · OOS untouched</small></div></aside>;
}
