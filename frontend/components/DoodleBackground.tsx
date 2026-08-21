/** Decorative background for the empty chat state — scattered generic
 * finance line-art (candlesticks, up/down trend lines, a bank outline,
 * a ledger, a pie chart, coin stacks, the rupee sign, a briefcase, a
 * search glass, a percent sign, a target gauge). Deliberately generic,
 * not any real company's mark or logo — this is a public repo, and using
 * an actual brand (Reliance, TCS, HDFC, ...) as decoration is a trademark
 * risk even for non-commercial/decorative use.
 *
 * One inline SVG, `currentColor` throughout so it inherits the theme
 * text color (light/dark both handled by the wrapping `text-*` class,
 * no separate dark: variants needed here), very low opacity so it reads
 * as texture behind the heading, never competes with it. `pointer-events-none`
 * + `aria-hidden` since it's pure decoration. */
export function DoodleBackground() {
  return (
    <svg
      viewBox="0 0 1200 640"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      className="absolute inset-0 w-full h-full pointer-events-none text-gray-900 dark:text-gray-100"
    >
      <defs>
        {/* Candlestick chart: three bars with high-low wicks */}
        <g id="doodle-candles" strokeWidth="2" fill="none">
          <line x1="4" y1="0" x2="4" y2="8" />
          <rect x="1" y="8" width="6" height="12" />
          <line x1="4" y1="20" x2="4" y2="28" />
          <line x1="16" y1="4" x2="16" y2="10" />
          <rect x="13" y="10" width="6" height="16" />
          <line x1="16" y1="26" x2="16" y2="32" />
          <line x1="28" y1="0" x2="28" y2="6" />
          <rect x="25" y="6" width="6" height="10" />
          <line x1="28" y1="16" x2="28" y2="22" />
        </g>

        {/* Upward trend line with an arrowhead */}
        <g id="doodle-trend" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="0,32 10,20 18,26 32,4" />
          <polyline points="24,4 32,4 32,12" />
        </g>

        {/* Bank / institution outline */}
        <g id="doodle-bank" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="2,12 18,2 34,12" />
          <line x1="2" y1="12" x2="34" y2="12" />
          <line x1="2" y1="32" x2="34" y2="32" />
          <line x1="6" y1="16" x2="6" y2="28" />
          <line x1="14" y1="16" x2="14" y2="28" />
          <line x1="22" y1="16" x2="22" y2="28" />
          <line x1="30" y1="16" x2="30" y2="28" />
        </g>

        {/* Ledger / report page */}
        <g id="doodle-doc" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 2 H22 L28 8 V30 H4 Z" />
          <path d="M22 2 V8 H28" />
          <line x1="9" y1="15" x2="23" y2="15" />
          <line x1="9" y1="20" x2="23" y2="20" />
          <line x1="9" y1="25" x2="18" y2="25" />
        </g>

        {/* Pie / allocation chart */}
        <g id="doodle-pie" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="16" cy="16" r="14" />
          <path d="M16 2 A14 14 0 0 1 28 22 L16 16 Z" />
        </g>

        {/* Coin stack */}
        <g id="doodle-coins" strokeWidth="2" fill="none">
          <ellipse cx="14" cy="24" rx="13" ry="5" />
          <ellipse cx="14" cy="17" rx="13" ry="5" />
          <ellipse cx="14" cy="10" rx="13" ry="5" />
        </g>

        {/* Growth bars */}
        <g id="doodle-bars" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <line x1="2" y1="30" x2="2" y2="20" />
          <line x1="10" y1="30" x2="10" y2="14" />
          <line x1="18" y1="30" x2="18" y2="6" />
          <polyline points="14,6 18,6 18,10" />
        </g>

        {/* Rupee sign */}
        <g id="doodle-rupee">
          <text
            x="0"
            y="26"
            fontSize="30"
            fontFamily="Arial, sans-serif"
            fontWeight="700"
            stroke="none"
            fill="currentColor"
          >
            ₹
          </text>
        </g>

        {/* Downward trend line with an arrowhead (bearish) */}
        <g id="doodle-trend-down" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="0,4 10,16 18,10 32,32" />
          <polyline points="24,32 32,32 32,24" />
        </g>

        {/* Briefcase */}
        <g id="doodle-briefcase" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 8 V4 H22 V8" />
          <rect x="2" y="8" width="30" height="20" rx="2" />
          <line x1="2" y1="17" x2="32" y2="17" />
          <line x1="14" y1="17" x2="20" y2="17" />
        </g>

        {/* Magnifying glass */}
        <g id="doodle-search" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="13" cy="13" r="11" />
          <line x1="21" y1="21" x2="30" y2="30" />
        </g>

        {/* Percentage sign */}
        <g id="doodle-percent" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="7" cy="7" r="5" />
          <circle cx="25" cy="25" r="5" />
          <line x1="26" y1="2" x2="2" y2="30" />
        </g>

        {/* Gauge / target */}
        <g id="doodle-target" strokeWidth="2" fill="none">
          <circle cx="15" cy="15" r="14" />
          <circle cx="15" cy="15" r="8" />
          <circle cx="15" cy="15" r="1.5" fill="currentColor" stroke="none" />
        </g>
      </defs>

      {/* Scattered placements — hand-picked positions/rotations/scales, kept
          away from dead-center where the heading sits, opacity does the
          rest of the work so this reads as texture, not content. */}
      <g opacity="0.18" stroke="currentColor">
        <use href="#doodle-candles" x="80" y="70" transform="rotate(-8 80 70)" />
        <use href="#doodle-trend" x="220" y="480" transform="rotate(6 220 480) scale(1.4)" />
        <use href="#doodle-bank" x="960" y="90" transform="rotate(4 960 90) scale(1.3)" />
        <use href="#doodle-doc" x="1080" y="420" transform="rotate(-10 1080 420)" />
        <use href="#doodle-pie" x="140" y="280" transform="rotate(0 140 280)" />
        <use href="#doodle-coins" x="1000" y="270" transform="rotate(-6 1000 270)" />
        <use href="#doodle-bars" x="60" y="440" transform="rotate(10 60 440) scale(1.5)" />
        <use href="#doodle-trend" x="900" y="540" transform="rotate(-14 900 540) scale(1.2)" />
        <use href="#doodle-candles" x="1120" y="200" transform="rotate(12 1120 200)" />
        <use href="#doodle-bars" x="300" y="60" transform="rotate(-6 300 60)" />
        <use href="#doodle-doc" x="40" y="200" transform="rotate(8 40 200) scale(0.9)" />
        <use href="#doodle-pie" x="1040" y="560" transform="rotate(0 1040 560) scale(0.85)" />

        <use href="#doodle-rupee" x="430" y="30" transform="rotate(-5 430 30)" />
        <use href="#doodle-rupee" x="760" y="590" transform="rotate(6 760 590) scale(1.2)" />
        <use href="#doodle-trend-down" x="180" y="120" transform="rotate(10 180 120) scale(1.1)" />
        <use href="#doodle-trend-down" x="1090" y="330" transform="rotate(-8 1090 330)" />
        <use href="#doodle-briefcase" x="540" y="580" transform="rotate(-4 540 580)" />
        <use href="#doodle-briefcase" x="1140" y="60" transform="rotate(8 1140 60) scale(0.9)" />
        <use href="#doodle-search" x="620" y="20" transform="rotate(-10 620 20) scale(0.9)" />
        <use href="#doodle-search" x="20" y="330" transform="rotate(12 20 330)" />
        <use href="#doodle-percent" x="900" y="40" transform="rotate(6 900 40) scale(0.9)" />
        <use href="#doodle-percent" x="380" y="560" transform="rotate(-8 380 560) scale(1.1)" />
        <use href="#doodle-target" x="1160" y="480" transform="rotate(0 1160 480)" />
        <use href="#doodle-target" x="250" y="20" transform="rotate(0 250 20) scale(0.8)" />
        <use href="#doodle-coins" x="620" y="590" transform="rotate(4 620 590) scale(0.85)" />
        <use href="#doodle-candles" x="480" y="590" transform="rotate(-6 480 590) scale(0.85)" />
      </g>
    </svg>
  );
}
