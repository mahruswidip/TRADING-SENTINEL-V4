"use client";

import { useEffect, useState } from "react";

function times(now: Date) {
  return { utc: now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "UTC" }), local: now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) };
}

export function Clock() {
  const [value, setValue] = useState<{ utc: string; local: string } | null>(null);
  useEffect(() => { const update = () => setValue(times(new Date())); update(); const timer = window.setInterval(update, 1000); return () => window.clearInterval(timer); }, []);
  return <div className="clock" suppressHydrationWarning><span>UTC <strong>{value?.utc ?? "--:--:--"}</strong></span><span>LOCAL <strong>{value?.local ?? "--:--:--"}</strong></span></div>;
}
