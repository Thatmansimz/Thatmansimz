"use client";

export type ColorMode = "profit" | "risk" | "confidence" | "neutral";

interface SpeedometerProps {
  value: number;
  max: number;
  label: string;
  sublabel?: string;
  unit?: string;
  colorMode?: ColorMode;
  size?: number;
  formatCenter?: (v: number) => string;
}

function arcColor(pct: number, mode: ColorMode): string {
  if (mode === "profit") {
    if (pct >= 100) return "#00ff88";
    if (pct >= 60)  return "#34d399";
    if (pct >= 30)  return "#fbbf24";
    return "#94a3b8";
  }
  if (mode === "risk") {
    if (pct >= 80) return "#f43f5e";
    if (pct >= 50) return "#fbbf24";
    return "#34d399";
  }
  if (mode === "confidence") {
    if (pct >= 75) return "#00ff88";
    if (pct >= 55) return "#fbbf24";
    return "#f43f5e";
  }
  if (pct >= 70) return "#60a5fa";
  return "#94a3b8";
}

export function Speedometer({
  value,
  max,
  label,
  sublabel,
  unit = "",
  colorMode = "neutral",
  size = 190,
  formatCenter,
}: SpeedometerProps) {
  const cx = size / 2;
  const cy = size / 2;
  const r  = size / 2 - 22;

  const pct = Math.min(100, Math.max(0, max > 0 ? (value / max) * 100 : 0));
  const color = arcColor(pct, colorMode);

  // Arc geometry: 270° sweep starting at 135° SVG (7:30 o'clock)
  const circumference = 2 * Math.PI * r;
  const sweepDeg   = 270;
  const trackLen   = (sweepDeg / 360) * circumference;
  const fillLen    = (pct / 100) * trackLen;
  const startDeg   = 135;

  // Tick marks
  const NUM_TICKS = 10;
  const ticks = Array.from({ length: NUM_TICKS + 1 }, (_, i) => {
    const angleDeg = startDeg + (i / NUM_TICKS) * sweepDeg;
    const rad      = (angleDeg * Math.PI) / 180;
    const major    = i % 2 === 0;
    const outerR   = r - 1;
    const innerR   = r - (major ? 13 : 8);
    return {
      i,
      major,
      x1: cx + innerR * Math.cos(rad),
      y1: cy + innerR * Math.sin(rad),
      x2: cx + outerR * Math.cos(rad),
      y2: cy + outerR * Math.sin(rad),
    };
  });

  // Needle tip & base
  const needleDeg = startDeg + (pct / 100) * sweepDeg;
  const needleRad = (needleDeg * Math.PI) / 180;
  const needleLen = r - 26;
  const baseHalf  = 7;
  const perpRad   = needleRad + Math.PI / 2;
  const nx  = cx + needleLen  * Math.cos(needleRad);
  const ny  = cy + needleLen  * Math.sin(needleRad);
  const bx1 = cx + baseHalf   * Math.cos(perpRad);
  const by1 = cy + baseHalf   * Math.sin(perpRad);
  const bx2 = cx - baseHalf   * Math.cos(perpRad);
  const by2 = cy - baseHalf   * Math.sin(perpRad);

  const uid = label.replace(/\W/g, "");
  const displayValue = formatCenter ? formatCenter(value) : `${value.toFixed(0)}${unit}`;

  // Height: deepest arc point is at cy + r*sin(135°) ≈ cy + 0.707r
  const svgH = Math.ceil(cy + r * 0.77 + 18);

  return (
    <div className="flex flex-col items-center gap-1 select-none">
      <svg
        width={size}
        height={svgH}
        viewBox={`0 0 ${size} ${svgH}`}
        style={{ overflow: "visible" }}
      >
        <defs>
          {/* Arc glow */}
          <filter id={`ag-${uid}`} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Needle glow */}
          <filter id={`ng-${uid}`} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Dial gradient */}
          <radialGradient id={`dg-${uid}`} cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#1a2535" />
            <stop offset="100%" stopColor="#0b1120" />
          </radialGradient>
        </defs>

        {/* Outer bezel */}
        <circle cx={cx} cy={cy} r={r + 18} fill={`url(#dg-${uid})`} stroke="#2d3f52" strokeWidth="2" />
        {/* Inner bezel ring */}
        <circle cx={cx} cy={cy} r={r + 6}  fill="none" stroke="#1e293b" strokeWidth="1" />

        {/* Track arc */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke="#1e293b"
          strokeWidth="11"
          strokeLinecap="butt"
          strokeDasharray={`${trackLen} ${circumference - trackLen}`}
          transform={`rotate(${startDeg} ${cx} ${cy})`}
        />

        {/* Colored fill arc */}
        {fillLen > 1 && (
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={color}
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={`${fillLen} ${circumference - fillLen}`}
            transform={`rotate(${startDeg} ${cx} ${cy})`}
            filter={`url(#ag-${uid})`}
            style={{ transition: "stroke-dasharray 0.8s ease, stroke 0.4s ease" }}
          />
        )}

        {/* Tick marks */}
        {ticks.map((t) => (
          <line
            key={t.i}
            x1={t.x1} y1={t.y1}
            x2={t.x2} y2={t.y2}
            stroke={t.major ? "#4a5f75" : "#253040"}
            strokeWidth={t.major ? 2 : 1.2}
          />
        ))}

        {/* Needle */}
        <polygon
          points={`${nx},${ny} ${bx1},${by1} ${bx2},${by2}`}
          fill={color}
          opacity={0.92}
          filter={`url(#ng-${uid})`}
          style={{
            transition: "points 0.8s ease",
            filter: `drop-shadow(0 0 6px ${color})`,
          }}
        />

        {/* Hub */}
        <circle cx={cx} cy={cy} r={10} fill="#0f1a28" stroke="#334155" strokeWidth="1.5" />
        <circle
          cx={cx} cy={cy} r={5}
          fill={color}
          style={{ filter: `drop-shadow(0 0 5px ${color})` }}
        />

        {/* Value label */}
        <text
          x={cx}
          y={cy + r * 0.42}
          textAnchor="middle"
          fill="white"
          fontSize={size * 0.115}
          fontWeight="bold"
          fontFamily="'Courier New', monospace"
          style={{ filter: `drop-shadow(0 0 6px ${color}88)` }}
        >
          {displayValue}
        </text>
        {sublabel && (
          <text
            x={cx}
            y={cy + r * 0.60}
            textAnchor="middle"
            fill="#475569"
            fontSize={size * 0.052}
            fontFamily="sans-serif"
          >
            {sublabel}
          </text>
        )}
      </svg>

      {/* Label below gauge */}
      <p
        className="text-[11px] font-semibold tracking-widest uppercase"
        style={{ color: color }}
      >
        {label}
      </p>
    </div>
  );
}
