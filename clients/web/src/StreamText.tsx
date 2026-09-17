import { memo, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const CHARACTERS_PER_SECOND = 80;

/** Pace live text independently of SSE batch size; completed replies drain normally. */
export const StreamText = memo(function StreamText({ text, live, onComplete }: { text: string; live: boolean; onComplete?: (text: string) => void }) {
  const [visible, setVisible] = useState(live ? "" : text);
  const shown = useRef(visible);
  const target = useRef(text);
  const animated = useRef(live);
  const frame = useRef(0);
  const credit = useRef(0);
  const last = useRef(0);

  useEffect(() => {
    target.current = text;
    if (live) animated.current = true;
    if (!animated.current || !text.startsWith(shown.current) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
      credit.current = 0;
      shown.current = text;
      setVisible(text);
      return;
    }
    if (frame.current || shown.current === text) return;
    last.current = performance.now();
    const reveal = (now: number) => {
      // Do not accumulate a burst of credit while the tab is suspended.
      credit.current += Math.min(50, now - last.current) * CHARACTERS_PER_SECOND / 1000;
      last.current = now;
      const count = Math.floor(credit.current);
      if (count > 0) {
        const remaining = Array.from(target.current.slice(shown.current.length));
        shown.current += remaining.slice(0, count).join("");
        credit.current -= count;
        setVisible(shown.current);
      }
      if (shown.current.length < target.current.length) {
        frame.current = requestAnimationFrame(reveal);
      } else {
        frame.current = 0;
        credit.current = 0;
      }
    };
    frame.current = requestAnimationFrame(reveal);
  }, [text, live]);

  // Notify after the full text has committed to the DOM, not when SSE ends.
  useEffect(() => {
    if (visible === text) onComplete?.(text);
  }, [visible, text, onComplete]);

  useEffect(() => () => { cancelAnimationFrame(frame.current); frame.current = 0; }, []);
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{visible}</ReactMarkdown>;
});
