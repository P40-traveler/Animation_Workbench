export type Rect = { x: number; y: number; width: number; height: number };
export type Transform = {
  dx: number;
  dy: number;
  anchor_x: number | null;
  anchor_y: number | null;
  scale: number;
  rotation: number;
  flip_x: boolean;
  flip_y: boolean;
  opacity: number;
};
export type Exposure = {
  id: string;
  asset_id: string;
  duration_ms: number;
  transform: Partial<Transform>;
};
export type Track = {
  id: string;
  name: string;
  kind: "character" | "effect" | "reference";
  visible: boolean;
  locked: boolean;
  export: boolean;
  start_ms: number;
  end_behavior: "hide" | "hold" | "loop";
  transform: Transform;
  exposures: Exposure[];
};
export type Frame = {
  id: string;
  duration_ms: number;
  status: "pending" | "passed" | "problem";
  events: string[];
  points: Record<string, number[]>;
};
export type Issue = {
  id: string;
  frame_id: string;
  track_id: string | null;
  rect: Rect | null;
  tag: string;
  note: string;
  status: "open" | "resolved" | "recheck";
  author: string;
  original_label: string;
};
export type State = {
  canvas: {
    width: number;
    height: number;
    pivot_x: number;
    pivot_y: number;
    ground_y: number;
  };
  body: { width: number; height: number; reference_rect: Rect | null };
  frames: Frame[];
  tracks: Track[];
  issues: Issue[];
  prompt: {
    identity: string;
    motion: string;
    frame_notes: string;
    changes: string;
    reference_ids: string[];
    final_text: string;
  };
  status: "draft" | "candidate" | "accepted";
};
export type Version = {
  id: string;
  action_id: string;
  project_id: string;
  name: string;
  revision: number;
  state: State;
  can_undo: boolean;
  can_redo: boolean;
};
export type Asset = {
  id: string;
  project_id: string;
  name: string;
  width: number;
  height: number;
  transparent_pixels: number;
  has_alpha: boolean;
  parent_id: string | null;
  operation: string;
};
export type Catalog = {
  objects: { id: string; kind: string; parent: string | null; name: string }[];
  versions: { id: string; action_id: string; name: string; revision: number }[];
};
export const id = () => crypto.randomUUID().replaceAll("-", "");
export const defaults = (): Transform => ({
  dx: 0,
  dy: 0,
  anchor_x: null,
  anchor_y: null,
  scale: 1,
  rotation: 0,
  flip_x: false,
  flip_y: false,
  opacity: 1,
});
export const total = (s: State) =>
  s.frames.reduce((n, f) => n + f.duration_ms, 0);
export const frameTimes = (s: State) => {
  let t = 0;
  return s.frames.map((f) => {
    const v = t;
    t += f.duration_ms;
    return v;
  });
};
export const frameIndex = (s: State, t: number) => {
  let at = 0;
  return s.frames.findIndex((f) => {
    const yes = t >= at && t < at + f.duration_ms;
    at += f.duration_ms;
    return yes;
  });
};
export function sample(t: Track, time: number): Exposure | undefined {
  let n = time - t.start_ms;
  const dur = t.exposures.reduce((a, e) => a + e.duration_ms, 0);
  if (n < 0 || !dur) return;
  if (n >= dur) {
    if (t.end_behavior === "hide") return;
    if (t.end_behavior === "hold") return t.exposures.at(-1);
    n %= dur;
  }
  let a = 0;
  return t.exposures.find((e) => {
    const ok = n < a + e.duration_ms;
    a += e.duration_ms;
    return ok;
  });
}
export const imageUrl = (a: string) => `/api/v1/assets/${a}/image`;
export const images = new Map<string, HTMLImageElement>();
export function image(a: string): Promise<HTMLImageElement> {
  const cached = images.get(a);
  if (cached) return Promise.resolve(cached);
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      images.set(a, img);
      resolve(img);
    };
    img.onerror = reject;
    img.src = imageUrl(a);
  });
}
export async function api<T = any>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const multipart = body instanceof FormData;
  const r = await fetch("/api/v1" + path, {
    method: method || (body ? "POST" : "GET"),
    headers: multipart
      ? { "X-Actor": "user" }
      : { "Content-Type": "application/json", "X-Actor": "user" },
    body: body ? (multipart ? body : JSON.stringify(body)) : undefined,
  });
  if (!r.ok) {
    let detail;
    try {
      detail = (await r.json()).detail;
    } catch {
      detail = r.statusText;
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return r.json();
}
export async function drawComposition(
  ctx: CanvasRenderingContext2D,
  s: State,
  t: number,
  only?: string,
) {
  ctx.imageSmoothingEnabled = false;
  for (const track of s.tracks) {
    if (!track.visible || (only && track.id !== only)) continue;
    const exp = sample(track, t);
    if (!exp) continue;
    const im = await image(exp.asset_id);
    const tr = { ...track.transform, ...exp.transform };
    ctx.save();
    ctx.translate(s.canvas.pivot_x + tr.dx, s.canvas.pivot_y + tr.dy);
    ctx.rotate((tr.rotation * Math.PI) / 180);
    ctx.scale(tr.scale * (tr.flip_x ? -1 : 1), tr.scale * (tr.flip_y ? -1 : 1));
    ctx.globalAlpha = tr.opacity;
    ctx.drawImage(
      im,
      -(tr.anchor_x ?? im.width / 2),
      -(tr.anchor_y ?? im.height),
    );
    ctx.restore();
  }
}
