import { useEffect, useRef, useState } from "react";
import {
  drawComposition,
  frameIndex,
  frameTimes,
  State,
  Rect,
  Track,
  image,
  sample,
} from "./types";

type Props = {
  state: State;
  time: number;
  zoom: number;
  onion: boolean;
  before: number;
  after: number;
  opacity: number;
  onionLayer: boolean;
  track?: Track;
  guides: boolean;
  background: string;
  backgroundImage: string;
  tool: string;
  onMove: (dx: number, dy: number) => void;
  onRect: (r: Rect) => void;
};
export function Stage(p: Props) {
  const canvas = useRef<HTMLCanvasElement>(null),
    over = useRef<HTMLCanvasElement>(null),
    generation = useRef(0);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  useEffect(() => {
    const token = ++generation.current;
    let alive = true;
    (async () => {
      const s = p.state;
      const out = document.createElement("canvas");
      out.width = s.canvas.width;
      out.height = s.canvas.height;
      const ctx = out.getContext("2d")!;
      const i = frameIndex(s, p.time),
        times = frameTimes(s);
      if (p.onion && i >= 0) {
        for (
          let j = Math.max(0, i - p.before);
          j <= Math.min(times.length - 1, i + p.after);
          j++
        ) {
          if (j === i) continue;
          const ghost = document.createElement("canvas");
          ghost.width = out.width;
          ghost.height = out.height;
          const gc = ghost.getContext("2d")!;
          await drawComposition(
            gc,
            s,
            times[j],
            p.onionLayer ? p.track?.id : undefined,
          );
          gc.globalCompositeOperation = "source-in";
          gc.fillStyle = j < i ? "#ec7897" : "#73baff";
          gc.fillRect(0, 0, out.width, out.height);
          ctx.globalAlpha = p.opacity;
          ctx.drawImage(ghost, 0, 0);
        }
      }
      ctx.globalAlpha = 1;
      await drawComposition(ctx, s, p.time);
      if (alive && token === generation.current && canvas.current) {
        const target = canvas.current.getContext("2d")!;
        target.clearRect(0, 0, out.width, out.height);
        target.drawImage(out, 0, 0);
      }
    })().catch(() => {});
    return () => {
      alive = false;
    };
  }, [
    p.state,
    p.time,
    p.onion,
    p.before,
    p.after,
    p.opacity,
    p.onionLayer,
    p.track?.id,
  ]);
  useEffect(() => {
    const ctx = over.current?.getContext("2d");
    if (!ctx) return;
    const c = p.state.canvas;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.lineWidth = 1 / p.zoom;
    if (p.guides) {
      ctx.strokeStyle = "#68d9aacc";
      ctx.setLineDash([4 / p.zoom, 4 / p.zoom]);
      ctx.beginPath();
      ctx.moveTo(0, c.ground_y);
      ctx.lineTo(c.width, c.ground_y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.strokeStyle = "#e9b65c";
      ctx.beginPath();
      ctx.moveTo(c.pivot_x - 6 / p.zoom, c.pivot_y);
      ctx.lineTo(c.pivot_x + 6 / p.zoom, c.pivot_y);
      ctx.moveTo(c.pivot_x, c.pivot_y - 6 / p.zoom);
      ctx.lineTo(c.pivot_x, c.pivot_y + 6 / p.zoom);
      ctx.stroke();
      ctx.strokeStyle = "#9ba9d0";
      ctx.strokeRect(
        c.pivot_x - p.state.body.width / 2,
        c.pivot_y - p.state.body.height,
        p.state.body.width,
        p.state.body.height,
      );
      const f = p.state.frames[frameIndex(p.state, p.time)];
      for (const pt of Object.values(f?.points || {})) {
        ctx.fillStyle = "#ff70a6";
        ctx.fillRect(
          pt[0] - 2 / p.zoom,
          pt[1] - 2 / p.zoom,
          4 / p.zoom,
          4 / p.zoom,
        );
      }
    }
    if (rect) {
      ctx.strokeStyle = "#a48af7";
      ctx.fillStyle = "#a48af733";
      ctx.fillRect(rect.x, rect.y, rect.width, rect.height);
      ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);
    }
  }, [p.state, p.time, p.guides, p.zoom, rect]);
  const pos = (e: React.PointerEvent) => {
    const b = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.floor((e.clientX - b.left) / p.zoom),
      y: Math.floor((e.clientY - b.top) / p.zoom),
    };
  };
  return (
    <div className="stage-scroll">
      <div
        className={"stage " + (p.background === "checker" ? "checker" : "")}
        style={{
          width: p.state.canvas.width * p.zoom,
          height: p.state.canvas.height * p.zoom,
          backgroundColor:
            p.background === "checker" ? undefined : p.background,
          backgroundImage: p.backgroundImage
            ? `url(${p.backgroundImage})`
            : undefined,
        }}
      >
        <canvas
          ref={canvas}
          width={p.state.canvas.width}
          height={p.state.canvas.height}
        />
        <canvas
          ref={over}
          width={p.state.canvas.width}
          height={p.state.canvas.height}
          onPointerDown={(e) => {
            if (p.tool === "move" && p.track?.locked) return;
            drag.current = pos(e);
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            if (!drag.current) return;
            const to = pos(e),
              from = drag.current;
            if (p.tool !== "move")
              setRect({
                x: Math.min(from.x, to.x),
                y: Math.min(from.y, to.y),
                width: Math.max(1, Math.abs(to.x - from.x)),
                height: Math.max(1, Math.abs(to.y - from.y)),
              });
          }}
          onPointerUp={(e) => {
            if (!drag.current) return;
            const to = pos(e),
              from = drag.current;
            drag.current = null;
            if (p.tool === "move") p.onMove(to.x - from.x, to.y - from.y);
            else
              p.onRect({
                x: Math.min(from.x, to.x),
                y: Math.min(from.y, to.y),
                width: Math.max(1, Math.abs(to.x - from.x)),
                height: Math.max(1, Math.abs(to.y - from.y)),
              });
            setRect(null);
          }}
        />
      </div>
    </div>
  );
}

