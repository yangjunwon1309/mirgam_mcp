"use client";
export function Sparkline({ values, color }: { values: number[]; color: string }) {
  const width = 160, height = 28, pad = 2;
  const min = Math.min(...values, 0), max = Math.max(...values, 1), span = max - min || 1;
  const points = values.map((value, index) => {
    const x = values.length < 2 ? width / 2 : pad + index * (width - pad * 2) / (values.length - 1);
    const y = height - pad - (value - min) * (height - pad * 2) / span;
    return x.toFixed(1) + "," + y.toFixed(1);
  }).join(" ");
  const area = points ? "2,26 " + points + " 158,26" : "";
  return <svg className="bx-spark" viewBox="0 0 160 28" role="img" aria-label="최근 측정 추이"><polygon points={area} fill={color} opacity=".1" /><polyline points={points} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" /></svg>;
}
