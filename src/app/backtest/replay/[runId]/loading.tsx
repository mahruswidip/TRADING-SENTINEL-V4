import { DataStateBoundary } from "@/components/data-state";

export default function ReplayLoading() {
  return <DataStateBoundary state="loading">Loading replay scenario…</DataStateBoundary>;
}
