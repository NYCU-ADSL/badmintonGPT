/**
 * BadmintonRallyThinking — a decorative badminton rally shown below the agent
 * activity/"thinking" cluster while a turn is streaming.
 *
 * Layout is responsive HTML (not one fixed SVG) so the two players sit at the
 * far LEFT and RIGHT edges of the conversation column — the player-to-player
 * distance equals the container width. The shuttlecock travels the full width
 * via a transform-only trick: its wrapper is `left-0 right-0` (== container
 * width), so `translateX(100%)` spans the whole column regardless of size.
 *
 * Motion lives in CSS keyframes in globals.css (the `br-*` classes), all on one
 * shared 1.8s loop so the parabola and the racket swings stay in sync:
 *   - br-shuttle-x  : horizontal travel left→right→left (container-relative)
 *   - br-shuttle-y  : vertical arc (apex at each mid-flight) → a parabola
 *   - br-shuttle-rot: rotates the glyph so the cork leads along the velocity
 *                     tangent (up→level→down each arc; flips at each hit) — the
 *                     "follows the physics" angle
 *   - br-racket-left / br-racket-right: each racket waves as the shuttle arrives
 *
 * Purely decorative (aria-hidden); freezes under prefers-reduced-motion.
 */
export function BadmintonRallyThinking() {
  return (
    <div aria-hidden className="relative mt-1 h-[78px] w-full text-muted-foreground/80">
      {/* court ground */}
      <div className="absolute inset-x-3 bottom-[10px] h-px bg-current opacity-20" />
      {/* net (centre) */}
      <div className="absolute bottom-[10px] left-1/2 h-[30px] w-px -translate-x-1/2 bg-current opacity-25" />

      {/* players pinned to the column edges */}
      <Player side="left" className="absolute bottom-[10px] left-0" />
      <Player side="right" className="absolute bottom-[10px] right-0" />

      {/* shuttlecock: full-width x-travel wraps the y-arc wraps the tangent rotation */}
      <div className="br-shuttle-x absolute inset-x-0 bottom-[54px]">
        <div className="br-shuttle-y inline-block">
          <div className="br-shuttle-rot inline-block">
            <svg viewBox="0 0 16 18" width="16" height="18" fill="none" className="block">
              {/* cork (nose) at top → glyph "points up" at rotate(0) */}
              <circle cx="8" cy="6" r="2.8" fill="#f59e0b" stroke="none" />
              {/* feathers fanning down (trailing) */}
              <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                <line x1="8" y1="7" x2="4" y2="16" />
                <line x1="8" y1="7" x2="6.5" y2="16.5" />
                <line x1="8" y1="7" x2="8" y2="17" />
                <line x1="8" y1="7" x2="9.5" y2="16.5" />
                <line x1="8" y1="7" x2="12" y2="16" />
              </g>
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * A stick-figure player with a racket. The figure is drawn left-facing (racket
 * reaching inward to the right); the right player mirrors every x about the
 * box centre (28). The racket-arm group rotates about the shoulder
 * (transform-origin set per side in globals.css: left 16,24 — right 40,24).
 */
function Player({ side, className }: { side: "left" | "right"; className?: string }) {
  const flip = side === "right";
  const mx = (x: number) => (flip ? 56 - x : x);
  const racketClass = side === "left" ? "br-racket-left" : "br-racket-right";
  const body = "currentColor";
  return (
    <svg viewBox="0 0 56 58" width="56" height="58" fill="none" className={className}>
      {/* body + legs */}
      <g stroke={body} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
        <circle cx={mx(16)} cy={12} r={6} fill={body} stroke="none" />
        <line x1={mx(16)} y1={18} x2={mx(16)} y2={38} />
        <line x1={mx(16)} y1={38} x2={mx(9)} y2={54} />
        <line x1={mx(16)} y1={38} x2={mx(23)} y2={54} />
      </g>
      {/* racket arm (waves on hit) */}
      <g className={racketClass} stroke={body} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
        <line x1={mx(16)} y1={24} x2={mx(34)} y2={17} />
        <line x1={mx(34)} y1={17} x2={mx(40)} y2={13} />
        <ellipse cx={mx(43)} cy={11} rx={5} ry={7} stroke={body} strokeWidth="1.8" fill="none" />
      </g>
    </svg>
  );
}
