import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Stage, PixelEditor } from "./Canvas";
import {
  api,
  Asset,
  Catalog,
  Version,
  State,
  Track,
  Exposure,
  Rect,
  Transform,
  id,
  defaults,
  total,
  frameIndex,
  frameTimes,
  sample,
  imageUrl,
} from "./types";
import "./style.css";

const labels = {
  pending: "待检查",
  passed: "通过",
  problem: "有问题",
  draft: "草稿",
  candidate: "候选",
  accepted: "已验收",
  open: "待修",
  resolved: "已解决",
  recheck: "待复查",
};
function NumberField({
  label,
  value,
  onChange,
  min,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min?: number;
  step?: number;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(n);
        }}
      />
    </label>
  );
}
function App() {
  const [catalog, setCatalog] = useState<Catalog>({
      objects: [],
      versions: [],
    }),
    [version, setVersion] = useState<Version | null>(null),
    [assets, setAssets] = useState<Asset[]>([]),
    [dirty, setDirty] = useState(false),
    [remote, setRemote] = useState(false),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("layers"),
    [time, setTime] = useState(0),
    [playing, setPlaying] = useState(false),
    [zoom, setZoom] = useState(1),
    [loop, setLoop] = useState(true),
    [onion, setOnion] = useState(false),
    [before, setBefore] = useState(1),
    [after, setAfter] = useState(1),
    [onionOpacity, setOnionOpacity] = useState(0.25),
    [onionLayer, setOnionLayer] = useState(false),
    [guides, setGuides] = useState(true),
    [background, setBackground] = useState("checker"),
    [backgroundImage, setBackgroundImage] = useState(""),
    [tool, setTool] = useState("move"),
    [trackId, setTrackId] = useState(""),
    [scope, setScope] = useState("track");
  const [pixel, setPixel] = useState(false),
    [pixelTool, setPixelTool] = useState("pencil"),
    [pixelColor, setPixelColor] = useState("#d5b66a"),
    [pixelZoom, setPixelZoom] = useState(8),
    [problemOnly, setProblemOnly] = useState(false),
    [tagFilter, setTagFilter] = useState(""),
    [issueRect, setIssueRect] = useState<Rect | null>(null),
    [issueTag, setIssueTag] = useState("衔接"),
    [issueNote, setIssueNote] = useState(""),
    [compareId, setCompareId] = useState(""),
    [compare, setCompare] = useState<Version | null>(null),
    [sequenceIds, setSequenceIds] = useState<string[]>([]),
    [sequence, setSequence] = useState<Version[]>([]),
    [sequenceMode, setSequenceMode] = useState(false);
  const [importOpen, setImportOpen] = useState(false),
    [sliceAsset, setSliceAsset] = useState<Asset | null>(null),
    [columns, setColumns] = useState(4),
    [rows, setRows] = useState(2),
    [margin, setMargin] = useState(0),
    [spacing, setSpacing] = useState(0),
    [cellWidth, setCellWidth] = useState(0),
    [cellHeight, setCellHeight] = useState(0),
    [sliceOrder, setSliceOrder] = useState("row"),
    [manual, setManual] = useState(false),
    [rects, setRects] = useState<Rect[]>([]),
    [sliceWarnings, setSliceWarnings] = useState<string[]>([]),
    [importKind, setImportKind] = useState<Track["kind"]>("character"),
    [librarySelection, setLibrarySelection] = useState<string[]>([]);
  const [jobs, setJobs] = useState<any[]>([]),
    [requests, setRequests] = useState<any[]>([]),
    [report, setReport] = useState<any | null>(null),
    [exportMode, setExportMode] = useState("union"),
    [exportCount, setExportCount] = useState(8),
    [exportLayers, setExportLayers] = useState(true),
    [allowClip, setAllowClip] = useState(false),
    [method, setMethod] = useState("nearest"),
    [colors, setColors] = useState(0),
    [dither, setDither] = useState(false),
    [history, setHistory] = useState<any[]>([]),
    [authoritative, setAuthoritative] = useState(false);
  const vref = useRef(version),
    dirtyRef = useRef(dirty),
    sliceCanvas = useRef<HTMLCanvasElement>(null),
    sliceStart = useRef<{ x: number; y: number } | null>(null);
  vref.current = version;
  dirtyRef.current = dirty;
  const s = version?.state,
    track = s?.tracks.find((t) => t.id === trackId),
    frame = s?.frames[Math.max(0, frameIndex(s, time))],
    exposure = track ? sample(track, time) : undefined;
  function notify(e: unknown) {
    setMessage(e instanceof Error ? e.message : String(e));
  }
  async function task(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      notify(e);
    } finally {
      setBusy(false);
    }
  }
  async function catalogLoad() {
    setCatalog(await api("/catalog"));
  }
  async function assetsLoad(project?: string) {
    const pid = project || vref.current?.project_id;
    if (pid) setAssets(await api(`/assets?project_id=${pid}`));
  }
  function accept(v: Version) {
    setVersion(v);
    setDirty(false);
    setRemote(false);
    setReport(null);
    setTrackId(selected => v.state.tracks.some(t => t.id === selected) ? selected : v.state.tracks[0]?.id || "");
    setTime(current => current >= total(v.state) ? 0 : current);
  }
  async function load(vid: string) {
    if (
      dirtyRef.current &&
      !confirm("当前有未保存修改。切换版本会放弃这些修改，是否继续？")
    )
      return;
    setPlaying(false);
    const v = await api<Version>(`/versions/${vid}`);
    accept(v);
    setTime(0);
    setPixel(false);
    await assetsLoad(v.project_id);
  }
  function edit(fn: (state: State) => void) {
    if (!version || busy) return;
    const next = structuredClone(version);
    fn(next.state);
    setVersion(next);
    setDirty(true);
    setReport(null);
  }
  async function save(): Promise<Version> {
    const v = vref.current;
    if (!v) throw new Error("请选择动作版本");
    if (!dirtyRef.current) return v;
    const updated = await api<Version>(
      `/versions/${v.id}`,
      { expected_revision: v.revision, state: v.state, name: v.name },
      "PUT",
    );
    accept(updated);
    await catalogLoad();
    return updated;
  }
  async function clone() {
    if (!version) return;
    const name = prompt("新版本名称", version.name + " 副本");
    if (!name) return;
    const latest = await api<Version>(`/versions/${version.id}`);
    const v = await api<Version>(`/versions/${version.id}/clone`, {
      expected_revision: latest.revision,
      state: version.state,
      name,
    });
    accept(v);
    await catalogLoad();
    setMessage("已建立独立版本，批注标为待复查");
  }
  useEffect(() => {
    void catalogLoad().catch(notify);
  }, []);
  useEffect(() => {
    const timer = setInterval(() => {
      void (async () => {
        const c = await api<Catalog>("/catalog");
        setCatalog(c);
        const v = vref.current,
          latest = c.versions.find((x) => x.id === v?.id);
        if (v && latest && latest.revision !== v.revision) {
          if (dirtyRef.current) setRemote(true);
          else {
            accept(await api(`/versions/${v.id}`));
            await assetsLoad(v.project_id);
          }
        }
      })().catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (tab !== "exports" && tab !== "prompt") return;
    let alive = true;
    const tick = () => {
      Promise.all([api("/jobs"), api("/generation-requests")])
        .then(([j, r]) => {
          if (alive) {
            setJobs(j);
            setRequests(r);
          }
        })
        .catch(() => {});
    };
    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [tab]);
  useEffect(() => {
    if (!playing || !s) return;
    let animation = 0;
    const start = performance.now(),
      initial = time;
    const length =
      sequenceMode && sequence.length
        ? sequence.reduce((n, v) => n + total(v.state), 0)
        : total(s);
    if (!length) {
      setPlaying(false);
      return;
    }
    const tick = (now: number) => {
      let t = initial + Math.floor(now - start);
      if (t >= length) {
        if (loop) t %= length;
        else {
          setTime(length - 1);
          setPlaying(false);
          return;
        }
      }
      setTime(t);
      animation = requestAnimationFrame(tick);
    };
    animation = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animation);
  }, [playing, loop, version?.id, sequenceMode, sequence]);
  useEffect(() => {
    if (compareId)
      api<Version>(`/versions/${compareId}`).then(setCompare).catch(notify);
    else setCompare(null);
  }, [compareId]);
  useEffect(() => {
    Promise.all(sequenceIds.map((vid) => api<Version>(`/versions/${vid}`)))
      .then(setSequence)
      .catch(notify);
  }, [sequenceIds]);
  function appendAssets(list: Asset[], kind = importKind) {
    if (!list.length || !s) return;
    const n = list.length;
    edit((state) => {
      const t: Track = {
        id: id(),
        name:
          kind === "character"
            ? "角色动作"
            : kind === "effect"
              ? "剑光 / 特效"
              : "辅助参考",
        kind,
        visible: true,
        locked: false,
        export: kind !== "reference",
        start_ms: 0,
        end_behavior: kind === "reference" ? "hold" : "hide",
        transform: defaults(),
        exposures: list.map((a) => ({
          id: id(),
          asset_id: a.id,
          duration_ms: 100,
          transform: {},
        })),
      };
      state.tracks.push(t);
      if (kind === "character" && !state.frames.length)
        state.frames = Array.from({ length: n }, () => ({
          id: id(),
          duration_ms: 100,
          status: "pending",
          events: [],
          points: {},
        }));
      setTrackId(t.id);
    });
    setImportOpen(false);
    setSliceAsset(null);
    setLibrarySelection([]);
    setMessage(`已加入${n}帧；请检查位置、时长和切片边界`);
  }
  async function upload(files: FileList | null) {
    if (!files || !version) return;
    const uploaded: Asset[] = [];
    for (const f of Array.from(files)) {
      const form = new FormData();
      form.set("project_id", version.project_id);
      form.set("file", f);
      uploaded.push(await api("/assets", form));
    }
    await assetsLoad();
    if (uploaded.length === 1) {
      setSliceAsset(uploaded[0]);
      setRects([]);
      setCellWidth(0);
      setCellHeight(0);
    } else appendAssets(uploaded);
  }
  async function slicing() {
    if (!sliceAsset) return;
    const data = await api(
      `/assets/${sliceAsset.id}/slice`,
      manual
        ? { rects }
        : {
            columns,
            rows,
            margin,
            spacing,
            width: cellWidth || null,
            height: cellHeight || null,
            order: sliceOrder,
          },
    );
    setSliceWarnings(data.warnings);
    await assetsLoad();
    appendAssets(data.assets);
    if (data.warnings.length) setMessage(data.warnings.join("；"));
  }
  useEffect(() => {
    const canvas = sliceCanvas.current;
    if (!sliceAsset || !canvas) return;
    const img = new Image();
    img.onload = () => {
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(img, 0, 0);
      ctx.strokeStyle = "#a18dff";
      ctx.lineWidth = Math.max(1, img.width / 700);
      const boxes = manual
        ? rects
        : Array.from({ length: columns * rows }, (_, i) => {
            const w =
                cellWidth ||
                Math.floor(
                  (img.width - 2 * margin - (columns - 1) * spacing) / columns,
                ),
              h =
                cellHeight ||
                Math.floor(
                  (img.height - 2 * margin - (rows - 1) * spacing) / rows,
                );
            return {
              x: margin + (i % columns) * (w + spacing),
              y: margin + Math.floor(i / columns) * (h + spacing),
              width: w,
              height: h,
            };
          });
      boxes.forEach((r, i) => {
        ctx.strokeRect(r.x, r.y, r.width, r.height);
        ctx.fillStyle = "#a18dff";
        ctx.font = `${Math.max(12, img.width / 60)}px sans-serif`;
        ctx.fillText(String(i + 1), r.x + 5, r.y + 20);
      });
    };
    img.src = imageUrl(sliceAsset.id);
  }, [
    sliceAsset,
    columns,
    rows,
    margin,
    spacing,
    cellWidth,
    cellHeight,
    manual,
    rects,
  ]);
  function transformEdit(key: keyof Transform, value: unknown) {
    if (track?.locked) return;
    edit((state) => {
      const t = state.tracks.find((t) => t.id === trackId)!;
      if (scope === "exposure" && exposure) {
        const exp = t.exposures.find((e) => e.id === exposure.id)!;
        (exp.transform as any)[key] = value;
      } else (t.transform as any)[key] = value;
    });
  }
  const tr = track
    ? {
        ...track.transform,
        ...(scope === "exposure" ? exposure?.transform : {}),
      }
    : defaults();
  function addIssue() {
    if (!frame) return;
    edit((state) => {
      state.issues.push({
        id: id(),
        frame_id: frame.id,
        track_id: trackId || null,
        rect: issueRect,
        tag: issueTag,
        note: issueNote,
        status: "open",
        author: "user",
        original_label: `F${state.frames.findIndex((f) => f.id === frame.id) + 1}`,
      });
      state.frames.find((f) => f.id === frame.id)!.status = "problem";
    });
    setIssueNote("");
    setIssueRect(null);
    setTool("move");
  }
  async function pixelCommit(
    patches: { x: number; y: number; rgba: number[] }[],
  ) {
    if (!track || !exposure) return;
    setBusy(true);
    try {
      const v = await save();
      const updated = await api<Version>(`/versions/${v.id}/pixels`, {
        expected_revision: v.revision,
        track_id: track.id,
        exposure_id: exposure.id,
        patches,
      });
      accept(updated);
      await assetsLoad();
    } catch (e) {
      notify(e);
      await assetsLoad();
      throw e;
    } finally {
      setBusy(false);
    }
  }
  async function travel(direction: string) {
    const v = await save();
    accept(
      await api(`/versions/${v.id}/${direction}`, {
        expected_revision: v.revision,
      }),
    );
    await assetsLoad();
  }
  function composePrompt() {
    if (!s) return;
    const text = [
      `角色固定设定：\n${s.prompt.identity}`,
      `动作：\n${s.prompt.motion}`,
      `逐帧说明：\n${s.prompt.frame_notes}`,
      `输出要求：透明 PNG；${s.frames.length || "待定"}帧；固定画布 ${s.canvas.width}×${s.canvas.height}；统一 pivot (${s.canvas.pivot_x},${s.canvas.pivot_y})；角色身体目标 ${s.body.width}×${s.body.height}，武器与特效可占更大范围；分层需求按动作说明。`,
      `本次修改：\n${s.prompt.changes}`,
    ].join("\n\n");
    edit((state) => {
      state.prompt.final_text = text;
    });
  }
  async function convert() {
    const v = await save(),
      rect = v.state.body.reference_rect;
    if (!rect) throw new Error("请先指定角色身体参考框（在原素材坐标中）");
    const job = await api(`/versions/${v.id}/convert`, {
      expected_revision: v.revision,
      track_ids: [trackId],
      reference_rect: rect,
      target_width: v.state.body.width,
      target_height: v.state.body.height,
      method,
      colors,
      dither,
    });
    setTab("exports");
    setMessage(`精度转换任务 ${job.id.slice(0, 8)} 已启动`);
  }
  async function exportRun() {
    const v = await save();
    await api(`/versions/${v.id}/export`, {
      expected_revision: v.revision,
      mode: exportMode,
      count: exportCount,
      allow_clip: allowClip,
      layers: exportLayers,
    });
    setTab("exports");
  }
  async function validateRun() {
    const v = await save();
    setReport(await api(`/versions/${v.id}/validate`));
  }
  async function createProject() {
    const name = prompt("项目名称", "我的角色素材");
    if (!name) return;
    const p = await api("/projects", { name });
    const c = await api("/characters", { name: "主角", parent_id: p.id });
    const a = await api("/actions", { name: "普攻01", parent_id: c.id });
    const v = await api<Version>(`/actions/${a.id}/versions`, { name: "v001" });
    accept(v);
    setAssets([]);
    await catalogLoad();
  }
  function pointerSlice(e: React.PointerEvent) {
    const b = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.round(((e.clientX - b.left) * sliceAsset!.width) / b.width),
      y: Math.round(((e.clientY - b.top) * sliceAsset!.height) / b.height),
    };
  }
  let viewState = s,
    viewTime = time,
    viewName = "";
  if (sequenceMode && sequence.length) {
    let t = time;
    for (const v of sequence) {
      if (t < total(v.state)) {
        viewState = v.state;
        viewTime = t;
        viewName = v.name;
        break;
      }
      t -= total(v.state);
    }
  }
  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-icon">帧</div>
          <div>
            <strong>帧间</strong>
            <small>角色动画素材工作台</small>
          </div>
        </div>
        <div className="breadcrumbs">
          {version
            ? `${catalog.objects.find((o) => o.id === version.project_id)?.name} / ${catalog.objects.find((o) => o.id === version.action_id)?.name} / ${version.name}`
            : "从一段动作开始"}
          <span className={"save-state " + (dirty ? "dirty" : "")}>
            {dirty ? "● 未保存" : version ? "● 已保存" : ""}
          </span>
        </div>
        <div className="header-actions">
          <button
            disabled={!version || busy}
            onClick={() => void task(() => travel("undo"))}
          >
            撤销
          </button>
          <button
            disabled={!version || busy}
            onClick={() => void task(() => travel("redo"))}
          >
            重做
          </button>
          <button disabled={!version || busy} onClick={() => void task(clone)}>
            另存版本
          </button>
          <button
            className="primary"
            disabled={!dirty || busy}
            onClick={() => void task(save)}
          >
            保存修改
          </button>
        </div>
      </header>
      {(message || remote) && (
        <div className={"notice " + (remote ? "warning" : "")}>
          <span>
            {remote
              ? "另一端已更新此版本。本地修改保留，请另存版本或刷新。"
              : message}
          </span>
          <button
            onClick={() => {
              setMessage("");
              if (remote && version) void task(() => load(version.id));
            }}
          >
            {remote ? "刷新版本" : "关闭"}
          </button>
        </div>
      )}
      <div className={"workspace " + (busy ? "processing" : "")}>
        <aside className="sidebar">
          <div className="panel-title">
            素材项目
            <button title="新建项目" onClick={() => void task(createProject)}>
              ＋
            </button>
          </div>
          {catalog.objects
            .filter((o) => o.kind === "project")
            .map((project) => (
              <div className="project" key={project.id}>
                <div className="project-name">
                  ◈ {project.name}
                  <button
                    title="添加角色"
                    onClick={() =>
                      void task(async () => {
                        const name = prompt("角色名称");
                        if (name) {
                          await api("/characters", {
                            name,
                            parent_id: project.id,
                          });
                          await catalogLoad();
                        }
                      })
                    }
                  >
                    ＋
                  </button>
                </div>
                {catalog.objects
                  .filter((o) => o.parent === project.id)
                  .map((char) => (
                    <div className="character" key={char.id}>
                      <div className="character-name">
                        {char.name}
                        <button
                          title="添加动作"
                          onClick={() =>
                            void task(async () => {
                              const name = prompt("动作名称");
                              if (name) {
                                const a = await api("/actions", {
                                  name,
                                  parent_id: char.id,
                                });
                                const v = await api<Version>(
                                  `/actions/${a.id}/versions`,
                                  { name: "v001" },
                                );
                                await catalogLoad();
                                await load(v.id);
                              }
                            })
                          }
                        >
                          ＋
                        </button>
                      </div>
                      {catalog.objects
                        .filter((o) => o.parent === char.id)
                        .map((action) => (
                          <div key={action.id} className="action">
                            <div className="action-name">▸ {action.name}</div>
                            {catalog.versions
                              .filter((v) => v.action_id === action.id)
                              .map((v) => (
                                <button
                                  key={v.id}
                                  className={
                                    "version-item " +
                                    (version?.id === v.id ? "active" : "")
                                  }
                                  onClick={() => void task(() => load(v.id))}
                                >
                                  <span>{v.name}</span>
                                  <small>r{v.revision}</small>
                                </button>
                              ))}
                          </div>
                        ))}
                    </div>
                  ))}
              </div>
            ))}
          <div className="sidebar-bottom">
            <p>
              共同查看，同步修改。
              <br />
              原图保留，修订可追溯。
            </p>
            <button
              onClick={() =>
                void task(async () => {
                  const b = await api("/backup", {});
                  window.open(b.download_url, "_blank");
                })
              }
            >
              备份全部项目
            </button>
            <a href="/docs" target="_blank">
              协作接口文档 ↗
            </a>
          </div>
        </aside>
        {!version || !s ? (
          <main className="welcome">
            <div className="welcome-art">✦</div>
            <span className="eyebrow">ANIMATION WORKBENCH</span>
            <h1>让每一帧，都对得上。</h1>
            <p>
              在这里预览动作、校准位置、组合剑光。
              <br />
              把需要修改的地方标出来，再一起完成它。
            </p>
            <button
              className="primary"
              onClick={() => void task(createProject)}
            >
              新建素材项目
            </button>
            <p className="muted">也可以从左侧打开已有动作。</p>
          </main>
        ) : (
          <>
            <main className="main">
              <div className="toolbar">
                <div className="segmented">
                  <button
                    className={!pixel ? "selected" : ""}
                    onClick={() => setPixel(false)}
                  >
                    动画预览
                  </button>
                  <button
                    className={pixel ? "selected" : ""}
                    disabled={!exposure}
                    onClick={() => {
                      setPixel(true);
                      setPlaying(false);
                    }}
                  >
                    像素微调
                  </button>
                </div>
                {pixel ? (
                  <>
                    <select
                      value={pixelTool}
                      onChange={(e) => setPixelTool(e.target.value)}
                    >
                      <option value="pencil">铅笔</option>
                      <option value="eraser">橡皮</option>
                      <option value="eyedropper">吸色</option>
                      <option value="fill">填充</option>
                      <option value="select">矩形选区</option>
                    </select>
                    <input
                      type="color"
                      value={pixelColor}
                      onChange={(e) => setPixelColor(e.target.value)}
                    />
                    <select
                      value={pixelZoom}
                      onChange={(e) => setPixelZoom(+e.target.value)}
                    >
                      {[1, 2, 4, 8, 12, 16].map((n) => (
                        <option key={n} value={n}>
                          {n}×
                        </option>
                      ))}
                    </select>
                  </>
                ) : (
                  <>
                    <select
                      value={tool}
                      onChange={(e) => setTool(e.target.value)}
                    >
                      <option value="move">移动当前图层</option>
                      <option value="issue">框选问题区域</option>
                    </select>
                    <select
                      value={zoom}
                      onChange={(e) => setZoom(+e.target.value)}
                    >
                      {[1, 2, 3, 4, 6, 8].map((n) => (
                        <option key={n} value={n}>
                          {n}×
                        </option>
                      ))}
                    </select>
                    <label>
                      <input
                        type="checkbox"
                        checked={onion}
                        onChange={(e) => setOnion(e.target.checked)}
                      />
                      洋葱皮
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={guides}
                        onChange={(e) => setGuides(e.target.checked)}
                      />
                      参考线
                    </label>
                    <select
                      value={background}
                      onChange={(e) => setBackground(e.target.value)}
                    >
                      <option value="checker">透明棋盘</option>
                      <option value="#171b25">深色背景</option>
                      <option value="#e5e5e5">浅色背景</option>
                      <option value="#42705f">绿色背景</option>
                    </select>
                  </>
                )}
              </div>
              <div className="canvas-area">
                {pixel && exposure ? (
                  <PixelEditor
                    assetId={exposure.asset_id}
                    zoom={pixelZoom}
                    color={pixelColor}
                    tool={pixelTool}
                    onColor={setPixelColor}
                    onCommit={pixelCommit}
                    disabled={busy || !!track?.locked}
                  />
                ) : viewState ? (
                  <>
                    <div className="canvas-badge">
                      {viewName || version.name}{" "}
                      <span>
                        {viewState.canvas.width} × {viewState.canvas.height} px
                      </span>
                    </div>
                    <div
                      className={
                        "preview-layout " + (compare ? "comparison" : "")
                      }
                    >
                      <Stage
                        state={viewState}
                        time={viewTime}
                        zoom={zoom}
                        onion={onion}
                        before={before}
                        after={after}
                        opacity={onionOpacity}
                        onionLayer={onionLayer}
                        track={track}
                        guides={guides}
                        background={background}
                        backgroundImage={backgroundImage}
                        tool={tool}
                        onMove={(dx, dy) => {
                          if (!track || sequenceMode) return;
                          if (scope === "exposure" && exposure) {
                            edit((state) => {
                              const t = state.tracks.find(
                                  (t) => t.id === trackId,
                                )!,
                                e = t.exposures.find(
                                  (e) => e.id === exposure.id,
                                )!;
                              e.transform = {
                                ...e.transform,
                                dx: tr.dx + dx,
                                dy: tr.dy + dy,
                              };
                            });
                          } else
                            edit((state) => {
                              const t = state.tracks.find(
                                (t) => t.id === trackId,
                              )!;
                              t.transform.dx += dx;
                              t.transform.dy += dy;
                            });
                        }}
                        onRect={(r) => {
                          setIssueRect(r);
                          setTab("issues");
                        }}
                      />
                      {compare && (
                        <div className="compare-stage">
                          <p>{compare.name} · 对比</p>
                          <Stage
                            state={compare.state}
                            time={Math.min(
                              viewTime,
                              Math.max(0, total(compare.state) - 1),
                            )}
                            zoom={zoom}
                            onion={false}
                            before={0}
                            after={0}
                            opacity={0}
                            onionLayer={false}
                            guides={guides}
                            background={background}
                            backgroundImage={backgroundImage}
                            tool="move"
                            onMove={() => {}}
                            onRect={() => {}}
                          />
                        </div>
                      )}
                    </div>
                    {authoritative && !dirty && (
                      <div className="export-preview">
                        <span>后端导出预览</span>
                        <img
                          src={`/api/v1/versions/${version.id}/render?time_ms=${viewTime}&r=${version.revision}`}
                          style={{
                            width: s.canvas.width * zoom,
                            height: s.canvas.height * zoom,
                          }}
                        />
                      </div>
                    )}
                  </>
                ) : null}
              </div>
              <div className="playbar">
                <button
                  title="上一帧"
                  onClick={() => {
                    setPlaying(false);
                    setTime(
                      frameTimes(s)[Math.max(0, frameIndex(s, time) - 1)] || 0,
                    );
                  }}
                >
                  ◀|
                </button>
                <button className="play" onClick={() => setPlaying(!playing)}>
                  {playing ? "Ⅱ" : "▶"}
                </button>
                <button
                  title="下一帧"
                  onClick={() => {
                    setPlaying(false);
                    setTime(
                      frameTimes(s)[
                        Math.min(s.frames.length - 1, frameIndex(s, time) + 1)
                      ] || 0,
                    );
                  }}
                >
                  |▶
                </button>
                <label>
                  <input
                    type="checkbox"
                    checked={loop}
                    onChange={(e) => setLoop(e.target.checked)}
                  />
                  循环
                </label>
                <input
                  className="scrubber"
                  type="range"
                  min={0}
                  max={Math.max(
                    0,
                    (sequenceMode
                      ? sequence.reduce((n, v) => n + total(v.state), 0)
                      : total(s)) - 1,
                  )}
                  value={time}
                  onChange={(e) => {
                    setPlaying(false);
                    setTime(+e.target.value);
                  }}
                />
                <span className="timecode">
                  {time} / {total(s)} ms
                </span>
                <span className="framecode">
                  F
                  {String(Math.max(0, frameIndex(s, viewTime)) + 1).padStart(
                    3,
                    "0",
                  )}
                </span>
              </div>
              <div className="timeline">
                <div className="timeline-heading">
                  <strong>动作时间轴</strong>
                  <label>
                    <input
                      type="checkbox"
                      checked={problemOnly}
                      onChange={(e) => setProblemOnly(e.target.checked)}
                    />
                    只看问题帧
                  </label>
                  <button
                    onClick={() =>
                      edit((state) =>
                        state.frames.push({
                          id: id(),
                          duration_ms: 100,
                          status: "pending",
                          events: [],
                          points: {},
                        }),
                      )
                    }
                  >
                    ＋ 动作帧
                  </button>
                  <button
                    onClick={() => {
                      const fps = Number(prompt("统一帧率 FPS", "10"));
                      if (fps > 0 && fps <= 1000)
                        edit((state) => {
                          const ms = Math.max(1, Math.round(1000 / fps));
                          state.frames.forEach((f) => (f.duration_ms = ms));
                          state.tracks
                            .filter(
                              (t) =>
                                t.kind === "character" &&
                                t.exposures.length === state.frames.length,
                            )
                            .forEach((t) =>
                              t.exposures.forEach((e) => (e.duration_ms = ms)),
                            );
                        });
                    }}
                  >
                    统一帧率
                  </button>
                </div>
                <div className="frames">
                  {s.frames.map((f, i) =>
                    problemOnly && f.status !== "problem" ? null : (
                      <button
                        key={f.id}
                        className={
                          "frame-card " +
                          (frame?.id === f.id ? "selected" : "") +
                          " " +
                          f.status
                        }
                        onClick={() => {
                          setSequenceMode(false);
                          setPlaying(false);
                          setTime(frameTimes(s)[i]);
                        }}
                      >
                        <img
                          src={`/api/v1/versions/${version.id}/render?time_ms=${frameTimes(s)[i]}&r=${version.revision}`}
                          alt=""
                        />
                        <div>
                          <strong>F{String(i + 1).padStart(3, "0")}</strong>
                          <span>{f.duration_ms}ms</span>
                        </div>
                        <small>
                          {labels[f.status]}
                          {f.events.length ? " · ◆" : ""}
                        </small>
                      </button>
                    ),
                  )}
                </div>
                <div className="tracks">
                  {s.tracks.map((t, i) => (
                    <div
                      key={t.id}
                      className={
                        "track-row " + (trackId === t.id ? "selected" : "")
                      }
                    >
                      <button
                        className="track-name"
                        onClick={() => setTrackId(t.id)}
                      >
                        <span>
                          {t.kind === "effect"
                            ? "✦"
                            : t.kind === "reference"
                              ? "◇"
                              : "◉"}{" "}
                          {t.name}
                        </span>
                        <small>{t.exposures.length} 帧</small>
                      </button>
                      <button
                        title="显示/隐藏"
                        onClick={() =>
                          edit((state) => {
                            state.tracks[i].visible = !t.visible;
                          })
                        }
                      >
                        {t.visible ? "●" : "○"}
                      </button>
                      <div
                        className="exposures"
                        style={{
                          paddingLeft: `${total(s) ? (t.start_ms / total(s)) * 100 : 0}%`,
                        }}
                      >
                        {t.exposures.map((e, ei) => (
                          <button
                            key={e.id}
                            className={
                              exposure?.id === e.id && trackId === t.id
                                ? "current"
                                : ""
                            }
                            title={`E${ei + 1} · ${e.duration_ms}ms`}
                            style={{ flex: `${e.duration_ms} 0 18px` }}
                            onClick={() => {
                              setTrackId(t.id);
                              setPlaying(false);
                              setTime(
                                t.start_ms +
                                  t.exposures
                                    .slice(0, ei)
                                    .reduce((n, e) => n + e.duration_ms, 0),
                              );
                            }}
                          >
                            <img src={imageUrl(e.asset_id)} alt="" />
                            <span>E{String(ei + 1).padStart(3, "0")}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </main>
            <aside className="inspector">
              <div className="tabs">
                {[
                  ["layers", "图层"],
                  ["frame", "帧"],
                  ["spec", "规范"],
                  ["prompt", "生成"],
                  ["issues", "问题"],
                  ["exports", "导出"],
                ].map(([key, name]) => (
                  <button
                    key={key}
                    className={tab === key ? "active" : ""}
                    onClick={() => setTab(key)}
                  >
                    {name}
                  </button>
                ))}
              </div>
              <div className="inspector-body">
                {tab === "layers" && (
                  <>
                    <div className="section-head">
                      <h3>图层合成</h3>
                      <button
                        onClick={() => {
                          setImportOpen(true);
                          setSliceAsset(null);
                        }}
                      >
                        导入 PNG
                      </button>
                    </div>
                    <p className="help">
                      从后向前叠加。角色和剑光各自播放，可独立定位。
                    </p>
                    <select
                      value={trackId}
                      onChange={(e) => setTrackId(e.target.value)}
                    >
                      <option value="">选择图层</option>
                      {s.tracks.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                    {track && (
                      <>
                        <label className="field">
                          <span>图层名称</span>
                          <input
                            value={track.name}
                            onChange={(e) =>
                              edit((state) => {
                                state.tracks.find(
                                  (t) => t.id === trackId,
                                )!.name = e.target.value;
                              })
                            }
                          />
                        </label>
                        <div className="row">
                          <label>
                            <input
                              type="checkbox"
                              checked={track.visible}
                              onChange={(e) =>
                                edit((state) => {
                                  state.tracks.find(
                                    (t) => t.id === trackId,
                                  )!.visible = e.target.checked;
                                })
                              }
                            />
                            显示
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              checked={track.locked}
                              onChange={(e) =>
                                edit((state) => {
                                  state.tracks.find(
                                    (t) => t.id === trackId,
                                  )!.locked = e.target.checked;
                                })
                              }
                            />
                            锁定
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              checked={track.export}
                              onChange={(e) =>
                                edit((state) => {
                                  state.tracks.find(
                                    (t) => t.id === trackId,
                                  )!.export = e.target.checked;
                                })
                              }
                            />
                            导出
                          </label>
                        </div>
                        <div className="row">
                          <button
                            onClick={() =>
                              edit((state) => {
                                const i = state.tracks.findIndex(
                                  (t) => t.id === trackId,
                                );
                                if (i > 0)
                                  [state.tracks[i - 1], state.tracks[i]] = [
                                    state.tracks[i],
                                    state.tracks[i - 1],
                                  ];
                              })
                            }
                          >
                            后移一层
                          </button>
                          <button
                            onClick={() =>
                              edit((state) => {
                                const i = state.tracks.findIndex(
                                  (t) => t.id === trackId,
                                );
                                if (i < state.tracks.length - 1)
                                  [state.tracks[i + 1], state.tracks[i]] = [
                                    state.tracks[i],
                                    state.tracks[i + 1],
                                  ];
                              })
                            }
                          >
                            前移一层
                          </button>
                        </div>
                        <NumberField
                          label="起始时间 ms"
                          value={track.start_ms}
                          min={0}
                          onChange={(n) =>
                            edit((state) => {
                              state.tracks.find(
                                (t) => t.id === trackId,
                              )!.start_ms = n;
                            })
                          }
                        />
                        <label className="field">
                          <span>播放结束</span>
                          <select
                            value={track.end_behavior}
                            onChange={(e) =>
                              edit((state) => {
                                state.tracks.find(
                                  (t) => t.id === trackId,
                                )!.end_behavior = e.target.value as any;
                              })
                            }
                          >
                            <option value="hide">隐藏</option>
                            <option value="hold">保持最后帧</option>
                            <option value="loop">循环</option>
                          </select>
                        </label>
                        <label className="field">
                          <span>变换范围</span>
                          <select
                            value={scope}
                            onChange={(e) => setScope(e.target.value)}
                          >
                            <option value="track">整个片段</option>
                            <option value="exposure">
                              当前曝光{" "}
                              {exposure
                                ? "E" + (track.exposures.indexOf(exposure) + 1)
                                : "（当前无素材）"}
                            </option>
                          </select>
                        </label>
                        <div className="grid2">
                          <NumberField
                            label="X 偏移 px"
                            value={tr.dx}
                            onChange={(n) => transformEdit("dx", n)}
                          />
                          <NumberField
                            label="Y 偏移 px"
                            value={tr.dy}
                            onChange={(n) => transformEdit("dy", n)}
                          />
                          <NumberField
                            label="缩放"
                            value={tr.scale}
                            min={0.01}
                            step={0.01}
                            onChange={(n) => transformEdit("scale", n)}
                          />
                          <NumberField
                            label="旋转 °"
                            value={tr.rotation}
                            onChange={(n) => transformEdit("rotation", n)}
                          />
                          <NumberField
                            label="锚点 X"
                            value={
                              tr.anchor_x ??
                              (assets.find((a) => a.id === exposure?.asset_id)
                                ?.width || 0) / 2
                            }
                            step={0.5}
                            onChange={(n) => transformEdit("anchor_x", n)}
                          />
                          <NumberField
                            label="锚点 Y"
                            value={
                              tr.anchor_y ??
                              assets.find((a) => a.id === exposure?.asset_id)
                                ?.height ??
                              0
                            }
                            step={0.5}
                            onChange={(n) => transformEdit("anchor_y", n)}
                          />
                        </div>
                        <NumberField
                          label="透明度"
                          value={tr.opacity}
                          min={0}
                          step={0.05}
                          onChange={(n) => transformEdit("opacity", n)}
                        />
                        <div className="row">
                          <label>
                            <input
                              type="checkbox"
                              checked={tr.flip_x}
                              onChange={(e) =>
                                transformEdit("flip_x", e.target.checked)
                              }
                            />
                            水平翻转
                          </label>
                          <label>
                            <input
                              type="checkbox"
                              checked={tr.flip_y}
                              onChange={(e) =>
                                transformEdit("flip_y", e.target.checked)
                              }
                            />
                            垂直翻转
                          </label>
                        </div>
                        {scope === "exposure" && exposure && (
                          <>
                            <NumberField
                              label="曝光时长 ms"
                              value={exposure.duration_ms}
                              min={1}
                              onChange={(n) =>
                                edit((state) => {
                                  state.tracks
                                    .find((t) => t.id === trackId)!
                                    .exposures.find(
                                      (e) => e.id === exposure.id,
                                    )!.duration_ms = n;
                                })
                              }
                            />
                            <div className="row">
                              <button
                                onClick={() =>
                                  edit((state) => {
                                    const t = state.tracks.find(
                                      (t) => t.id === trackId,
                                    )!;
                                    const i = t.exposures.findIndex(
                                      (e) => e.id === exposure.id,
                                    );
                                    t.exposures.splice(i + 1, 0, {
                                      ...structuredClone(exposure),
                                      id: id(),
                                    });
                                  })
                                }
                              >
                                复制曝光
                              </button>
                              <button
                                onClick={() =>
                                  edit((state) => {
                                    const t = state.tracks.find(
                                      (t) => t.id === trackId,
                                    )!;
                                    t.exposures = t.exposures.filter(
                                      (e) => e.id !== exposure.id,
                                    );
                                  })
                                }
                              >
                                删除曝光
                              </button>
                              <button
                                onClick={() => {
                                  const input = prompt(
                                    "从其他版本挑选：输入素材库 asset ID（接口或素材信息可复制）",
                                  );
                                  if (
                                    input &&
                                    assets.some((a) => a.id === input)
                                  )
                                    edit((state) => {
                                      state.tracks
                                        .find((t) => t.id === trackId)!
                                        .exposures.find(
                                          (e) => e.id === exposure.id,
                                        )!.asset_id = input;
                                    });
                                }}
                              >
                                替换素材
                              </button>
                            </div>
                          </>
                        )}
                        <button
                          className="danger"
                          onClick={() => {
                            if (confirm("删除图层？可通过保存后撤销恢复。"))
                              edit((state) => {
                                state.tracks = state.tracks.filter(
                                  (t) => t.id !== trackId,
                                );
                                state.issues.forEach((i) => {
                                  if (i.track_id === trackId) i.track_id = null;
                                });
                              });
                          }}
                        >
                          删除图层
                        </button>
                      </>
                    )}
                    <h3>项目素材库</h3>
                    <p className="help">
                      勾选素材后加入新图层，或替换当前曝光。原图与派生帧都保留。
                    </p>
                    <div className="row">
                      <select
                        value={importKind}
                        onChange={(e) => setImportKind(e.target.value as any)}
                      >
                        <option value="character">角色</option>
                        <option value="effect">特效</option>
                        <option value="reference">参考</option>
                      </select>
                      <button
                        disabled={!librarySelection.length}
                        onClick={() =>
                          appendAssets(
                            librarySelection.map((aid) =>
                              assets.find((a) => a.id === aid)!,
                            ),
                          )
                        }
                      >
                        加入图层
                      </button>
                    </div>
                    <div className="asset-library">
                      {assets.map((a) => (
                        <div key={a.id} className="asset-card">
                          <label>
                            <input
                              type="checkbox"
                              checked={librarySelection.includes(a.id)}
                              onChange={(e) =>
                                setLibrarySelection((ids) =>
                                  e.target.checked
                                    ? [...ids, a.id]
                                    : ids.filter((i) => i !== a.id),
                                )
                              }
                            />
                            <img src={imageUrl(a.id)} alt="" />
                          </label>
                          <span title={a.name}>{a.name}</span>
                          <small>
                            {a.width}×{a.height} · {a.operation}
                          </small>
                          <div>
                            <button
                              onClick={() => {
                                setSliceAsset(a);
                                setImportOpen(true);
                                setRects([]);
                              }}
                            >
                              切片
                            </button>
                            <button
                              title="复制素材定位 ID"
                              onClick={() => {
                                void navigator.clipboard.writeText(a.id);
                                setMessage("素材 ID 已复制");
                              }}
                            >
                              ID
                            </button>
                            <button
                              disabled={!exposure || !track}
                              onClick={() =>
                                edit((state) => {
                                  state.tracks
                                    .find((t) => t.id === trackId)!
                                    .exposures.find(
                                      (e) => e.id === exposure!.id,
                                    )!.asset_id = a.id;
                                })
                              }
                            >
                              替换
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
                {tab === "frame" && (
                  <>
                    <h3>当前动作帧</h3>
                    {frame ? (
                      <>
                        <p className="frame-large">
                          F
                          {String(s.frames.indexOf(frame) + 1).padStart(3, "0")}
                        </p>
                        <NumberField
                          label="动作帧时长 ms"
                          value={frame.duration_ms}
                          min={1}
                          onChange={(n) =>
                            edit((state) => {
                              const i = state.frames.findIndex(
                                (f) => f.id === frame.id,
                              );
                              state.frames[i].duration_ms = n;
                              state.tracks
                                .filter(
                                  (t) =>
                                    t.kind === "character" &&
                                    t.exposures.length === state.frames.length,
                                )
                                .forEach(
                                  (t) => (t.exposures[i].duration_ms = n),
                                );
                            })
                          }
                        />
                        <label className="field">
                          <span>检查状态</span>
                          <select
                            value={frame.status}
                            onChange={(e) =>
                              edit((state) => {
                                state.frames.find(
                                  (f) => f.id === frame.id,
                                )!.status = e.target.value as any;
                              })
                            }
                          >
                            {["pending", "passed", "problem"].map((k) => (
                              <option key={k} value={k}>
                                {labels[k as keyof typeof labels]}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="field">
                          <span>事件（逗号分隔）</span>
                          <input
                            placeholder="damage, trail-start"
                            value={frame.events.join(", ")}
                            onChange={(e) =>
                              edit((state) => {
                                state.frames.find(
                                  (f) => f.id === frame.id,
                                )!.events = e.target.value
                                  .split(",")
                                  .map((t) => t.trim())
                                  .filter(Boolean);
                              })
                            }
                          />
                        </label>
                        <h3>参考点</h3>
                        <p className="help">
                          在合成画布坐标中记录脚底或骨盆。点的移动会出现在检查报告里。
                        </p>
                        {Object.entries(frame.points).map(([name, pt]) => (
                          <div key={name}>
                            <strong>{name}</strong>
                            <div className="grid2">
                              <NumberField
                                label="X"
                                value={pt[0]}
                                onChange={(n) =>
                                  edit((state) => {
                                    state.frames.find(
                                      (f) => f.id === frame.id,
                                    )!.points[name][0] = n;
                                  })
                                }
                              />
                              <NumberField
                                label="Y"
                                value={pt[1]}
                                onChange={(n) =>
                                  edit((state) => {
                                    state.frames.find(
                                      (f) => f.id === frame.id,
                                    )!.points[name][1] = n;
                                  })
                                }
                              />
                            </div>
                          </div>
                        ))}
                        <button
                          onClick={() => {
                            const name = prompt("参考点名称", "脚底");
                            if (name)
                              edit((state) => {
                                state.frames.find(
                                  (f) => f.id === frame.id,
                                )!.points[name] = [
                                  state.canvas.pivot_x,
                                  state.canvas.pivot_y,
                                ];
                              });
                          }}
                        >
                          ＋ 参考点
                        </button>
                        <div className="row">
                          <button
                            onClick={() =>
                              edit((state) => {
                                const i = state.frames.findIndex(
                                  (f) => f.id === frame.id,
                                );
                                if (i > 0) {
                                  [state.frames[i - 1], state.frames[i]] = [
                                    state.frames[i],
                                    state.frames[i - 1],
                                  ];
                                  state.tracks
                                    .filter(
                                      (t) =>
                                        t.kind === "character" &&
                                        t.exposures.length ===
                                          state.frames.length,
                                    )
                                    .forEach((t) => {
                                      [t.exposures[i - 1], t.exposures[i]] = [
                                        t.exposures[i],
                                        t.exposures[i - 1],
                                      ];
                                    });
                                }
                              })
                            }
                          >
                            向前一帧
                          </button>
                          <button
                            onClick={() =>
                              edit((state) => {
                                const i = state.frames.findIndex(
                                  (f) => f.id === frame.id,
                                );
                                if (i < state.frames.length - 1) {
                                  [state.frames[i + 1], state.frames[i]] = [
                                    state.frames[i],
                                    state.frames[i + 1],
                                  ];
                                  state.tracks
                                    .filter(
                                      (t) =>
                                        t.kind === "character" &&
                                        t.exposures.length ===
                                          state.frames.length,
                                    )
                                    .forEach((t) => {
                                      [t.exposures[i + 1], t.exposures[i]] = [
                                        t.exposures[i],
                                        t.exposures[i + 1],
                                      ];
                                    });
                                }
                              })
                            }
                          >
                            向后一帧
                          </button>
                        </div>
                        <button
                          onClick={() =>
                            void navigator.clipboard.writeText(
                              `${version.name} / F${s.frames.indexOf(frame) + 1} / frame_id=${frame.id}`,
                            )
                          }
                        >
                          复制协作定位
                        </button>
                      </>
                    ) : (
                      <p>导入动作或添加动作帧。</p>
                    )}
                    <h3>播放与对比</h3>
                    <div className="grid2">
                      <NumberField
                        label="前帧数量"
                        value={before}
                        min={0}
                        onChange={(n) => setBefore(Math.min(5, n))}
                      />
                      <NumberField
                        label="后帧数量"
                        value={after}
                        min={0}
                        onChange={(n) => setAfter(Math.min(5, n))}
                      />
                    </div>
                    <NumberField
                      label="洋葱皮透明度"
                      value={onionOpacity}
                      min={0}
                      step={0.05}
                      onChange={setOnionOpacity}
                    />
                    <label>
                      <input
                        type="checkbox"
                        checked={onionLayer}
                        onChange={(e) => setOnionLayer(e.target.checked)}
                      />
                      只叠加选中图层
                    </label>
                    <label className="field">
                      <span>比较版本</span>
                      <select
                        value={compareId}
                        onChange={(e) => setCompareId(e.target.value)}
                      >
                        <option value="">关闭对比</option>
                        {catalog.versions
                          .filter((v) => v.id !== version.id)
                          .map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.name} ·{" "}
                              {
                                catalog.objects.find(
                                  (o) => o.id === v.action_id,
                                )?.name
                              }
                            </option>
                          ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>自定义背景图</span>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file)
                            setBackgroundImage(URL.createObjectURL(file));
                        }}
                      />
                    </label>
                    <button onClick={() => setBackgroundImage("")}>
                      清除背景图
                    </button>
                    <h3>动作切换预览</h3>
                    <p className="help">
                      按顺序加入待机、攻击、待机；仅用于查看衔接。
                    </p>
                    <select
                      value=""
                      onChange={(e) => {
                        if (e.target.value)
                          setSequenceIds((ids) => [...ids, e.target.value]);
                      }}
                    >
                      <option value="">添加一个动作版本</option>
                      {catalog.versions.map((v) => (
                        <option key={v.id} value={v.id}>
                          {
                            catalog.objects.find((o) => o.id === v.action_id)
                              ?.name
                          }{" "}
                          / {v.name}
                        </option>
                      ))}
                    </select>
                    <ol>
                      {sequence.map((v, i) => (
                        <li key={i}>
                          {v.name}
                          <button
                            onClick={() =>
                              setSequenceIds((ids) =>
                                ids.filter((_, j) => j !== i),
                              )
                            }
                          >
                            ×
                          </button>
                        </li>
                      ))}
                    </ol>
                    <label>
                      <input
                        type="checkbox"
                        checked={sequenceMode}
                        onChange={(e) => {
                          setPlaying(false);
                          setTime(0);
                          setSequenceMode(e.target.checked);
                        }}
                      />
                      播放拼接序列
                    </label>
                  </>
                )}
                {tab === "spec" && (
                  <>
                    <h3>输出画布</h3>
                    <p className="help">
                      身体目标尺寸与整帧尺寸独立。调整画布后请检查所有动作是否越界。
                    </p>
                    <div className="grid2">
                      <NumberField
                        label="画布宽 px"
                        value={s.canvas.width}
                        min={1}
                        onChange={(n) =>
                          edit((state) => {
                            state.canvas.width = n;
                          })
                        }
                      />
                      <NumberField
                        label="画布高 px"
                        value={s.canvas.height}
                        min={1}
                        onChange={(n) =>
                          edit((state) => {
                            state.canvas.height = n;
                          })
                        }
                      />
                      <NumberField
                        label="Pivot X"
                        value={s.canvas.pivot_x}
                        onChange={(n) =>
                          edit((state) => {
                            state.canvas.pivot_x = n;
                          })
                        }
                      />
                      <NumberField
                        label="Pivot Y"
                        value={s.canvas.pivot_y}
                        onChange={(n) =>
                          edit((state) => {
                            state.canvas.pivot_y = n;
                          })
                        }
                      />
                    </div>
                    <NumberField
                      label="地面线 Y"
                      value={s.canvas.ground_y}
                      onChange={(n) =>
                        edit((state) => {
                          state.canvas.ground_y = n;
                        })
                      }
                    />
                    <h3>角色身体精度</h3>
                    <div className="grid2">
                      <NumberField
                        label="目标身体宽 px"
                        value={s.body.width}
                        min={1}
                        onChange={(n) =>
                          edit((state) => {
                            state.body.width = n;
                          })
                        }
                      />
                      <NumberField
                        label="目标身体高 px"
                        value={s.body.height}
                        min={1}
                        onChange={(n) =>
                          edit((state) => {
                            state.body.height = n;
                          })
                        }
                      />
                    </div>
                    <p className="help">
                      填写原素材中身体的参考框，排除武器和特效。全序列按同一比例适配，保持体型。
                    </p>
                    <div className="grid2">
                      {(["x", "y", "width", "height"] as const).map((k) => (
                        <NumberField
                          key={k}
                          label={"参考框 " + k}
                          value={
                            s.body.reference_rect?.[k] ??
                            (k === "width" ? 100 : k === "height" ? 250 : 0)
                          }
                          min={k === "width" || k === "height" ? 1 : undefined}
                          onChange={(n) =>
                            edit((state) => {
                              state.body.reference_rect = {
                                x: 0,
                                y: 0,
                                width: 100,
                                height: 250,
                                ...state.body.reference_rect,
                                [k]: n,
                              };
                            })
                          }
                        />
                      ))}
                    </div>
                    <button
                      onClick={() =>
                        edit((state) => {
                          const a = assets.find(
                            (a) => a.id === exposure?.asset_id,
                          );
                          if (a)
                            state.body.reference_rect = {
                              x: 0,
                              y: 0,
                              width: a.width,
                              height: a.height,
                            };
                        })
                      }
                    >
                      使用整张素材作参考框
                    </button>
                    <label className="field">
                      <span>缩小方式</span>
                      <select
                        value={method}
                        onChange={(e) => setMethod(e.target.value)}
                      >
                        <option value="nearest">最近邻 · 保留硬边</option>
                        <option value="smooth">平滑重采样 · 细节对比</option>
                      </select>
                    </label>
                    <NumberField
                      label="调色板颜色数（0不限制）"
                      value={colors}
                      min={0}
                      onChange={setColors}
                    />
                    <label>
                      <input
                        type="checkbox"
                        checked={dither}
                        onChange={(e) => setDither(e.target.checked)}
                      />
                      颜色转换时使用抖动
                    </label>
                    {s.body.reference_rect && (
                      <p className="help">
                        适配比例{" "}
                        {Math.min(
                          s.body.width / s.body.reference_rect.width,
                          s.body.height / s.body.reference_rect.height,
                        ).toFixed(3)}{" "}
                        · 保持比例，不拉伸。
                      </p>
                    )}
                    <button
                      className="primary"
                      disabled={!track || busy}
                      onClick={() => void task(convert)}
                    >
                      转换当前图层全部帧
                    </button>
                    <p className="help">
                      产生新素材，可撤销。高精度图片缩小后仍需检查眼睛、手指和武器细节。
                    </p>
                    <button onClick={() => void task(validateRun)}>
                      检查格式与越界
                    </button>
                  </>
                )}
                {tab === "prompt" && (
                  <>
                    <h3>生成方案</h3>
                    <p className="help">
                      在这里确定文本与参考图。保存请求后，Codex
                      读取快照、生成并回传。
                    </p>
                    {[
                      ["identity", "角色固定设定"],
                      ["motion", "动作说明"],
                      ["frame_notes", "逐帧说明"],
                      ["changes", "本次修改要求"],
                    ].map(([key, name]) => (
                      <label className="field" key={key}>
                        <span>{name}</span>
                        <textarea
                          rows={3}
                          value={(s.prompt as any)[key]}
                          onChange={(e) =>
                            edit((state) => {
                              (state.prompt as any)[key] = e.target.value;
                            })
                          }
                        />
                      </label>
                    ))}
                    <h4>参考图</h4>
                    <div className="reference-picker">
                      {assets
                        .filter(
                          (a) =>
                            !a.parent_id ||
                            s.prompt.reference_ids.includes(a.id),
                        )
                        .map((a) => (
                          <label key={a.id}>
                            <input
                              type="checkbox"
                              checked={s.prompt.reference_ids.includes(a.id)}
                              onChange={(e) =>
                                edit((state) => {
                                  state.prompt.reference_ids = e.target.checked
                                    ? [...state.prompt.reference_ids, a.id]
                                    : state.prompt.reference_ids.filter(
                                        (i) => i !== a.id,
                                      );
                                })
                              }
                            />
                            <img src={imageUrl(a.id)} alt="" />
                            <span>{a.name}</span>
                          </label>
                        ))}
                    </div>
                    <button onClick={composePrompt}>组合提示词</button>
                    <label className="field">
                      <span>最终提示词（可直接编辑）</span>
                      <textarea
                        rows={9}
                        value={s.prompt.final_text}
                        onChange={(e) =>
                          edit((state) => {
                            state.prompt.final_text = e.target.value;
                          })
                        }
                      />
                    </label>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() =>
                        void task(async () => {
                          const v = await save();
                          const req = await api("/generation-requests", {
                            version_id: v.id,
                            expected_revision: v.revision,
                          });
                          setRequests((r) => [req, ...r]);
                          setMessage("生成方案已冻结为快照，可通知 Codex 读取");
                        })
                      }
                    >
                      保存为待生成请求
                    </button>
                    <h3>生成记录</h3>
                    {requests
                      .filter((r) => r.project_id === version.project_id)
                      .map((r) => (
                        <div className="record" key={r.id}>
                          <strong>
                            {r.id.slice(0, 8)} ·{" "}
                            {
                              (
                                {
                                  pending: "待生成",
                                  claimed: "已领取",
                                  completed: "已回传",
                                  failed: "失败",
                                  cancelled: "已取消",
                                } as any
                              )[r.status]
                            }
                          </strong>
                          <small>版本 r{r.revision}</small>
                          <button
                            onClick={() => {
                              void navigator.clipboard.writeText(r.id);
                              setMessage("生成请求 ID 已复制");
                            }}
                          >
                            复制 ID
                          </button>
                          {r.asset_ids?.length > 0 && (
                            <button
                              onClick={() => {
                                appendAssets(
                                  r.asset_ids
                                    .map((aid: string) =>
                                      assets.find((a) => a.id === aid),
                                    )
                                    .filter(Boolean),
                                );
                                setTab("layers");
                              }}
                            >
                              结果加入图层
                            </button>
                          )}
                          {r.status === "pending" && (
                            <button
                              onClick={() =>
                                void task(async () => {
                                  await api(
                                    `/generation-requests/${r.id}/status`,
                                    { status: "cancelled" },
                                  );
                                  setRequests(
                                    await api("/generation-requests"),
                                  );
                                })
                              }
                            >
                              取消
                            </button>
                          )}
                        </div>
                      ))}
                  </>
                )}
                {tab === "issues" && (
                  <>
                    <h3>标记问题</h3>
                    <p className="help">
                      指定帧、图层和区域，避免只说“这一帧不对”。插帧后记录仍跟随原帧。
                    </p>
                    <select
                      value={issueTag}
                      onChange={(e) => setIssueTag(e.target.value)}
                    >
                      {[
                        "姿势",
                        "武器变化",
                        "漂移",
                        "衔接",
                        "遮挡",
                        "杂色",
                        "裁切",
                        "其他",
                      ].map((k) => (
                        <option key={k}>{k}</option>
                      ))}
                    </select>
                    <textarea
                      rows={4}
                      placeholder="描述需要修改的地方…"
                      value={issueNote}
                      onChange={(e) => setIssueNote(e.target.value)}
                    />
                    {issueRect && (
                      <div className="help">
                        区域：{issueRect.x},{issueRect.y} · {issueRect.width}×
                        {issueRect.height}{" "}
                        <button onClick={() => setIssueRect(null)}>清除</button>
                      </div>
                    )}
                    <div className="row">
                      <button
                        onClick={() => {
                          setPixel(false);
                          setTool("issue");
                        }}
                      >
                        在画布框选
                      </button>
                      <button
                        className="primary"
                        disabled={!frame}
                        onClick={addIssue}
                      >
                        标记当前帧
                      </button>
                    </div>
                    <h3>问题清单</h3>
                    <select
                      value={tagFilter}
                      onChange={(e) => setTagFilter(e.target.value)}
                    >
                      <option value="">全部标签</option>
                      {[...new Set(s.issues.map((i) => i.tag))].map((k) => (
                        <option key={k}>{k}</option>
                      ))}
                    </select>
                    {s.issues
                      .filter((i) => !tagFilter || i.tag === tagFilter)
                      .map((issue) => (
                        <div className="issue-card" key={issue.id}>
                          <div>
                            <strong>
                              F
                              {String(
                                s.frames.findIndex(
                                  (f) => f.id === issue.frame_id,
                                ) + 1,
                              ).padStart(3, "0")}{" "}
                              · {issue.tag}
                            </strong>
                            <span>{labels[issue.status]}</span>
                          </div>
                          <p>{issue.note || "待补充说明"}</p>
                          {issue.rect && (
                            <small>
                              区域 {issue.rect.x},{issue.rect.y} /{" "}
                              {issue.rect.width}×{issue.rect.height}
                            </small>
                          )}
                          <div className="row">
                            <button
                              onClick={() => {
                                setPlaying(false);
                                setTime(
                                  frameTimes(s)[
                                    s.frames.findIndex(
                                      (f) => f.id === issue.frame_id,
                                    )
                                  ],
                                );
                                setTrackId(issue.track_id || trackId);
                                setIssueRect(issue.rect);
                              }}
                            >
                              定位
                            </button>
                            <button
                              onClick={() =>
                                edit((state) => {
                                  state.issues.find(
                                    (i) => i.id === issue.id,
                                  )!.status =
                                    issue.status === "resolved"
                                      ? "open"
                                      : "resolved";
                                })
                              }
                            >
                              {issue.status === "resolved"
                                ? "重新打开"
                                : "标记解决"}
                            </button>
                            <button
                              onClick={() =>
                                void navigator.clipboard.writeText(
                                  `${version.name} / ${issue.frame_id} / ${issue.tag}: ${issue.note}`,
                                )
                              }
                            >
                              复制
                            </button>
                          </div>
                        </div>
                      ))}
                  </>
                )}
                {tab === "exports" && (
                  <>
                    <h3>检查与导出</h3>
                    <div className="row">
                      <button onClick={() => void task(validateRun)}>
                        运行检查
                      </button>
                      <button
                        onClick={() => {
                          setAuthoritative(!authoritative);
                          setPixel(false);
                        }}
                      >
                        {authoritative ? "关闭" : "显示"}后端预览
                      </button>
                    </div>
                    {dirty && (
                      <p className="help">
                        后端预览显示已保存状态，保存后更新。
                      </p>
                    )}
                    <label className="field">
                      <span>版本状态</span>
                      <select
                        value={s.status}
                        onChange={(e) =>
                          edit((state) => {
                            state.status = e.target.value as any;
                          })
                        }
                      >
                        {["draft", "candidate", "accepted"].map((k) => (
                          <option key={k} value={k}>
                            {labels[k as keyof typeof labels]}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>导出时序</span>
                      <select
                        value={exportMode}
                        onChange={(e) => setExportMode(e.target.value)}
                      >
                        <option value="union">
                          保留角色与特效的全部曝光变化
                        </option>
                        <option value="fixed">指定固定帧数（时间采样）</option>
                      </select>
                    </label>
                    {exportMode === "fixed" && (
                      <>
                        <NumberField
                          label="输出帧数"
                          value={exportCount}
                          min={1}
                          onChange={setExportCount}
                        />
                        <p className="help">
                          可能漏掉更短的特效变化。请先查看目标时序。
                        </p>
                      </>
                    )}
                    <label>
                      <input
                        type="checkbox"
                        checked={exportLayers}
                        onChange={(e) => setExportLayers(e.target.checked)}
                      />
                      同时导出独立图层
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={allowClip}
                        onChange={(e) => setAllowClip(e.target.checked)}
                      />
                      允许裁切越界部分（默认阻止）
                    </label>
                    <button
                      className="primary"
                      disabled={busy}
                      onClick={() => void task(exportRun)}
                    >
                      导出 PNG 与描述文件
                    </button>
                    {report && (
                      <div className="validation">
                        <strong>
                          {report.errors.length
                            ? "检查发现问题"
                            : "格式检查通过"}{" "}
                          · r{report.revision}
                        </strong>
                        <p>
                          {report.frame_count}帧 · {report.duration_ms}ms
                        </p>
                        {report.errors.map((m: string, i: number) => (
                          <p className="error" key={i}>
                            {m}
                          </p>
                        ))}
                        {report.warnings.map((m: string, i: number) => (
                          <p className="warning-text" key={i}>
                            {m}
                          </p>
                        ))}
                        <p className="help">
                          动作合理性与武器一致性需人工检查。
                        </p>
                      </div>
                    )}
                    <h3>任务记录</h3>
                    {jobs
                      .filter((j) => j.version_id === version.id)
                      .map((j) => (
                        <div className="record" key={j.id}>
                          <strong>
                            {j.kind === "export" ? "素材导出" : "精度转换"} ·{" "}
                            {
                              (
                                {
                                  queued: "等待",
                                  running: "进行中",
                                  completed: "完成",
                                  failed: "失败",
                                  cancelled: "已取消",
                                  interrupted: "中断",
                                } as any
                              )[j.status]
                            }
                          </strong>
                          <progress max={100} value={j.progress} />
                          {j.error && <p className="error">{j.error}</p>}
                          {j.result?.download_url && (
                            <a
                              className="download"
                              href={j.result.download_url}
                            >
                              下载素材包 ↗
                            </a>
                          )}
                          {["queued", "running"].includes(j.status) && (
                            <button
                              onClick={() =>
                                void task(async () => {
                                  await api(`/jobs/${j.id}/cancel`, {});
                                })
                              }
                            >
                              取消
                            </button>
                          )}
                        </div>
                      ))}
                    <h3>操作记录</h3>
                    <button
                      onClick={() =>
                        void task(async () =>
                          setHistory(
                            await api(`/versions/${version.id}/history`),
                          ),
                        )
                      }
                    >
                      读取记录
                    </button>
                    {history.slice(0, 20).map((h) => (
                      <p className="help" key={h.id}>
                        r{h.revision} · {h.actor} · {h.operation}
                      </p>
                    ))}
                    <a
                      href={`/api/v1/versions/${version.id}/contact-sheet`}
                      target="_blank"
                    >
                      打开动作联系表 ↗
                    </a>
                  </>
                )}
              </div>
            </aside>
          </>
        )}
      </div>
      {importOpen && version && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="section-head">
              <h2>导入与切片</h2>
              <button onClick={() => setImportOpen(false)}>关闭</button>
            </div>
            <div className="row">
              <label>
                素材类型{" "}
                <select
                  value={importKind}
                  onChange={(e) => setImportKind(e.target.value as any)}
                >
                  <option value="character">角色动作</option>
                  <option value="effect">独立特效</option>
                  <option value="reference">参考图</option>
                </select>
              </label>
              <label className="upload-button">
                选择 PNG（可多选）
                <input
                  type="file"
                  multiple
                  accept="image/png"
                  onChange={(e) => void task(() => upload(e.target.files))}
                />
              </label>
            </div>
            <p className="help">
              多张图片按选择顺序加入序列；单张图片可直接使用或切片。原图保留。
            </p>
            {sliceAsset && (
              <>
                <p>
                  {sliceAsset.name} · {sliceAsset.width}×{sliceAsset.height} ·{" "}
                  {sliceAsset.transparent_pixels
                    ? "含透明像素"
                    : "没有完全透明像素，请检查背景"}
                </p>
                <div className="row">
                  <label>
                    <input
                      type="checkbox"
                      checked={manual}
                      onChange={(e) => setManual(e.target.checked)}
                    />
                    手动框选切片
                  </label>
                  <button onClick={() => appendAssets([sliceAsset])}>
                    整张作为单帧加入
                  </button>
                </div>
                {!manual ? (
                  <div className="slice-settings">
                    {[
                      ["列", columns, setColumns],
                      ["行", rows, setRows],
                      ["边距", margin, setMargin],
                      ["间距", spacing, setSpacing],
                      ["格宽（0自动）", cellWidth, setCellWidth],
                      ["格高（0自动）", cellHeight, setCellHeight],
                    ].map(([name, value, setter]) => (
                      <NumberField
                        key={name as string}
                        label={name as string}
                        value={value as number}
                        onChange={setter as any}
                        min={0}
                      />
                    ))}
                    <select
                      value={sliceOrder}
                      onChange={(e) => setSliceOrder(e.target.value)}
                    >
                      <option value="row">先行后列</option>
                      <option value="column">先列后行</option>
                    </select>
                  </div>
                ) : (
                  <div className="row">
                    <span>{rects.length}个切片框，在预览上拖动添加。</span>
                    <button onClick={() => setRects((r) => r.slice(0, -1))}>
                      撤销框选
                    </button>
                    <button onClick={() => setRects([])}>清空</button>
                  </div>
                )}
                <div className="slice-preview checker">
                  <canvas
                    ref={sliceCanvas}
                    onPointerDown={(e) => {
                      if (!manual) return;
                      sliceStart.current = pointerSlice(e);
                      e.currentTarget.setPointerCapture(e.pointerId);
                    }}
                    onPointerUp={(e) => {
                      if (!sliceStart.current) return;
                      const at = pointerSlice(e),
                        from = sliceStart.current;
                      sliceStart.current = null;
                      setRects((r) => [
                        ...r,
                        {
                          x: Math.min(at.x, from.x),
                          y: Math.min(at.y, from.y),
                          width: Math.max(1, Math.abs(at.x - from.x)),
                          height: Math.max(1, Math.abs(at.y - from.y)),
                        },
                      ]);
                    }}
                  />
                </div>
                {manual &&
                  rects.map((r, i) => (
                    <div className="manual-rect" key={i}>
                      <span>F{i + 1}</span>
                      {(["x", "y", "width", "height"] as const).map((k) => (
                        <NumberField
                          key={k}
                          label={k}
                          value={r[k]}
                          onChange={(n) =>
                            setRects((rects) =>
                              rects.map((r, j) =>
                                i === j ? { ...r, [k]: n } : r,
                              ),
                            )
                          }
                        />
                      ))}
                    </div>
                  ))}
                <button
                  className="primary"
                  disabled={busy || (manual && !rects.length)}
                  onClick={() => void task(slicing)}
                >
                  生成切片并加入图层
                </button>
                {sliceWarnings.map((m, i) => (
                  <p className="warning-text" key={i}>
                    {m}
                  </p>
                ))}
              </>
            )}
          </div>
        </div>
      )}
      <footer className="footer">
        <span>{busy ? "正在处理…" : "本地工作台 · 原图保留"}</span>
        <span>
          {version
            ? `${s?.frames.length || 0}动作帧 · ${s?.tracks.length || 0}图层 · r${version.revision}`
            : "127.0.0.1:18765"}
        </span>
      </footer>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
