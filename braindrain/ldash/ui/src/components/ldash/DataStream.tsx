import { motion } from "framer-motion";
import { useEffect, useState, useMemo } from "react";

// Animated bar for data stream visualization
interface DataBarProps {
  height: number;
  delay: number;
  color?: string;
  width?: number;
}

function DataBar({ height, delay, color = "var(--ld-brand-500)", width = 6 }: DataBarProps) {
  return (
    <motion.div
      className="rounded-t-sm"
      style={{ 
        width, 
        background: `linear-gradient(to top, ${color}40, ${color})`,
        minHeight: 4,
      }}
      initial={{ height: 4, opacity: 0.4 }}
      animate={{ 
        height: Math.max(4, height), 
        opacity: [0.4, 0.9, 0.6, 0.8],
      }}
      transition={{
        height: { duration: 0.6, delay, ease: "easeOut" },
        opacity: { duration: 2, repeat: Infinity, repeatType: "reverse" },
      }}
    />
  );
}

// Data Stream Bar Chart - Animated visualization for telemetry/metrics
export function DataStream({
  barCount = 30,
  maxHeight = 140,
  color = "#a855f7",
  className = "",
}: {
  barCount?: number;
  maxHeight?: number;
  color?: string;
  className?: string;
}) {
  const [heights, setHeights] = useState<number[]>([]);

  // Generate initial random heights
  const initialHeights = useMemo(() => {
    return Array.from({ length: barCount }, () => Math.random() * maxHeight * 0.5 + 10);
  }, [barCount, maxHeight]);

  useEffect(() => {
    setHeights(initialHeights);

    // Animate heights periodically
    const interval = setInterval(() => {
      setHeights(prev => 
        prev.map(h => {
          const change = (Math.random() - 0.5) * maxHeight * 0.3;
          const newHeight = Math.max(4, Math.min(maxHeight, h + change));
          return newHeight;
        })
      );
    }, 800);

    return () => clearInterval(interval);
  }, [initialHeights, maxHeight]);

  return (
    <div className={`flex items-end justify-between gap-1 px-2 ${className}`}>
      {heights.map((height, i) => (
        <DataBar
          key={i}
          height={height}
          delay={i * 0.02}
          color={color}
        />
      ))}
    </div>
  );
}

// Pulse activity indicator - for showing active processes
export function PulseActivity({
  size = "md",
  color = "var(--ld-brand-500)",
  label,
}: {
  size?: "sm" | "md" | "lg";
  color?: string;
  label?: string;
}) {
  const sizeMap = {
    sm: "w-2 h-2",
    md: "w-3 h-3",
    lg: "w-4 h-4",
  };

  return (
    <div className="inline-flex items-center gap-2">
      <span className={`${sizeMap[size]} relative`}>
        <span
          className="absolute inset-0 rounded-full animate-ping opacity-75"
          style={{ backgroundColor: color }}
        />
        <span
          className="relative block rounded-full"
          style={{ 
            backgroundColor: color,
            width: "100%",
            height: "100%",
          }}
        />
      </span>
      {label && <span className="text-xs text-[color:var(--ld-text-soft)]">{label}</span>}
    </div>
  );
}

// Sparkline chart - Mini line chart for trends
export function Sparkline({
  data,
  width = 120,
  height = 30,
  color = "var(--ld-brand-500)",
  strokeWidth = 2,
  fill = true,
}: {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
  fill?: boolean;
}) {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((value, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((value - min) / range) * height;
    return `${x},${y}`;
  }).join(" ");

  const fillPoints = `0,${height} ${points} ${width},${height}`;

  return (
    <svg width={width} height={height} className="overflow-visible">
      <defs>
        <linearGradient id={`sparkline-gradient-${color.replace(/[^a-zA-Z0-9]/g, '')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && (
        <motion.polygon
          points={fillPoints}
          fill={`url(#sparkline-gradient-${color.replace(/[^a-zA-Z0-9]/g, '')})`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5 }}
        />
      )}
      <motion.polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
        style={{ filter: `drop-shadow(0 0 3px ${color})` }}
      />
    </svg>
  );
}

