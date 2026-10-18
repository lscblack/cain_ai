import { useEffect, useState } from "react";

import { subscribeActivity } from "@/lib/activity";

/** A thin indeterminate bar pinned to the top of the viewport, visible whenever
 *  any API request is in flight — so navigating to a page that is still loading
 *  never looks blank/frozen. */
export function TopProgress() {
  const [active, setActive] = useState(false);

  useEffect(() => {
    let hideTimer: ReturnType<typeof setTimeout> | undefined;
    return subscribeActivity((count) => {
      if (count > 0) {
        if (hideTimer) clearTimeout(hideTimer);
        setActive(true);
      } else {
        // brief hold so very fast requests still flash the bar
        hideTimer = setTimeout(() => setActive(false), 150);
      }
    });
  }, []);

  if (!active) return null;
  return (
    <div
      aria-hidden
      style={{ position: "fixed", top: 0, left: 0, right: 0, height: 2, zIndex: 100, overflow: "hidden" }}
    >
      <span
        style={{
          position: "absolute",
          top: 0,
          height: "100%",
          background: "var(--kai-hud)",
          boxShadow: "0 0 8px var(--kai-hud)",
          animation: "kai-progress 1.1s ease-in-out infinite",
        }}
      />
    </div>
  );
}
