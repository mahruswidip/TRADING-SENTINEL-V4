export function Progress({ value, label }: { value: number; label: string }) {
  return <div className="progress" aria-label={`${label}: ${value}%`}><div className="progress__track"><span style={{ width: `${value}%` }} /></div><div className="progress__labels"><span>{label}</span><strong>{value}%</strong></div></div>;
}