// Live metric value with animated change indicator
export function LiveMetric({
  value,
  unit = "",
  previousValue,
  className = "",
}: {
  value: number;
  unit?: string;
  previousValue?: number;
  className?: string;
}) {
  const trend = previousValue !== undefined 
    ? value > previousValue ? "up" : value < previousValue ? "down" : "neutral"
    : "neutral";

  return (
    <div className={`flex items-baseline gap-2 ${className}`}>
      <motion.span
        key={value}
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-2xl font-bold text-white"
      >
        {value}
        {unit && <span className="text-lg text-[color:var(--ld-brand-400)]">{unit}</span>}
      </motion.span>
      {trend !== "neutral" && (
        <motion.span
          initial={{ opacity: 0, scale: 0 }}
          animate={{ opacity: 1, scale: 1 }}
          className={trend === "up" ? "text-emerald-400" : "text-rose-400"}
        >
          {trend === "up" ? "↑" : "↓"}
        </motion.span>
      )}
    </div>
  );
}

// Animated dots for "loading" or "waiting" states
export function AnimatedDots({
  count = 3,
  size = 6,
  color = "var(--ld-brand-500)",
  className = "",
}: {
  count?: number;
  size?: number;
  color?: string;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-1 ${className}`}>
      {Array.from({ length: count }).map((_, i) => (
        <motion.span
          key={i}
          className="rounded-full"
          style={{ 
            width: size, 
            height: size, 
            backgroundColor: color,
          }}
          animate={{
            scale: [1, 1.3, 1],
            opacity: [0.4, 1, 0.4],
          }}
          transition={{
            duration: 1.2,
            repeat: Infinity,
            delay: i * 0.2,
          }}
        />
      ))}
    </div>
  );
}

// Data packet visualization - for showing data flow
export function DataPacket({
  size = "md",
  color = "var(--ld-brand-500)",
  animated = true,
}: {
  size?: "sm" | "md" | "lg";
  color?: string;
  animated?: boolean;
}) {
  const sizeMap = {
    sm: { container: "w-5 h-5", icon: 10 },
    md: { container: "w-8 h-8", icon: 16 },
    lg: { container: "w-12 h-12", icon: 24 },
  };

  const { container, icon } = sizeMap[size];

  return (
    <motion.div
      className={`${container} rounded-md flex items-center justify-center`}
      style={{ 
        background: `linear-gradient(180deg, ${color}20, ${color}10)`,
        border: `1px solid ${color}40`,
        boxShadow: `0 0 15px ${color}30`,
      }}
      animate={animated ? {
        boxShadow: [
          `0 0 10px ${color}20`,
          `0 0 20px ${color}40`,
          `0 0 10px ${color}20`,
        ],
      } : undefined}
      transition={{
        duration: 2,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    >
      <svg width={icon} height={icon} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2">
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <path d="M9 9h6v6H9z" fill={color} fillOpacity="0.5" />
      </svg>
    </motion.div>
  );
}

// Status stream - list of status items with animated transitions
export function StatusStream<T>({
  items,
  renderItem,
  keyExtractor,
  maxItems = 5,
  className = "",
}: {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  keyExtractor: (item: T) => string;
  maxItems?: number;
  className?: string;
}) {
  const visibleItems = items.slice(0, maxItems);

  return (
    <div className={`space-y-2 ${className}`}>
      {visibleItems.map((item, index) => (
        <motion.div
          key={keyExtractor(item)}
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 20 }}
          transition={{ delay: index * 0.05, duration: 0.3 }}
          className="animate-slideUp"
          style={{ animationDelay: `${index * 50}ms` }}
        >
          {renderItem(item)}
        </motion.div>
      ))}
    </div>
  );
}
