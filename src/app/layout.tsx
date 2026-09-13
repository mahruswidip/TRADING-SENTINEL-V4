import type { Metadata } from "next";
import { GlobalHeader } from "@/components/global-header";
import { Navigation } from "@/components/nav";
import { sentinelData } from "@/data";
import "./globals.css";

export const metadata: Metadata = { title: "Trading Sentinel V4", description: "Systematic trading research operations dashboard" };

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const system = await sentinelData.getSystemHealth();
  return <html lang="en"><body><div className="app-shell"><Navigation /><div className="workspace"><GlobalHeader system={system} /><main>{children}</main></div></div></body></html>;
}
