import { motion, AnimatePresence, type Variants } from "framer-motion";
import type { PropsWithChildren, ReactNode } from "react";

// Easing curves
export const easings = {
  smooth: [0.4, 0, 0.2, 1],
  bounce: [0.68, -0.55, 0.265, 1.55],
  snap: [0.4, 0, 0, 1],
  gentle: [0.25, 0.1, 0.25, 1],
} as const;

// Fade In variants
export const fadeInVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { duration: 0.3, ease: easings.smooth },
  },
  exit: { opacity: 0, transition: { duration: 0.2 } },
};

// Slide Up variants
export const slideUpVariants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: easings.smooth },
  },
  exit: { opacity: 0, y: -10, transition: { duration: 0.2 } },
};

// Scale variants
export const scaleVariants: Variants = {
  hidden: { opacity: 0, scale: 0.95 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.3, ease: easings.smooth },
  },
  exit: { opacity: 0, scale: 0.98, transition: { duration: 0.2 } },
};

// Stagger container variants
export const staggerContainerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.1,
    },
  },
};

// Stagger item variants
export const staggerItemVariants: Variants = {
  hidden: { opacity: 0, y: 15 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: easings.smooth },
  },
};

// Card entrance variants (slightly more pronounced)
export const cardEntranceVariants: Variants = {
  hidden: { opacity: 0, y: 30, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { duration: 0.4, ease: easings.smooth },
  },
};

const disableMotion = import.meta.env.MODE === "test";

// Page transition wrapper (key drives tab/route crossfade)
export function PageTransition({
  children,
  transitionKey,
  mode = "wait",
}: PropsWithChildren<{ transitionKey: string; mode?: "wait" | "sync" | "popLayout" }>) {
  if (disableMotion) {
    return <div key={transitionKey}>{children}</div>;
  }

  return (
    <AnimatePresence mode={mode}>
      <motion.div
        key={transitionKey}
        initial="hidden"
        animate="visible"
        exit="exit"
        variants={fadeInVariants}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// Fade In wrapper component
export function FadeIn({
  children,
  delay = 0,
  duration = 0.3,
  className = "",
}: PropsWithChildren<{ delay?: number; duration?: number; className?: string }>) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration, delay, ease: easings.smooth }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// Slide Up wrapper component
export function SlideUp({
  children,
  delay = 0,
  duration = 0.4,
  className = "",
  y = 20,
}: PropsWithChildren<{ delay?: number; duration?: number; className?: string; y?: number }>) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration, delay, ease: easings.smooth }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// Scale wrapper component
export function ScaleIn({
  children,
  delay = 0,
  className = "",
}: PropsWithChildren<{ delay?: number; className?: string }>) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3, delay, ease: easings.smooth }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// Stagger Container component
export function StaggerContainer({
  children,
  className = "",
  staggerDelay = 0.08,
  delayChildren = 0.1,
}: PropsWithChildren<{ className?: string; staggerDelay?: number; delayChildren?: number }>) {
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={{
        hidden: { opacity: 0 },
        visible: {
          opacity: 1,
          transition: { staggerChildren: staggerDelay, delayChildren },
        },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// Stagger Item component
export function StaggerItem({
  children,
  className = "",
}: PropsWithChildren<{ className?: string }>) {
  return (
    <motion.div variants={staggerItemVariants} className={className}>
      {children}
    </motion.div>
  );
}

// Animated card with hover lift
export function AnimatedCard({
  children,
  className = "",
  hoverScale = 1.02,
  hoverY = -4,
}: PropsWithChildren<{ className?: string; hoverScale?: number; hoverY?: number }>) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: hoverScale, y: hoverY }}
      transition={{ duration: 0.3, ease: easings.smooth }}
      className={className}
      style={{ willChange: "transform" }}
    >
      {children}
    </motion.div>
  );
}

// Tab content crossfade
export function TabContent({
  children,
  tabId,
}: PropsWithChildren<{ tabId: string }>) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={tabId}
        initial={{ opacity: 0, x: 10 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -10 }}
        transition={{ duration: 0.2, ease: easings.smooth }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// Shimmer Skeleton component for loading states
export function ShimmerSkeleton({
  className = "",
  width,
  height,
}: {
  className?: string;
  width?: string | number;
  height?: string | number;
}) {
  return (
    <motion.div
      className={`rounded bg-white/5 ${className}`}
      style={{ width, height }}
      animate={{
        background: [
          "linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.03) 100%)",
          "linear-gradient(90deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.03) 50%, rgba(255,255,255,0.08) 100%)",
          "linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.03) 100%)",
        ],
      }}
      transition={{
        duration: 1.8,
        repeat: Infinity,
        ease: "linear",
      }}
    />
  );
}

// Animated list wrapper
export function AnimatedList<T>({
  items,
  renderItem,
  keyExtractor,
  className = "",
  staggerDelay = 0.05,
}: {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  keyExtractor: (item: T, index: number) => string;
  className?: string;
  staggerDelay?: number;
}) {
  return (
    <motion.div className={className} initial="hidden" animate="visible">
      {items.map((item, index) => (
        <motion.div
          key={keyExtractor(item, index)}
          variants={{
            hidden: { opacity: 0, y: 15 },
            visible: {
              opacity: 1,
              y: 0,
              transition: { delay: index * staggerDelay, duration: 0.3 },
            },
          }}
        >
          {renderItem(item, index)}
        </motion.div>
      ))}
    </motion.div>
  );
}

// Animated number counter
export function AnimatedNumber({
  value,
  duration = 0.6,
  className = "",
}: {
  value: number;
  duration?: number;
  className?: string;
}) {
  return (
    <motion.span
      className={className}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      key={value}
    >
      <motion.span
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        {value}
      </motion.span>
    </motion.span>
  );
}

// Glow pulse animation wrapper
export function GlowPulse({
  children,
  className = "",
  color = "rgba(168, 85, 247, 0.3)",
}: PropsWithChildren<{ className?: string; color?: string }>) {
  return (
    <motion.div
      className={className}
      animate={{
        boxShadow: [
          `0 0 15px ${color}`,
          `0 0 25px ${color}`,
          `0 0 15px ${color}`,
        ],
      }}
      transition={{
        duration: 2.5,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    >
      {children}
    </motion.div>
  );
}
