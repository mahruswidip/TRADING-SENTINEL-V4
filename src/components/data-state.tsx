import type { LoadState } from "@/domain/contracts";
import type { ReactNode } from "react";

export function DataStateBoundary({ state, children, message }: { state: LoadState; children: ReactNode; message?: string }) {
  if (state === "success" || state === "degraded") return <>{children}</>;
  const defaults = { loading: "Loading provider data…", empty: "No provider records are available.", error: "Provider data could not be loaded." } as const;
  return <div className={`data-state data-state--${state}`}>{message ?? defaults[state]}</div>;
}
