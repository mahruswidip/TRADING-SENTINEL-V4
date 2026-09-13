export const percent = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
export const plainPercent = (value: number) => `${value.toFixed(1)}%`;
export const usd = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
export const costUsd = (value: number) => usd(-value);
export const bps = (value: number) => `${value.toFixed(1)} bps`;
export const compactTime = (value: string) => new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(value));