type PixelProps = {
  assetId: string;
  zoom: number;
  color: string;
  tool: string;
  onColor: (s: string) => void;
  onCommit: (p: { x: number; y: number; rgba: number[] }[]) => Promise<void>;
  disabled: boolean;
};
export function PixelEditor(p: PixelProps) {
  const ref = useRef<HTMLCanvasElement>(null),
    buffer = useRef<ImageData | null>(null),
    start = useRef<{ x: number; y: number } | null>(null),
    last = useRef<{ x: number; y: number } | null>(null),
    clipboard = useRef<ImageData | null>(null),
    patches = useRef(
      new Map<string, { x: number; y: number; rgba: number[] }>(),
    );
  const [size, setSize] = useState([1, 1]),
    [selection, setSelection] = useState<Rect | null>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    image(p.assetId).then((im) => {
      if (!alive || !ref.current) return;
      setSize([im.width, im.height]);
      ref.current.width = im.width;
      ref.current.height = im.height;
      const ctx = ref.current.getContext("2d")!;
      ctx.drawImage(im, 0, 0);
      buffer.current = ctx.getImageData(0, 0, im.width, im.height);
      setSelection(null);
    });
    return () => {
      alive = false;
    };
  }, [p.assetId]);
  function coord(e: React.PointerEvent) {
    const b = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.floor((e.clientX - b.left) / p.zoom),
      y: Math.floor((e.clientY - b.top) / p.zoom),
    };
  }
  function put(x: number, y: number, rgba: number[]) {
    const b = buffer.current;
    if (!b || x < 0 || y < 0 || x >= b.width || y >= b.height) return;
    const index = (y * b.width + x) * 4;
    b.data.set(rgba, index);
    patches.current.set(`${x},${y}`, { x, y, rgba });
  }
  function paint(x: number, y: number) {
    const rgba =
      p.tool === "eraser"
        ? [0, 0, 0, 0]
        : [
            parseInt(p.color.slice(1, 3), 16),
            parseInt(p.color.slice(3, 5), 16),
            parseInt(p.color.slice(5, 7), 16),
            255,
          ];
    put(x, y, rgba);
  }
  function redraw() {
    if (buffer.current)
      ref.current?.getContext("2d")?.putImageData(buffer.current, 0, 0);
  }
  async function commit() {
    if (!patches.current.size) return;
    setBusy(true);
    try {
      await p.onCommit([...patches.current.values()]);
    } catch {
      const im = await image(p.assetId);
      const ctx = ref.current?.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, im.width, im.height);
        ctx.drawImage(im, 0, 0);
        buffer.current = ctx.getImageData(0, 0, im.width, im.height);
      }
    } finally {
      patches.current.clear();
      setBusy(false);
    }
  }
  function fill(x: number, y: number) {
    const b = buffer.current;
    if (!b || x < 0 || y < 0 || x >= b.width || y >= b.height) return;
    const index = (y * b.width + x) * 4,
      target = Array.from(b.data.slice(index, index + 4));
    const rgba = [
      parseInt(p.color.slice(1, 3), 16),
      parseInt(p.color.slice(3, 5), 16),
      parseInt(p.color.slice(5, 7), 16),
      255,
    ];
    if (target.every((v, i) => v === rgba[i])) return;
    const queue = [[x, y]],
      seen = new Set<number>();
    while (queue.length) {
      const [cx, cy] = queue.pop()!;
      if (cx < 0 || cy < 0 || cx >= b.width || cy >= b.height) continue;
      const ii = (cy * b.width + cx) * 4;
      if (seen.has(ii) || !target.every((v, i) => b.data[ii + i] === v))
        continue;
      seen.add(ii);
      put(cx, cy, rgba);
      queue.push([cx - 1, cy], [cx + 1, cy], [cx, cy - 1], [cx, cy + 1]);
    }
    redraw();
  }
  function capture() {
    const b = buffer.current;
    if (!b || !selection) return;
    const copy = new ImageData(selection.width, selection.height);
    for (let y = 0; y < selection.height; y++)
      for (let x = 0; x < selection.width; x++) {
        const sx = x + selection.x,
          sy = y + selection.y;
        if (sx >= 0 && sy >= 0 && sx < b.width && sy < b.height)
          copy.data.set(
            b.data.slice((sy * b.width + sx) * 4, (sy * b.width + sx) * 4 + 4),
            (y * copy.width + x) * 4,
          );
      }
    clipboard.current = copy;
  }
  function paste(dx = 0, dy = 0, move = false) {
    const copy = clipboard.current,
      b = buffer.current;
    if (!copy || !b) return;
    const x = selection?.x ?? 0,
      y = selection?.y ?? 0;
    if (move && selection)
      for (let yy = 0; yy < selection.height; yy++)
        for (let xx = 0; xx < selection.width; xx++)
          put(x + xx, y + yy, [0, 0, 0, 0]);
    for (let yy = 0; yy < copy.height; yy++)
      for (let xx = 0; xx < copy.width; xx++)
        put(
          x + dx + xx,
          y + dy + yy,
          Array.from(
            copy.data.slice(
              (yy * copy.width + xx) * 4,
              (yy * copy.width + xx) * 4 + 4,
            ),
          ),
        );
    setSelection({
      x: x + dx,
      y: y + dy,
      width: copy.width,
      height: copy.height,
    });
    redraw();
    void commit();
  }
  return (
    <div className="pixel-work">
      <div className="pixel-info">
        原始素材坐标 · {size[0]} × {size[1]} px · 每笔另存当前曝光副本{" "}
        {busy ? "· 保存中…" : ""}
      </div>
      <div className="pixel-actions">
        <button disabled={!selection || busy} onClick={capture}>
          复制选区
        </button>
        <button disabled={busy} onClick={() => paste()}>
          粘贴到选区
        </button>
        <button
          disabled={!selection || busy}
          onClick={() => {
            capture();
            paste(-1, 0, true);
          }}
        >
          ← 移动1px
        </button>
        <button
          disabled={!selection || busy}
          onClick={() => {
            capture();
            paste(1, 0, true);
          }}
        >
          → 移动1px
        </button>
        <button
          disabled={!selection || busy}
          onClick={() => {
            capture();
            paste(0, -1, true);
          }}
        >
          ↑
        </button>
        <button
          disabled={!selection || busy}
          onClick={() => {
            capture();
            paste(0, 1, true);
          }}
        >
          ↓
        </button>
      </div>
      <div className="pixel-scroll">
        <div
          className="pixel-board checker"
          style={{ width: size[0] * p.zoom, height: size[1] * p.zoom }}
        >
          <canvas
            ref={ref}
            style={{ width: "100%", height: "100%" }}
            onPointerDown={(e) => {
              if (busy || p.disabled) return;
              const at = coord(e);
              start.current = at;
              last.current = at;
              patches.current.clear();
              e.currentTarget.setPointerCapture(e.pointerId);
              if (p.tool === "select") {
                setSelection({ x: at.x, y: at.y, width: 1, height: 1 });
                return;
              }
              if (p.tool === "eyedropper") {
                const b = buffer.current;
                if (
                  b &&
                  at.x >= 0 &&
                  at.y >= 0 &&
                  at.x < b.width &&
                  at.y < b.height
                ) {
                  const i = (at.y * b.width + at.x) * 4;
                  p.onColor(
                    "#" +
                      Array.from(b.data.slice(i, i + 3))
                        .map((c) => c.toString(16).padStart(2, "0"))
                        .join(""),
                  );
                }
                return;
              }
              if (p.tool === "fill") fill(at.x, at.y);
              else paint(at.x, at.y);
              redraw();
            }}
            onPointerMove={(e) => {
              if (!start.current || busy || p.disabled) return;
              const at = coord(e);
              if (p.tool === "select") {
                setSelection({
                  x: Math.min(at.x, start.current.x),
                  y: Math.min(at.y, start.current.y),
                  width: Math.abs(at.x - start.current.x) + 1,
                  height: Math.abs(at.y - start.current.y) + 1,
                });
                return;
              }
              if (!["pencil", "eraser"].includes(p.tool)) return;
              const from = last.current!;
              const steps = Math.max(
                Math.abs(at.x - from.x),
                Math.abs(at.y - from.y),
              );
              for (let i = 0; i <= steps; i++)
                paint(
                  Math.round(
                    from.x + ((at.x - from.x) * i) / Math.max(1, steps),
                  ),
                  Math.round(
                    from.y + ((at.y - from.y) * i) / Math.max(1, steps),
                  ),
                );
              last.current = at;
              redraw();
            }}
            onPointerUp={() => {
              start.current = null;
              last.current = null;
              void commit();
            }}
          />
          {p.zoom >= 4 && (
            <div
              className="pixel-grid"
              style={{ backgroundSize: `${p.zoom}px ${p.zoom}px` }}
            />
          )}
          {selection && (
            <div
              className="selection-box"
              style={{
                left: selection.x * p.zoom,
                top: selection.y * p.zoom,
                width: selection.width * p.zoom,
                height: selection.height * p.zoom,
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
