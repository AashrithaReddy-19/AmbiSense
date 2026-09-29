import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMetricAvailability } from "./MetricValue";

/** Loaded lazily by the Dashboard so the charting library is not part of the first page load. */
export default function DashboardTrendChart({ data, name }: { data: Array<Record<string, any>>; name: string | undefined }) {
  return (
    <div role="img" aria-label={`Line chart preview of ${name ?? "the selected metric"} by period. Gaps mean unavailable evidence. Open the full Analytics page for a table of every value.`}>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
          <Tooltip content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const contract = payload[0]?.payload?.__contract;
            return <div className="notice" style={{ maxWidth: 240 }}>{contract ? formatMetricAvailability(contract) : "Unavailable"}</div>;
          }} />
          <Legend />
          <Line connectNulls={false} dataKey="value" name={name} stroke="var(--chart-1)" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
