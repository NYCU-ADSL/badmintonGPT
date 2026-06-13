interface CourtBackdropProps {
  /** ``home`` = empty/landing court (baseline + service-line L); ``chat`` = framing lines. */
  state: "home" | "chat";
  /** home only: render the Ball-in drop (ball+ripple+IN). Set once the composer textarea
   * is clicked; the ball and IN chip then stay (only the ripple fades), so nothing
   * appears until the user clicks the box. */
  dropped?: boolean;
}

/**
 * Decorative「淡綠場館」court lines drawn behind the thread (aria-hidden,
 * pointer-events-none). It lives in the non-scrolling layer of ``ThreadViewport``
 * so the lines stay fixed while messages scroll over them.
 *
 * - home: a solid white horizontal baseline + vertical service line forming an L,
 *   plus the Ball-in drop (ball → ripple → IN).
 * - chat: translucent framing lines (a top line across the view + a line in the
 *   left gutter of the message column).
 *
 * Light/dark colours, glows and the drop animation all live in globals.css. The
 * drop is CSS-triggered by ``.court-root:focus-within`` (the ThreadViewport root),
 * which excludes the header — so it fires on composer focus, not the theme button.
 */
export function CourtBackdrop({ state, dropped = false }: CourtBackdropProps) {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="court-glow" />
      {state === "home" ? (
        <>
          <div className="court-line court-h-base" />
          <div className="court-line court-v-base" />
          {dropped ? (
            <div className="court-drop">
              <div className="court-drop__ball" />
              <div className="court-drop__ripple" />
              <div className="court-drop__in">IN</div>
            </div>
          ) : null}
        </>
      ) : (
        <>
          <div className="court-line-soft court-h-top" />
          <div className="absolute inset-0 flex justify-center">
            <div className="relative h-full w-full max-w-[49.5rem]">
              <div className="court-line-soft court-v-left" />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
