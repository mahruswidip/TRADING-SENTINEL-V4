import { PageHeading } from "@/components/page-heading";
import { Panel } from "@/components/panel";
import { StatusPill } from "@/components/status-pill";

export function PlaceholderPage({ title, description, capabilities }: { title: string; description: string; capabilities: readonly string[] }) {
  return <><PageHeading eyebrow="Structured placeholder" title={title} description={description} /><Panel title={`${title} boundary`} action={<StatusPill label="NOT ACTIVE · D0+D1" tone="neutral" />}><div className="placeholder"><p>This route is intentionally non-functional. It reserves the information architecture without implying live capability.</p><ul>{capabilities.map((capability) => <li key={capability}>{capability}</li>)}</ul></div></Panel></>;
}
