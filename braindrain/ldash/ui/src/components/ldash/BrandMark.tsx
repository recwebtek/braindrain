interface BrandMarkProps {
  size?: "sm" | "md" | "lg";
  showWordmark?: boolean;
  compact?: boolean;
}

const sizeMap = {
  sm: "h-9 w-9",
  md: "h-12 w-12",
  lg: "h-16 w-16",
};

export function BrandMark({ size = "md", showWordmark = true, compact = false }: BrandMarkProps) {
  return (
    <div className={`flex items-center ${compact ? "gap-3" : "gap-4"}`}>
      <div className={`ld-brand-orb ${sizeMap[size]}`} aria-hidden="true">
        <svg viewBox="0 0 64 64" className="h-full w-full" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="brainStroke" x1="9" y1="9" x2="54" y2="54" gradientUnits="userSpaceOnUse">
              <stop stopColor="#F5BEFF" />
              <stop offset="0.45" stopColor="#C56FFF" />
              <stop offset="1" stopColor="#58E6FF" />
            </linearGradient>
            <radialGradient id="brainFill" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(32 30) rotate(90) scale(26 24)">
              <stop stopColor="#6A2DAA" stopOpacity="0.72" />
              <stop offset="1" stopColor="#15081E" stopOpacity="0.15" />
            </radialGradient>
          </defs>
          <path
            d="M22.6 16.8c-6.1 0-11.1 4.8-11.1 10.8 0 3.2 1.4 6.1 3.8 8.1-1.5 2.1-2 4.7-1.3 7.1 1 3.7 4.4 6.4 8.4 6.4 2.5 0 4.9-1 6.6-2.7 1.6 1.7 4 2.7 6.5 2.7 4 0 7.5-2.7 8.5-6.4.7-2.4.2-5-1.3-7.1 2.4-2 3.8-4.9 3.8-8.1 0-6-5-10.8-11.1-10.8-1.4 0-2.8.2-4 .8-1.3-.6-2.7-.8-4-.8Z"
            fill="url(#brainFill)"
            stroke="url(#brainStroke)"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M32 17.6v28.6" stroke="url(#brainStroke)" strokeWidth="1.9" strokeLinecap="round" />
          <path d="M22.6 23.4c3.8.1 7 2.7 7.9 6.4" stroke="url(#brainStroke)" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M20.7 33.8c4 .2 7.2 3 7.8 6.8" stroke="url(#brainStroke)" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M41.4 23.4c-3.8.1-7 2.7-7.9 6.4" stroke="url(#brainStroke)" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M43.3 33.8c-4 .2-7.2 3-7.8 6.8" stroke="url(#brainStroke)" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M26.5 15.4c0 2.1-1.7 3.8-3.9 3.8" stroke="url(#brainStroke)" strokeWidth="1.5" strokeLinecap="round" />
          <path d="M37.5 15.4c0 2.1 1.7 3.8 3.9 3.8" stroke="url(#brainStroke)" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="18.5" cy="27.5" r="1.8" fill="#7CF6FF" />
          <circle cx="45.5" cy="27.5" r="1.8" fill="#F0A8FF" />
          <circle cx="22.2" cy="45.8" r="1.8" fill="#F0A8FF" />
          <circle cx="41.8" cy="45.8" r="1.8" fill="#7CF6FF" />
        </svg>
      </div>
      {showWordmark ? (
        <div className="min-w-0">
          <p className="ld-brand-kicker">LivingDash</p>
          <div className={`${compact ? "text-base" : "text-lg"} truncate font-semibold tracking-tight text-white`}>BrainDrain MCP</div>
        </div>
      ) : null}
    </div>
  );
}
