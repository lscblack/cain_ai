import { useEffect } from "react";

/**
 * Route a clipboard image paste (Ctrl/Cmd+V) to a handler.
 * Ignores pastes while typing in a text field so search boxes still work.
 */
export function usePasteImage(onImage: (file: File) => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    function handler(e: ClipboardEvent) {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        // let text inputs handle their own paste
        const items = e.clipboardData?.items;
        const hasImage = items && Array.from(items).some((i) => i.type.startsWith("image/"));
        if (!hasImage) return;
      }
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of Array.from(items)) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) {
            e.preventDefault();
            onImage(file);
            return;
          }
        }
      }
    }
    window.addEventListener("paste", handler);
    return () => window.removeEventListener("paste", handler);
  }, [onImage, enabled]);
}
