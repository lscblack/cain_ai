import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import { AuthImg } from "@/components/AuthImg";

/** Animated strip of shifting indexed-face crops, shown while a face search
 *  runs — the same "scanning the index" motif as the upload search page. */
export function ScanningStrip({
  crops,
  label = "searching local index…",
  count = 6,
  size = 40,
  grid = false,
  columns,
}: {
  crops: string[];
  label?: string;
  count?: number;
  size?: number;
  grid?: boolean;
  columns?: number;
}) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 140);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <div className="kai-metadata mb-1" style={{ color: "var(--kai-warn)" }}>
        ● {label}
      </div>
      {crops.length > 0 ? (
        <div
          className={columns ? "grid gap-1.5" : grid ? "flex flex-wrap gap-1.5" : "flex gap-1.5 overflow-hidden"}
          style={columns ? { gridTemplateColumns: `repeat(${columns}, ${size}px)`, width: "max-content" } : undefined}
        >
          {Array.from({ length: count }).map((_, i) => {
            const idx = (tick + i) % crops.length;
            return (
              <motion.div
                key={i}
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.05 }}
                className="shrink-0 overflow-hidden rounded border border-line"
                style={{ height: size, width: size }}
              >
                <AuthImg path={crops[idx]} className="h-full w-full object-cover" />
              </motion.div>
            );
          })}
        </div>
      ) : (
        <div className="kai-metadata">comparing embeddings…</div>
      )}
    </div>
  );
}
