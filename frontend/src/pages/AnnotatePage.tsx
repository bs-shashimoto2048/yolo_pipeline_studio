// アノテーション画面（Konva）。プロジェクトの task により UI を切り替える。
// - detect: 矩形(bbox)の作成・選択・移動・サイズ変更・削除
// - segment: polygon（輪郭）の頂点追加・確定・選択・削除
//
// 内部管理は「画像基準の正規化座標(0〜1)」。表示サイズはブラウザ幅に追従して伸縮し、
// 正規化座標なので拡大縮小しても位置は保たれる。保存時はそのままYOLO正規化形式へ。
//
// bbox選択中はTransformerのハンドルを使わず、辺・角に近づくとカーソルが伸縮方向の
// 両矢印に変わりドラッグでリサイズ、枠内は手カーソルでドラッグ移動できる。
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Circle,
  Group,
  Image as KonvaImage,
  Layer,
  Line,
  Rect,
  Stage,
  Text,
} from "react-konva";
import type Konva from "konva";
import { api } from "../api/client";
import type {
  AnnotationItem,
  ClassItem,
  ImageInfo,
  PolygonItem,
  ProjectTask,
  SamCandidate,
  SamSettings,
} from "../types";

type SegMode = "manual" | "sam_box" | "sam_point";
const SEG_MODE_LABELS: Record<SegMode, string> = {
  manual: "手動Polygon",
  sam_box: "SAM Box",
  sam_point: "SAM Point",
};

// 手動polygon編集用のカスタム矢印カーソル（tipを左上に）。編集中=青、頂点ドラッグ中=緑。
function arrowCursor(color: string): string {
  const svg =
    "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'>" +
    `<path d='M3 2 L3 19 L8 14 L11.2 21 L14 20 L10.8 13.2 L18 13 Z' fill='${color}' ` +
    "stroke='white' stroke-width='1.3' stroke-linejoin='round'/></svg>";
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}") 3 2, default`;
}
const CURSOR_MANUAL = "default"; // 通常色（黒）＝手動編集の基本カーソル
const CURSOR_VERTEX_DRAG = arrowCursor("#39ff5e"); // 蛍光グリーン（頂点ドラッグ中）
const CURSOR_VERTEX_HOVER = arrowCursor("#ff2d2d"); // 赤（頂点ホバー時）
const CURSOR_VERTEX_HOVER_ALT = arrowCursor("#ffffff"); // 点滅用の白

// 正規化座標(0〜1)の矩形。x,y は左上、w,h は幅高さ。
interface Box {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  classId: number;
}

// 正規化座標(0〜1)の polygon。
interface Poly {
  id: string;
  classId: number;
  points: { x: number; y: number }[];
  source: string;
}

// リサイズ操作の掴んだ位置
type Handle = "left" | "right" | "top" | "bottom" | "tl" | "tr" | "bl" | "br";
type Zone = Handle | "inside" | null;

const FALLBACK_COLOR = "#1677ff";
const HANDLE_PX = 8; // 辺・角の判定しきい値（画面px）

const SOURCE_LABELS: Record<string, string> = {
  auto: "自動（前処理済みを優先）",
  raw: "元画像（未処理）",
  processed: "前処理済み画像",
};

// #RRGGBB → rgba(r,g,b,a)
function hexToRgba(hex: string, alpha: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return `rgba(22,119,255,${alpha})`;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

const stemOf = (filename: string) => filename.replace(/\.[^./\\]+$/, "");

function cursorForZone(z: Zone, dragging: boolean): string {
  switch (z) {
    case "tl":
    case "br":
      return "nwse-resize";
    case "tr":
    case "bl":
      return "nesw-resize";
    case "left":
    case "right":
      return "ew-resize";
    case "top":
    case "bottom":
      return "ns-resize";
    case "inside":
      return dragging ? "grabbing" : "grab";
    default:
      return "default";
  }
}

// 正規化座標の点が polygon 内にあるか（ray casting）
function pointInPoly(nx: number, ny: number, pts: { x: number; y: number }[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i].x;
    const yi = pts[i].y;
    const xj = pts[j].x;
    const yj = pts[j].y;
    const intersect =
      yi > ny !== yj > ny && nx < ((xj - xi) * (ny - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export default function AnnotatePage() {
  const { name = "" } = useParams();
  const [searchParams] = useSearchParams();
  const [task, setTask] = useState<ProjectTask>("detect");
  const [images, setImages] = useState<ImageInfo[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [imgSource, setImgSource] = useState("auto"); // auto | raw | processed
  const [excludedStems, setExcludedStems] = useState<Set<string>>(new Set());
  const [hideExcluded, setHideExcluded] = useState(true);
  const [current, setCurrent] = useState(0);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [polys, setPolys] = useState<Poly[]>([]);
  const [activeClass, setActiveClass] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // segment: 選択中polygonの頂点index（null=polygon本体を選択）
  const [selectedVertexIndex, setSelectedVertexIndex] = useState<number | null>(null);
  // segment: 作成中polygonの頂点（正規化）とマウス追従点
  const [draft, setDraft] = useState<{ x: number; y: number }[]>([]);
  const [cursorPt, setCursorPt] = useState<{ x: number; y: number } | null>(null);

  // SAM支援（segmentのみ）
  const [segMode, setSegMode] = useState<SegMode>("manual");
  const [samSettings, setSamSettings] = useState<SamSettings | null>(null);
  const [samBox, setSamBox] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const [posPoints, setPosPoints] = useState<{ x: number; y: number }[]>([]);
  const [negPoints, setNegPoints] = useState<{ x: number; y: number }[]>([]);
  const [candidates, setCandidates] = useState<SamCandidate[]>([]);
  const [samBusy, setSamBusy] = useState(false);
  const [samError, setSamError] = useState("");

  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<"" | "saved" | "unsaved" | "error">("");
  const [message, setMessage] = useState("");

  const isSeg = task === "segment";

  // 新規矩形の描画中（画面px座標で保持し、確定時に正規化）
  const drawing = useRef<{ x: number; y: number; w: number; h: number; classId: number } | null>(null);
  // 移動・リサイズ操作中の状態（開始時の正規化ボックスとポインタpxを保持）
  const opRef = useRef<
    | null
    | { mode: "move" | "resize"; handle?: Handle; box: Box; px: number; py: number }
  >(null);
  // segment: 頂点ドラッグ中の対象
  const vertexDrag = useRef<{ polyId: string; index: number } | null>(null);
  // 頂点ホバー時のカーソル点滅タイマー
  const blinkTimer = useRef<number | null>(null);
  const [, force] = useState(0);
  const stageRef = useRef<Konva.Stage>(null);
  const idSeq = useRef(0);
  // 表示中の画像に合わせて左サイドバーを自動スクロールするための参照
  const activeTaskRef = useRef<HTMLButtonElement>(null);

  // 表示サイズ（ブラウザ幅に追従）
  const wrapRef = useRef<HTMLDivElement>(null);
  const [wrapW, setWrapW] = useState(800);
  const [viewportH, setViewportH] = useState(
    typeof window !== "undefined" ? window.innerHeight : 800
  );
  // ズーム（Ctrl+ホイール）とパン。zoom=1 が「幅にフィット」した基準。
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const MAX_ZOOM = 8;

  // 除外画像を非表示にした表示用リスト
  const visibleImages = useMemo(
    () =>
      hideExcluded
        ? images.filter((im) => !excludedStems.has(stemOf(im.filename)))
        : images,
    [images, hideExcluded, excludedStems]
  );

  const filename = visibleImages[current]?.filename;
  const stem = filename ? stemOf(filename) : "";
  // 表示中画像の注釈数（タスク一覧の現在カードに表示）
  const currentCount = isSeg ? polys.length : boxes.length;
  // タスクカードのホバープレビュー（カード全体でホバー→拡大画像を表示）
  const [taskPreview, setTaskPreview] = useState<{ src: string; x: number; y: number } | null>(null);
  function onTaskHover(e: React.MouseEvent, srcFile: string) {
    const w = 480;
    const h = 360;
    const x = Math.min(e.clientX + 16, window.innerWidth - (w + 16));
    const y = Math.min(Math.max(e.clientY - h / 2, 8), window.innerHeight - (h + 16));
    setTaskPreview({ src: api.imageUrl(name, srcFile, imgSource), x: Math.max(8, x), y });
  }

  // 表示サイズ計算: 幅はコンテナ幅に追従、高さは画面高の一定割合で頭打ち。
  const aspect = img ? img.height / img.width : 9 / 16;
  let viewW = Math.max(200, wrapW);
  let viewH = viewW * aspect;
  const maxH = Math.max(240, viewportH * 0.72);
  if (viewH > maxH) {
    viewH = maxH;
    viewW = viewH / aspect;
  }

  // 画像の「フィット時サイズ」= viewW/viewH（座標計算の基準はこちらで固定）。
  // ステージ（表示領域）は拡大に合わせてコンテナ幅・上限高まで広げる。
  // 縦長画像はフィット時に幅が細くなるため、拡大時に横方向の作業領域が広がって効率が上がる。
  const stageW = clamp(viewW * zoom, viewW, wrapW);
  const stageH = clamp(viewH * zoom, viewH, maxH);

  // パンの可動範囲クランプ（ズーム時にコンテンツが画面外へ飛ばないように）。
  // ステージ自体が拡大に応じて広がるので、その時々のステージ寸法を z から算出する。
  function clampPan(px: number, py: number, z: number) {
    const sW = clamp(viewW * z, viewW, wrapW);
    const sH = clamp(viewH * z, viewH, maxH);
    const minX = Math.min(0, sW - viewW * z);
    const minY = Math.min(0, sH - viewH * z);
    return { x: clamp(px, minX, 0), y: clamp(py, minY, 0) };
  }

  // ステージ座標(screen px) → コンテンツ基準px（zoom/pan を打ち消す）
  const contentPt = (px: number, py: number) => ({
    x: (px - pan.x) / zoom,
    y: (py - pan.y) / zoom,
  });
  // ステージ座標 → 正規化(0〜1)
  const normPt = (px: number, py: number) => ({
    x: clamp((px - pan.x) / zoom / viewW, 0, 1),
    y: clamp((py - pan.y) / zoom / viewH, 0, 1),
  });

  const colorOf = (classId: number): string =>
    classes.find((c) => c.id === classId)?.color ?? FALLBACK_COLOR;
  const nameOf = (classId: number): string =>
    classes.find((c) => c.id === classId)?.name ?? String(classId);

  function newId() {
    idSeq.current += 1;
    return `ann_${idSeq.current}`;
  }

  function markDirty() {
    setDirty(true);
    setStatus("unsaved");
    setMessage("");
  }

  function setCursor(c: string) {
    const s = stageRef.current;
    if (s) s.container().style.cursor = c;
  }

  // 頂点ホバー中はカーソルを赤⇔白で点滅させる（つかめる位置を強調）
  function startVertexBlink() {
    if (blinkTimer.current !== null) return; // 既に点滅中
    setCursor(CURSOR_VERTEX_HOVER);
    let on = true;
    blinkTimer.current = window.setInterval(() => {
      on = !on;
      setCursor(on ? CURSOR_VERTEX_HOVER : CURSOR_VERTEX_HOVER_ALT);
    }, 420);
  }
  function stopVertexBlink() {
    if (blinkTimer.current !== null) {
      window.clearInterval(blinkTimer.current);
      blinkTimer.current = null;
    }
  }
  // アンマウント時にタイマーを止める
  useEffect(() => () => stopVertexBlink(), []);

  // Ctrl+ホイールでカーソル位置中心にズーム。ズーム中はホイール（+Shift）でパン。
  function onWheel(e: Konva.KonvaEventObject<WheelEvent>) {
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    if (e.evt.ctrlKey) {
      e.evt.preventDefault();
      const factor = e.evt.deltaY < 0 ? 1.15 : 1 / 1.15;
      const nz = clamp(zoom * factor, 1, MAX_ZOOM);
      const cx = (pos.x - pan.x) / zoom;
      const cy = (pos.y - pan.y) / zoom;
      const np = clampPan(pos.x - cx * nz, pos.y - cy * nz, nz);
      setZoom(nz);
      setPan(nz === 1 ? { x: 0, y: 0 } : np);
    } else if (zoom > 1) {
      e.evt.preventDefault();
      const d = e.evt.deltaY;
      const nx = e.evt.shiftKey ? pan.x - d : pan.x;
      const ny = e.evt.shiftKey ? pan.y : pan.y - d;
      setPan(clampPan(nx, ny, zoom));
    }
  }

  function zoomBy(factor: number) {
    const nz = clamp(zoom * factor, 1, MAX_ZOOM);
    // 現在のステージ中心を基準に拡大縮小（ステージ寸法はズームで変わる）
    const cx = (stageW / 2 - pan.x) / zoom;
    const cy = (stageH / 2 - pan.y) / zoom;
    const nSW = clamp(viewW * nz, viewW, wrapW);
    const nSH = clamp(viewH * nz, viewH, maxH);
    const np = clampPan(nSW / 2 - cx * nz, nSH / 2 - cy * nz, nz);
    setZoom(nz);
    setPan(nz === 1 ? { x: 0, y: 0 } : np);
  }

  function resetZoom() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  // コンテナ幅の監視（ブラウザリサイズに追従）
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setWrapW(Math.floor(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const onResize = () => setViewportH(window.innerHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // 表示画像が変わったら、左サイドバーの該当カードを画面内へスクロール
  useEffect(() => {
    activeTaskRef.current?.scrollIntoView({ block: "nearest" });
  }, [current]);

  // 表示サイズ変更時にパンを可動範囲へ収め直す
  useEffect(() => {
    if (zoom > 1) setPan((p) => clampPan(p.x, p.y, zoom));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewW, viewH, stageW, stageH]);

  // 初期ロード: 画像一覧（画像ソース依存）
  useEffect(() => {
    api.listImages(name, imgSource).then((r) => setImages(r.images)).catch(() => {});
  }, [name, imgSource]);

  // クラス・task・除外画像
  useEffect(() => {
    api.getClasses(name).then((r) => setClasses(r.classes)).catch(() => {});
    api.getProject(name).then((p) => setTask((p.task ?? "detect") as ProjectTask)).catch(() => {});
    api.getSamSettings(name).then(setSamSettings).catch(() => setSamSettings(null));
    api
      .getSelection(name)
      .then((r) =>
        setExcludedStems(
          new Set(r.items.filter((it) => it.status === "excluded").map((it) => it.image_id))
        )
      )
      .catch(() => setExcludedStems(new Set()));
  }, [name]);

  // ?image=<stem> 指定があれば、画像一覧ロード後に該当画像へ一度だけ移動
  const jumpedRef = useRef(false);
  useEffect(() => {
    if (jumpedRef.current || visibleImages.length === 0) return;
    const target = searchParams.get("image");
    if (!target) {
      jumpedRef.current = true;
      return;
    }
    const idx = visibleImages.findIndex((im) => stemOf(im.filename) === target);
    if (idx >= 0) setCurrent(idx);
    jumpedRef.current = true;
  }, [visibleImages, searchParams]);

  // 画像切替: 画像本体と既存アノテーションを読み込む
  useEffect(() => {
    setSelectedId(null);
    setImg(null);
    setBoxes([]);
    setPolys([]);
    setDraft([]);
    setCursorPt(null);
    setSamBox(null);
    setPosPoints([]);
    setNegPoints([]);
    setCandidates([]);
    setSamError("");
    setSelectedVertexIndex(null);
    vertexDrag.current = null;
    stopVertexBlink();
    setZoom(1);
    setPan({ x: 0, y: 0 });
    if (!filename) return;

    api
      .getAnnotations(name, stem)
      .then((d) => {
        if (d.task === "segment") {
          setPolys(
            (d.annotations as PolygonItem[]).map((p) => ({
              id: newId(),
              classId: p.class_id,
              points: p.points.map((pt) => ({ x: pt.x, y: pt.y })),
              source: p.source ?? "manual",
            }))
          );
        } else {
          setBoxes(
            (d.annotations as AnnotationItem[]).map((a) => ({
              id: newId(),
              x: a.x_center - a.width / 2,
              y: a.y_center - a.height / 2,
              w: a.width,
              h: a.height,
              classId: a.class_id,
            }))
          );
        }
        setDirty(false);
        setStatus("saved");
        setMessage("");
      })
      .catch(() => {
        setBoxes([]);
        setPolys([]);
      });

    const image = new window.Image();
    image.src = api.imageUrl(name, filename, imgSource);
    image.onload = () => setImg(image);
  }, [name, filename, stem, imgSource]);

  // ============ detect（bbox）============

  function toAnnotations(): AnnotationItem[] {
    const out: AnnotationItem[] = [];
    for (const b of boxes) {
      const left = clamp(Math.min(b.x, b.x + b.w), 0, 1);
      const right = clamp(Math.max(b.x, b.x + b.w), 0, 1);
      const top = clamp(Math.min(b.y, b.y + b.h), 0, 1);
      const bottom = clamp(Math.max(b.y, b.y + b.h), 0, 1);
      const w = right - left;
      const h = bottom - top;
      if (w <= 0 || h <= 0) continue;
      out.push({
        class_id: b.classId,
        x_center: left + w / 2,
        y_center: top + h / 2,
        width: w,
        height: h,
      });
    }
    return out;
  }

  const dispOf = (b: Box) => ({
    x: b.x * viewW,
    y: b.y * viewH,
    w: b.w * viewW,
    h: b.h * viewH,
  });

  function hitZone(px: number, py: number, b: Box): Zone {
    const d = dispOf(b);
    const t = HANDLE_PX / zoom; // ズームしても画面上のつかみ幅を一定に保つ
    const nearL = Math.abs(px - d.x) <= t;
    const nearR = Math.abs(px - (d.x + d.w)) <= t;
    const nearT = Math.abs(py - d.y) <= t;
    const nearB = Math.abs(py - (d.y + d.h)) <= t;
    const inX = px >= d.x - t && px <= d.x + d.w + t;
    const inY = py >= d.y - t && py <= d.y + d.h + t;
    if (!(inX && inY)) return null;
    if (nearT && nearL) return "tl";
    if (nearT && nearR) return "tr";
    if (nearB && nearL) return "bl";
    if (nearB && nearR) return "br";
    if (nearL) return "left";
    if (nearR) return "right";
    if (nearT) return "top";
    if (nearB) return "bottom";
    if (px > d.x && px < d.x + d.w && py > d.y && py < d.y + d.h) return "inside";
    return null;
  }

  function boxAt(px: number, py: number): string | null {
    for (let i = boxes.length - 1; i >= 0; i--) {
      const d = dispOf(boxes[i]);
      if (px >= d.x && px <= d.x + d.w && py >= d.y && py <= d.y + d.h) return boxes[i].id;
    }
    return null;
  }

  function liveUpdate(id: string, patch: Partial<Box>) {
    setBoxes((b) => b.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  }

  function onBoxDown(e: Konva.KonvaEventObject<MouseEvent>) {
    if (!img) return;
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    const c = contentPt(pos.x, pos.y);

    if (selectedId) {
      const b = boxes.find((x) => x.id === selectedId);
      if (b) {
        const z = hitZone(c.x, c.y, b);
        if (z && z !== "inside") {
          opRef.current = { mode: "resize", handle: z, box: { ...b }, px: c.x, py: c.y };
          setCursor(cursorForZone(z, true));
          return;
        }
        if (z === "inside") {
          opRef.current = { mode: "move", box: { ...b }, px: c.x, py: c.y };
          setCursor("grabbing");
          return;
        }
      }
    }

    const hit = boxAt(c.x, c.y);
    if (hit) {
      setSelectedId(hit);
      return;
    }

    if (classes.length === 0) return;
    setSelectedId(null);
    drawing.current = { x: c.x, y: c.y, w: 0, h: 0, classId: activeClass };
  }

  function onBoxMove(e: Konva.KonvaEventObject<MouseEvent>) {
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    const c = contentPt(pos.x, pos.y);

    if (drawing.current) {
      drawing.current.w = c.x - drawing.current.x;
      drawing.current.h = c.y - drawing.current.y;
      setCursor("crosshair");
      force((n) => n + 1);
      return;
    }

    const op = opRef.current;
    if (op) {
      const dnx = (c.x - op.px) / viewW;
      const dny = (c.y - op.py) / viewH;
      if (op.mode === "move") {
        const nx = clamp(op.box.x + dnx, 0, 1 - op.box.w);
        const ny = clamp(op.box.y + dny, 0, 1 - op.box.h);
        liveUpdate(op.box.id, { x: nx, y: ny });
        setCursor("grabbing");
      } else if (op.handle) {
        let L = op.box.x;
        let R = op.box.x + op.box.w;
        let T = op.box.y;
        let B = op.box.y + op.box.h;
        const h = op.handle;
        if (h === "left" || h === "tl" || h === "bl") L = op.box.x + dnx;
        if (h === "right" || h === "tr" || h === "br") R = op.box.x + op.box.w + dnx;
        if (h === "top" || h === "tl" || h === "tr") T = op.box.y + dny;
        if (h === "bottom" || h === "bl" || h === "br") B = op.box.y + op.box.h + dny;
        L = clamp(L, 0, 1);
        R = clamp(R, 0, 1);
        T = clamp(T, 0, 1);
        B = clamp(B, 0, 1);
        const minW = 4 / viewW;
        const minH = 4 / viewH;
        let nx = Math.min(L, R);
        let ny = Math.min(T, B);
        const nw = Math.max(minW, Math.abs(R - L));
        const nh = Math.max(minH, Math.abs(B - T));
        if (nx + nw > 1) nx = 1 - nw;
        if (ny + nh > 1) ny = 1 - nh;
        liveUpdate(op.box.id, { x: nx, y: ny, w: nw, h: nh });
        setCursor(cursorForZone(h, true));
      }
      return;
    }

    if (selectedId) {
      const b = boxes.find((x) => x.id === selectedId);
      if (b) {
        const z = hitZone(c.x, c.y, b);
        if (z) {
          setCursor(cursorForZone(z, false));
          return;
        }
      }
    }
    if (classes.length > 0) {
      setCursor(boxAt(c.x, c.y) ? "pointer" : "crosshair");
    } else {
      setCursor("default");
    }
  }

  function endBoxInteraction() {
    if (drawing.current) {
      const d = drawing.current;
      drawing.current = null;
      const pxw = Math.abs(d.w);
      const pxh = Math.abs(d.h);
      if (pxw * zoom >= 4 && pxh * zoom >= 4) {
        const box: Box = {
          id: newId(),
          x: Math.min(d.x, d.x + d.w) / viewW,
          y: Math.min(d.y, d.y + d.h) / viewH,
          w: pxw / viewW,
          h: pxh / viewH,
          classId: d.classId,
        };
        setBoxes((b) => [...b, box]);
        setSelectedId(box.id);
        markDirty();
      }
      force((n) => n + 1);
      return;
    }
    if (opRef.current) {
      opRef.current = null;
      markDirty();
      setCursor("default");
    }
  }

  // ============ segment（polygon）============

  function toPolygonItems(): PolygonItem[] {
    return polys
      .filter((p) => p.points.length >= 3)
      .map((p) => ({
        type: "polygon" as const,
        class_id: p.classId,
        points: p.points.map((pt) => ({
          x: clamp(pt.x, 0, 1),
          y: clamp(pt.y, 0, 1),
        })),
        source: (p.source === "sam" ? "sam" : "manual") as "manual" | "sam",
      }));
  }

  function polyAt(nx: number, ny: number): string | null {
    for (let i = polys.length - 1; i >= 0; i--) {
      if (pointInPoly(nx, ny, polys[i].points)) return polys[i].id;
    }
    return null;
  }

  // 頂点ヒット判定（コンテンツpx）。近い頂点index、無ければ -1。
  function vertexAt(poly: Poly, cx: number, cy: number): number {
    const t = 9 / zoom; // 画面上のつかみ幅を一定に
    let best = -1;
    let bestD = t;
    poly.points.forEach((pt, i) => {
      const d = Math.hypot(pt.x * viewW - cx, pt.y * viewH - cy);
      if (d <= bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }

  // 辺クリック判定（コンテンツpx）。挿入index（辺の後ろ）、無ければ -1。
  function edgeInsertAt(poly: Poly, cx: number, cy: number): number {
    const t = 8 / zoom;
    const n = poly.points.length;
    for (let i = 0; i < n; i++) {
      const a = poly.points[i];
      const b = poly.points[(i + 1) % n];
      const ax = a.x * viewW;
      const ay = a.y * viewH;
      const bx = b.x * viewW;
      const by = b.y * viewH;
      const dx = bx - ax;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      if (len2 < 1e-6) continue;
      let tt = ((cx - ax) * dx + (cy - ay) * dy) / len2;
      if (tt < 0 || tt > 1) continue; // 線分の外側（頂点付近は vertexAt が優先）
      const px = ax + tt * dx;
      const py = ay + tt * dy;
      if (Math.hypot(px - cx, py - cy) <= t) return i + 1;
    }
    return -1;
  }

  function onPolyDown(e: Konva.KonvaEventObject<MouseEvent>) {
    if (!img || classes.length === 0) return;
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    const np = normPt(pos.x, pos.y);
    const c = contentPt(pos.x, pos.y);

    if (draft.length > 0) {
      // 作成中 → 頂点追加
      setDraft((d) => [...d, np]);
      return;
    }

    // 選択中polygonの頂点編集（ドラッグ / 辺クリックで追加）
    if (selectedId) {
      const poly = polys.find((p) => p.id === selectedId);
      if (poly) {
        const vi = vertexAt(poly, c.x, c.y);
        if (vi >= 0) {
          setSelectedVertexIndex(vi);
          vertexDrag.current = { polyId: poly.id, index: vi };
          stopVertexBlink();
          setCursor(CURSOR_VERTEX_DRAG);
          return;
        }
        const ei = edgeInsertAt(poly, c.x, c.y);
        if (ei >= 0) {
          setPolys((ps) =>
            ps.map((p) => {
              if (p.id !== poly.id) return p;
              const pts = [...p.points];
              pts.splice(ei, 0, np);
              return { ...p, points: pts };
            })
          );
          setSelectedVertexIndex(ei);
          vertexDrag.current = { polyId: poly.id, index: ei };
          markDirty();
          stopVertexBlink();
          setCursor(CURSOR_VERTEX_DRAG);
          return;
        }
      }
    }

    // 既存polygonをクリック → 選択、そうでなければ新規作成開始
    const hit = polyAt(np.x, np.y);
    if (hit) {
      setSelectedId(hit);
      setSelectedVertexIndex(null);
      return;
    }
    setSelectedId(null);
    setSelectedVertexIndex(null);
    setDraft([np]);
  }

  function onPolyMove(e: Konva.KonvaEventObject<MouseEvent>) {
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;

    // 頂点ドラッグ中 → 緑の矢印
    if (vertexDrag.current) {
      const np = normPt(pos.x, pos.y);
      const { polyId, index } = vertexDrag.current;
      setPolys((ps) =>
        ps.map((p) =>
          p.id === polyId
            ? { ...p, points: p.points.map((pt, i) => (i === index ? np : pt)) }
            : p
        )
      );
      markDirty();
      stopVertexBlink();
      setCursor(CURSOR_VERTEX_DRAG);
      return;
    }

    if (draft.length > 0) {
      setCursorPt(normPt(pos.x, pos.y));
      stopVertexBlink();
      setCursor(CURSOR_MANUAL);
      return;
    }
    // 選択中polygon: 頂点上=赤で点滅（つかめる）、辺上=クラス枠線色（頂点追加可）、それ以外=通常色
    if (selectedId) {
      const poly = polys.find((p) => p.id === selectedId);
      if (poly) {
        const c = contentPt(pos.x, pos.y);
        if (vertexAt(poly, c.x, c.y) >= 0) {
          startVertexBlink();
          return;
        }
        if (edgeInsertAt(poly, c.x, c.y) >= 0) {
          stopVertexBlink();
          setCursor(arrowCursor(colorOf(poly.classId)));
          return;
        }
      }
    }
    stopVertexBlink();
    setCursor(CURSOR_MANUAL);
  }

  function finalizeDraft() {
    setDraft((d) => {
      // 連続する重複点を除去（ダブルクリック確定時の重複対策）
      const pts: { x: number; y: number }[] = [];
      for (const p of d) {
        const last = pts[pts.length - 1];
        if (!last || Math.abs(last.x - p.x) > 1e-6 || Math.abs(last.y - p.y) > 1e-6) {
          pts.push(p);
        }
      }
      if (pts.length >= 3) {
        const poly: Poly = {
          id: newId(),
          classId: activeClass,
          points: pts,
          source: "manual",
        };
        setPolys((ps) => [...ps, poly]);
        setSelectedId(poly.id);
        markDirty();
      }
      return [];
    });
    setCursorPt(null);
  }

  function cancelDraft() {
    setDraft([]);
    setCursorPt(null);
  }

  // ============ SAM支援（segment） ============

  function clearPrompt() {
    setSamBox(null);
    setPosPoints([]);
    setNegPoints([]);
    setCandidates([]);
    setSamError("");
  }

  function switchSegMode(m: SegMode) {
    setSegMode(m);
    setDraft([]);
    setCursorPt(null);
    setSelectedVertexIndex(null);
    vertexDrag.current = null;
    stopVertexBlink();
    clearPrompt();
  }

  function onSegDown(e: Konva.KonvaEventObject<MouseEvent>) {
    if (!img || classes.length === 0) return;
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    const np = normPt(pos.x, pos.y);

    if (segMode === "sam_box") {
      const c = contentPt(pos.x, pos.y);
      drawing.current = { x: c.x, y: c.y, w: 0, h: 0, classId: activeClass };
      return;
    }
    if (segMode === "sam_point") {
      if (e.evt.button === 2) return; // 右クリックは contextmenu で処理
      if (e.evt.altKey) setNegPoints((p) => [...p, np]);
      else setPosPoints((p) => [...p, np]);
      return;
    }
    onPolyDown(e); // manual
  }

  function onSegMove(e: Konva.KonvaEventObject<MouseEvent>) {
    const stage = e.target.getStage();
    if (!stage) return;
    const pos = stage.getPointerPosition();
    if (!pos) return;
    if (segMode === "sam_box") {
      if (drawing.current) {
        const c = contentPt(pos.x, pos.y);
        drawing.current.w = c.x - drawing.current.x;
        drawing.current.h = c.y - drawing.current.y;
        force((n) => n + 1);
      }
      setCursor("crosshair");
      return;
    }
    if (segMode === "sam_point") {
      setCursor("crosshair");
      return;
    }
    onPolyMove(e); // manual
  }

  function onSegUp() {
    if (vertexDrag.current) {
      vertexDrag.current = null;
      // 手動編集の矢印（青）へ戻す
      setCursor(segMode === "manual" ? CURSOR_MANUAL : "default");
      return;
    }
    if (segMode === "sam_box" && drawing.current) {
      const d = drawing.current;
      drawing.current = null;
      const x1 = Math.min(d.x, d.x + d.w) / viewW;
      const y1 = Math.min(d.y, d.y + d.h) / viewH;
      const x2 = Math.max(d.x, d.x + d.w) / viewW;
      const y2 = Math.max(d.y, d.y + d.h) / viewH;
      if (x2 - x1 > 0.005 && y2 - y1 > 0.005) setSamBox({ x1, y1, x2, y2 });
      force((n) => n + 1);
    }
  }

  function onSegContextMenu(e: Konva.KonvaEventObject<MouseEvent>) {
    if (!isSeg || segMode !== "sam_point") return;
    e.evt.preventDefault();
    const stage = e.target.getStage();
    const pos = stage?.getPointerPosition();
    if (pos) {
      setNegPoints((p) => [...p, normPt(pos.x, pos.y)]);
    }
  }

  async function runSam() {
    if (!filename) return;
    setSamError("");
    if (segMode === "sam_box" && !samBox) {
      setSamError("SAM用のbboxをドラッグで指定してください。");
      return;
    }
    if (segMode === "sam_point" && posPoints.length === 0) {
      setSamError("positive point を1つ以上指定してください。");
      return;
    }
    const prompt =
      segMode === "sam_box"
        ? { type: "box" as const, box: samBox, positive_points: [], negative_points: [] }
        : { type: "point" as const, positive_points: posPoints, negative_points: negPoints };
    setSamBusy(true);
    try {
      const res = await api.samPropose(name, stem, {
        source: imgSource,
        class_id: activeClass,
        prompt,
        settings: samSettings ?? undefined,
      });
      setCandidates(res.candidates);
      if (res.candidates.length === 0) {
        setSamError(res.message ?? "候補が見つかりませんでした。");
      } else {
        // 描写後は検出に使った枠・点を消す（候補polygonは残す）
        setSamBox(null);
        setPosPoints([]);
        setNegPoints([]);
        setCursorPt(null);
      }
    } catch (e) {
      setSamError(String(e));
    } finally {
      setSamBusy(false);
    }
  }

  function adoptCandidate(c: SamCandidate) {
    const poly: Poly = {
      id: newId(),
      classId: activeClass,
      points: c.points.map((p) => ({ x: p.x, y: p.y })),
      source: "sam",
    };
    setPolys((ps) => [...ps, poly]);
    setSelectedId(poly.id);
    setSelectedVertexIndex(null);
    setCandidates((cs) => cs.filter((x) => x.candidate_id !== c.candidate_id));
    markDirty();
  }

  // 現在の候補をすべて採用する（Enterでの一括採用用）。クラスは activeClass を適用。
  function adoptAllCandidates() {
    if (candidates.length === 0) return;
    const created: Poly[] = candidates.map((c) => ({
      id: newId(),
      classId: activeClass,
      points: c.points.map((p) => ({ x: p.x, y: p.y })),
      source: "sam",
    }));
    setPolys((ps) => [...ps, ...created]);
    setSelectedId(created[created.length - 1].id);
    setSelectedVertexIndex(null);
    setCandidates([]);
    markDirty();
  }

  function discardCandidate(id: string) {
    setCandidates((cs) => cs.filter((x) => x.candidate_id !== id));
  }

  // ============ 共通 ============

  function chooseClass(classId: number) {
    if (classId < 0 || classId >= classes.length) return;
    setActiveClass(classId);
    // SAM候補が保留中は、活性クラスのみ変更（採用時に適用）。既存選択は変えない。
    if (candidates.length > 0) return;
    if (selectedId) {
      if (isSeg) {
        setPolys((ps) => ps.map((p) => (p.id === selectedId ? { ...p, classId } : p)));
      } else {
        liveUpdate(selectedId, { classId });
      }
      markDirty();
    }
  }

  function deleteSelected() {
    if (!selectedId) return;
    // segment: 頂点が選択されていれば頂点削除（最低3点は維持）
    if (isSeg && selectedVertexIndex != null) {
      const poly = polys.find((p) => p.id === selectedId);
      if (poly) {
        if (poly.points.length <= 3) {
          setMessage("polygonは最低3点必要なため、この頂点は削除できません。");
          return;
        }
        setPolys((ps) =>
          ps.map((p) =>
            p.id === selectedId
              ? { ...p, points: p.points.filter((_, i) => i !== selectedVertexIndex) }
              : p
          )
        );
        setSelectedVertexIndex(null);
        markDirty();
        return;
      }
    }
    // それ以外は polygon / bbox 全体を削除
    if (isSeg) {
      setPolys((ps) => ps.filter((p) => p.id !== selectedId));
    } else {
      setBoxes((b) => b.filter((x) => x.id !== selectedId));
    }
    setSelectedId(null);
    setSelectedVertexIndex(null);
    markDirty();
  }

  async function save() {
    if (!filename) return;
    try {
      let count: number;
      let label: string;
      if (isSeg) {
        const items = toPolygonItems();
        const res = await api.saveSegmentAnnotations(name, stem, items);
        count = res.annotation_count;
        label = res.label_path;
      } else {
        const res = await api.saveAnnotations(name, stem, toAnnotations());
        count = res.annotation_count;
        label = res.label_path;
      }
      setDirty(false);
      setStatus("saved");
      setMessage(`保存しました（${count}件 / ${label}）`);
      api.listImages(name, imgSource).then((r) => setImages(r.images)).catch(() => {});
      // 保存後は作業のフォーカス（選択・DOMフォーカス）を外す
      setSelectedId(null);
      setSelectedVertexIndex(null);
      stopVertexBlink();
      (document.activeElement as HTMLElement | null)?.blur?.();
      if (isSeg && segMode === "manual") setCursor(CURSOR_MANUAL);
    } catch (e) {
      setStatus("error");
      setMessage("保存に失敗: " + String(e));
    }
  }

  function gotoImage(idx: number) {
    const next = clamp(idx, 0, visibleImages.length - 1);
    if (next === current) return;
    if (dirty && !window.confirm("未保存の変更があります。保存せずに移動しますか？")) {
      return;
    }
    setCurrent(next);
  }

  // キーボード操作はマウント時に1度だけ登録し、最新の処理はrefから呼ぶ
  const actionsRef = useRef({
    del: deleteSelected,
    save,
    next: () => gotoImage(current + 1),
    prev: () => gotoImage(current - 1),
    setClass: chooseClass,
    // Enter: SAMモードは「候補があれば採用、無ければSAM実行」。手動は作成中の確定。
    enter: () => {
      if (isSeg && segMode !== "manual") {
        if (candidates.length > 0) adoptAllCandidates();
        else runSam();
      } else {
        finalizeDraft();
      }
    },
    // Esc: 作成中polygonを取り消し、選択中アノテーションのフォーカス（選択）も外す
    cancel: () => {
      cancelDraft();
      setSelectedId(null);
      setSelectedVertexIndex(null);
      stopVertexBlink();
      (document.activeElement as HTMLElement | null)?.blur?.();
      if (isSeg) setCursor(segMode === "manual" ? CURSOR_MANUAL : "default");
    },
  });
  actionsRef.current = {
    del: deleteSelected,
    save,
    next: () => gotoImage(current + 1),
    prev: () => gotoImage(current - 1),
    setClass: chooseClass,
    // Enter: SAMモードは「候補があれば採用、無ければSAM実行」。手動は作成中の確定。
    enter: () => {
      if (isSeg && segMode !== "manual") {
        if (candidates.length > 0) adoptAllCandidates();
        else runSam();
      } else {
        finalizeDraft();
      }
    },
    // Esc: 作成中polygonを取り消し、選択中アノテーションのフォーカス（選択）も外す
    cancel: () => {
      cancelDraft();
      setSelectedId(null);
      setSelectedVertexIndex(null);
      stopVertexBlink();
      (document.activeElement as HTMLElement | null)?.blur?.();
      if (isSeg) setCursor(segMode === "manual" ? CURSOR_MANUAL : "default");
    },
  };

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.ctrlKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        actionsRef.current.save();
        return;
      }
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Enter") actionsRef.current.enter();
      else if (e.key === "Escape") actionsRef.current.cancel();
      else if (e.key === "Delete" || e.key === "Backspace") actionsRef.current.del();
      else if (e.key === "ArrowRight") actionsRef.current.next();
      else if (e.key === "ArrowLeft") actionsRef.current.prev();
      else if (/^[0-9]$/.test(e.key)) actionsRef.current.setClass(Number(e.key));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // YOLO形式プレビュー
  const yoloText = isSeg
    ? toPolygonItems()
        .map(
          (p) =>
            `${p.class_id} ` +
            p.points.map((pt) => `${pt.x.toFixed(6)} ${pt.y.toFixed(6)}`).join(" ")
        )
        .join("\n")
    : toAnnotations()
        .map(
          (a) =>
            `${a.class_id} ${a.x_center.toFixed(6)} ${a.y_center.toFixed(6)} ` +
            `${a.width.toFixed(6)} ${a.height.toFixed(6)}`
        )
        .join("\n");

  const preview = drawing.current;

  const statusLabel =
    status === "saved"
      ? "保存済み"
      : status === "unsaved"
      ? "未保存"
      : status === "error"
      ? "エラー"
      : "";

  // segment: 作成中polygonの表示用フラット配列（マウス追従点を含む）
  const draftFlat: number[] = [];
  for (const p of draft) draftFlat.push(p.x * viewW, p.y * viewH);
  if (draft.length > 0 && cursorPt) draftFlat.push(cursorPt.x * viewW, cursorPt.y * viewH);

  // ズーム時も線・ラベル・点の見た目の大きさを一定に保つ係数（Layerのscaleを打ち消す）
  const iz = 1 / zoom;

  // 選択中polygon（頂点ハンドル表示用）
  const selectedPoly = isSeg ? polys.find((p) => p.id === selectedId) ?? null : null;

  return (
    <div className="page">
      <h1>
        {isSeg ? "セグメンテーション（輪郭アノテーション）" : "アノテーション"}: {name}
      </h1>

      {classes.length === 0 && (
        <div className="warn">
          クラスが未定義です。「クラス設計」で先にクラスを追加してください。
        </div>
      )}

      {/* ツールバー1: 画像ナビゲーション + ズーム + 保存 */}
      <div className="annotate-toolbar">
        <div className="tb-group">
          <button onClick={() => gotoImage(current - 1)} disabled={current <= 0} title="前の画像 (←)">
            ←
          </button>
          <select
            className="tb-image-select"
            value={current}
            onChange={(e) => gotoImage(Number(e.target.value))}
            disabled={visibleImages.length === 0}
          >
            {visibleImages.length === 0 && <option value={0}>画像なし</option>}
            {visibleImages.map((im, i) => (
              <option key={im.filename} value={i}>
                {i + 1}. {im.filename}
                {im.has_label ? " ✓" : ""}
              </option>
            ))}
          </select>
          <button
            onClick={() => gotoImage(current + 1)}
            disabled={current >= visibleImages.length - 1}
            title="次の画像 (→)"
          >
            →
          </button>
          <span className="muted tb-count">
            {visibleImages.length > 0 ? `${current + 1} / ${visibleImages.length}` : "0 / 0"}
          </span>
        </div>

        <span className="tb-sep" />

        <div className="tb-group">
          <label className="field tb-field">
            画像ソース
            <select value={imgSource} onChange={(e) => setImgSource(e.target.value)}>
              <option value="auto">{SOURCE_LABELS.auto}</option>
              <option value="raw">{SOURCE_LABELS.raw}</option>
              <option value="processed">{SOURCE_LABELS.processed}</option>
            </select>
          </label>
          <label className="tb-check">
            <input type="checkbox" checked={hideExcluded} onChange={(e) => setHideExcluded(e.target.checked)} /> 除外画像を隠す
          </label>
        </div>

        <span className="tb-sep" />

        <div className="tb-group zoom-bar" title="Ctrl+ホイールでも拡大縮小できます">
          <span className="muted">表示</span>
          <button onClick={() => zoomBy(1 / 1.25)} disabled={zoom <= 1} title="縮小">
            −
          </button>
          <span className="tb-zoom">{Math.round(zoom * 100)}%</span>
          <button onClick={() => zoomBy(1.25)} disabled={zoom >= MAX_ZOOM} title="拡大">
            ＋
          </button>
          <button className="secondary" onClick={resetZoom} disabled={zoom === 1}>
            リセット
          </button>
        </div>

        <span className="tb-spacer" />

        <div className="tb-group">
          <button className="primary" onClick={save} disabled={!filename}>
            保存 (Ctrl+S)
          </button>
          {statusLabel && (
            <span className={status === "saved" ? "success" : status === "error" ? "error" : "warn"}>
              ● {statusLabel}
            </span>
          )}
        </div>
      </div>
      {message && <div className="muted" style={{ marginTop: -4 }}>{message}</div>}

      {/* ツールバー2: クラス選択 */}
      <div className="annotate-classbar">
        <span className="muted tb-label">クラス</span>
        <div className="class-palette">
          {classes.map((c) => (
            <button
              key={c.id}
              className={"chip" + (c.id === activeClass ? " active" : "")}
              style={{ borderColor: c.color }}
              onClick={() => chooseClass(c.id)}
            >
              <span className="swatch" style={{ background: c.color }} />
              {c.id}: {c.name}
            </button>
          ))}
          {classes.length === 0 && <span className="muted">クラス未定義</span>}
        </div>
      </div>

      <div className="annotate-body">
        {/* 左: 画像タスク一覧（サムネ＋アノテ状況、Label Studio風） */}
        <div className="annotate-tasklist">
          <div className="tasklist-head">
            画像（{visibleImages.length}）
            <span className="tasklist-sub">
              済 {visibleImages.filter((im) => im.has_label).length} / 未{" "}
              {visibleImages.filter((im) => !im.has_label).length}
            </span>
          </div>
          <div className="tasklist-scroll">
            {visibleImages.map((im, i) => {
              const st = stemOf(im.filename);
              const isCurrent = i === current;
              const excluded = excludedStems.has(st);
              return (
                <button
                  key={im.filename}
                  ref={isCurrent ? activeTaskRef : undefined}
                  className={"task-item" + (isCurrent ? " active" : "")}
                  onClick={() => gotoImage(i)}
                  onMouseMove={(e) => onTaskHover(e, im.filename)}
                  onMouseLeave={() => setTaskPreview(null)}
                  title={im.filename}
                >
                  <img
                    className="task-thumb"
                    src={api.thumbnailUrl(name, im.filename, imgSource)}
                    alt={im.filename}
                    loading="lazy"
                  />
                  <span className="task-meta">
                    <span className="task-name">
                      {i + 1}. {im.filename}
                    </span>
                    <span className="task-status">
                      {isCurrent && dirty ? (
                        <span className="ts-warn">● 未保存</span>
                      ) : im.has_label ? (
                        <span className="ts-done">✓ 済</span>
                      ) : (
                        <span className="ts-none">未</span>
                      )}
                      {excluded && <span className="ts-none"> ・除外</span>}
                    </span>
                    <span className="task-dims">
                      {im.width}×{im.height}
                      {isCurrent && <> ・annot {currentCount}</>}
                      {im.low_resolution && <span className="ts-warn"> ・低解像</span>}
                    </span>
                  </span>
                </button>
              );
            })}
            {visibleImages.length === 0 && <div className="muted" style={{ padding: 8 }}>画像なし</div>}
          </div>
          {/* カードホバー時の拡大プレビュー（body直下に描画） */}
          {taskPreview &&
            createPortal(
              <img
                className="hover-img-preview"
                src={taskPreview.src}
                alt=""
                style={{ left: taskPreview.x, top: taskPreview.y }}
              />,
              document.body
            )}
        </div>

        <div className="canvas-wrap" ref={wrapRef}>
          <Stage
            ref={stageRef}
            width={stageW}
            height={stageH}
            onMouseDown={isSeg ? onSegDown : onBoxDown}
            onMouseMove={isSeg ? onSegMove : onBoxMove}
            onMouseUp={isSeg ? onSegUp : endBoxInteraction}
            onDblClick={isSeg && segMode === "manual" ? finalizeDraft : undefined}
            onContextMenu={onSegContextMenu}
            onMouseLeave={() => {
              if (!isSeg) endBoxInteraction();
              vertexDrag.current = null;
              stopVertexBlink();
              setCursor("default");
            }}
            onWheel={onWheel}
            style={{ background: "transparent" }}
          >
            <Layer scaleX={zoom} scaleY={zoom} x={pan.x} y={pan.y}>
              {img && <KonvaImage image={img} width={viewW} height={viewH} listening={false} />}

              {/* detect: bbox */}
              {!isSeg &&
                boxes.map((b) => {
                  const d = dispOf(b);
                  const color = colorOf(b.classId);
                  const selected = b.id === selectedId;
                  const label = nameOf(b.classId);
                  const labelW = Math.max(18, label.length * 7 + 8) * iz;
                  const labelH = 16 * iz;
                  const labelInside = d.y < labelH;
                  const labelY = labelInside ? d.y : d.y - labelH;
                  return (
                    <Group key={b.id} listening={false}>
                      <Rect
                        x={d.x}
                        y={d.y}
                        width={d.w}
                        height={d.h}
                        stroke={color}
                        strokeWidth={(selected ? 3 : 2) * iz}
                        fill={hexToRgba(color, 0.2)}
                        dash={selected ? [6 * iz, 3 * iz] : undefined}
                        listening={false}
                      />
                      <Rect x={d.x} y={labelY} width={labelW} height={labelH} fill={color} listening={false} />
                      <Text
                        x={d.x + 4 * iz}
                        y={labelY + 3 * iz}
                        text={label}
                        fontSize={11 * iz}
                        fill="#ffffff"
                        listening={false}
                      />
                    </Group>
                  );
                })}
              {!isSeg && preview && (
                <Rect
                  x={Math.min(preview.x, preview.x + preview.w)}
                  y={Math.min(preview.y, preview.y + preview.h)}
                  width={Math.abs(preview.w)}
                  height={Math.abs(preview.h)}
                  stroke={colorOf(activeClass)}
                  fill={hexToRgba(colorOf(activeClass), 0.15)}
                  dash={[4 * iz, 4 * iz]}
                  strokeWidth={iz}
                  listening={false}
                />
              )}

              {/* segment: polygon */}
              {isSeg &&
                polys.map((p) => {
                  const color = colorOf(p.classId);
                  const selected = p.id === selectedId;
                  const flat: number[] = [];
                  for (const pt of p.points) flat.push(pt.x * viewW, pt.y * viewH);
                  const first = p.points[0];
                  return (
                    <Group key={p.id} listening={false}>
                      <Line
                        points={flat}
                        closed
                        stroke={color}
                        strokeWidth={(selected ? 3 : 2) * iz}
                        fill={hexToRgba(color, 0.2)}
                        dash={selected ? [6 * iz, 3 * iz] : undefined}
                        listening={false}
                      />
                      {first && (
                        <>
                          <Rect
                            x={first.x * viewW}
                            y={first.y * viewH - 16 * iz}
                            width={Math.max(18, nameOf(p.classId).length * 7 + 8) * iz}
                            height={16 * iz}
                            fill={color}
                            listening={false}
                          />
                          <Text
                            x={first.x * viewW + 4 * iz}
                            y={first.y * viewH - 13 * iz}
                            text={nameOf(p.classId)}
                            fontSize={11 * iz}
                            fill="#ffffff"
                            listening={false}
                          />
                        </>
                      )}
                    </Group>
                  );
                })}
              {/* segment: 選択中polygonの頂点ハンドル */}
              {isSeg &&
                selectedPoly &&
                selectedPoly.points.map((pt, i) => {
                  const sel = i === selectedVertexIndex;
                  const col = colorOf(selectedPoly.classId);
                  return (
                    <Circle
                      key={"vh" + i}
                      x={pt.x * viewW}
                      y={pt.y * viewH}
                      radius={5 * iz}
                      fill={sel ? col : "#ffffff"}
                      stroke={sel ? "#ffffff" : col}
                      strokeWidth={2 * iz}
                      listening={false}
                    />
                  );
                })}

              {/* segment: 作成中polygon（点と線） */}
              {isSeg && draft.length > 0 && (
                <Group listening={false}>
                  <Line
                    points={draftFlat}
                    stroke={colorOf(activeClass)}
                    strokeWidth={1.5 * iz}
                    dash={[4 * iz, 4 * iz]}
                    listening={false}
                  />
                  {draft.map((pt, i) => (
                    <Circle
                      key={i}
                      x={pt.x * viewW}
                      y={pt.y * viewH}
                      radius={4 * iz}
                      fill={colorOf(activeClass)}
                      stroke="#ffffff"
                      strokeWidth={iz}
                      listening={false}
                    />
                  ))}
                </Group>
              )}

              {/* SAM候補polygon（点線）。採用時に適用されるクラス色で表示し、
                  数字キーでクラスを変えると色とラベルが即時に変わる。 */}
              {isSeg &&
                candidates.map((c) => {
                  const flat: number[] = [];
                  for (const pt of c.points) flat.push(pt.x * viewW, pt.y * viewH);
                  const first = c.points[0];
                  const col = colorOf(activeClass);
                  const label = `候補: ${nameOf(activeClass)}`;
                  const labelW = Math.max(48, label.length * 7 + 8) * iz;
                  return (
                    <Group key={c.candidate_id} listening={false}>
                      <Line
                        points={flat}
                        closed
                        stroke={col}
                        strokeWidth={2 * iz}
                        dash={[8 * iz, 4 * iz]}
                        fill={hexToRgba(col, 0.15)}
                        listening={false}
                      />
                      {first && (
                        <>
                          <Rect
                            x={first.x * viewW}
                            y={first.y * viewH - 16 * iz}
                            width={labelW}
                            height={16 * iz}
                            fill={col}
                            listening={false}
                          />
                          <Text
                            x={first.x * viewW + 4 * iz}
                            y={first.y * viewH - 13 * iz}
                            text={label}
                            fontSize={11 * iz}
                            fill="#ffffff"
                            listening={false}
                          />
                        </>
                      )}
                    </Group>
                  );
                })}

              {/* SAM Box: prompt用一時bbox（青破線・保存しない） */}
              {isSeg && segMode === "sam_box" && drawing.current && (
                <Rect
                  x={Math.min(drawing.current.x, drawing.current.x + drawing.current.w)}
                  y={Math.min(drawing.current.y, drawing.current.y + drawing.current.h)}
                  width={Math.abs(drawing.current.w)}
                  height={Math.abs(drawing.current.h)}
                  stroke="#1677ff"
                  dash={[6 * iz, 4 * iz]}
                  strokeWidth={2 * iz}
                  listening={false}
                />
              )}
              {isSeg && segMode === "sam_box" && !drawing.current && samBox && (
                <Rect
                  x={samBox.x1 * viewW}
                  y={samBox.y1 * viewH}
                  width={(samBox.x2 - samBox.x1) * viewW}
                  height={(samBox.y2 - samBox.y1) * viewH}
                  stroke="#1677ff"
                  dash={[6 * iz, 4 * iz]}
                  strokeWidth={2 * iz}
                  listening={false}
                />
              )}

              {/* SAM Point: positive(緑)/negative(赤) */}
              {isSeg && segMode === "sam_point" && (
                <Group listening={false}>
                  {posPoints.map((p, i) => (
                    <Circle key={"p" + i} x={p.x * viewW} y={p.y * viewH} radius={5 * iz} fill="#22c55e" stroke="#fff" strokeWidth={iz} listening={false} />
                  ))}
                  {negPoints.map((p, i) => (
                    <Circle key={"n" + i} x={p.x * viewW} y={p.y * viewH} radius={5 * iz} fill="#ef4444" stroke="#fff" strokeWidth={iz} listening={false} />
                  ))}
                </Group>
              )}
            </Layer>
          </Stage>
        </div>

        <div className="annotate-side">
          {/* セグメンテーションのツール（polygon一覧の上に配置） */}
          {isSeg && (
            <div className="seg-tools">
              <div className="seg-tools-head">ツール</div>
              <div className="seg-mode-btns">
                {(["manual", "sam_box", "sam_point"] as SegMode[]).map((m) => (
                  <button
                    key={m}
                    className={segMode === m ? "primary" : "secondary"}
                    onClick={() => switchSegMode(m)}
                  >
                    {SEG_MODE_LABELS[m]}
                  </button>
                ))}
              </div>
              {segMode !== "manual" && (
                <div className="seg-sam">
                  <div className="seg-sam-actions">
                    {candidates.length > 0 ? (
                      <button onClick={adoptAllCandidates}>採用 (Enter)</button>
                    ) : (
                      <button onClick={runSam} disabled={samBusy}>
                        {samBusy ? "SAM実行中…" : "SAM実行 (Enter)"}
                      </button>
                    )}
                    <button className="secondary" onClick={clearPrompt}>
                      {candidates.length > 0 ? "候補を破棄" : "プロンプトをクリア"}
                    </button>
                  </div>
                  {samSettings && (
                    <div className="seg-merge">
                      <label className="tb-check">
                        <input
                          type="checkbox"
                          checked={samSettings.merge_nearby_regions}
                          onChange={(e) =>
                            setSamSettings({ ...samSettings, merge_nearby_regions: e.target.checked })
                          }
                        />{" "}
                        近い領域を結合
                      </label>
                      {samSettings.merge_nearby_regions && (
                        <label className="field">
                          結合距離(px)
                          <input
                            type="number"
                            min={0}
                            max={100}
                            style={{ width: 64 }}
                            value={samSettings.merge_distance_px}
                            onChange={(e) =>
                              setSamSettings({ ...samSettings, merge_distance_px: Number(e.target.value) })
                            }
                          />
                        </label>
                      )}
                    </div>
                  )}
                  <div className="seg-hint">
                    {candidates.length > 0
                      ? "数字キーでクラス変更 → もう一度Enterで採用"
                      : segMode === "sam_box"
                      ? "ドラッグで範囲を囲む → Enter/SAM実行"
                      : "左=positive(緑) / Alt+左・右=negative(赤) → Enter/SAM実行"}
                    {samSettings ? ` ｜ ${samSettings.model} / ${samSettings.device}` : ""}
                  </div>
                </div>
              )}
              {samError && <div className="error">{samError}</div>}
            </div>
          )}

          <div className="side-head">
            <h3>{isSeg ? `polygon（${polys.length}）` : `ボックス（${boxes.length}）`}</h3>
            <button onClick={deleteSelected} disabled={!selectedId} className="danger">
              削除 (Del)
            </button>
          </div>

          {isSeg && draft.length > 0 && (
            <div className="warn" style={{ fontSize: "0.8rem" }}>
              作成中: {draft.length}点（Enter/ダブルクリックで確定、Escでキャンセル）
            </div>
          )}

          <ul className="compact box-list">
            {isSeg
              ? polys.map((p) => (
                  <li
                    key={p.id}
                    className={p.id === selectedId ? "selected" : ""}
                    onClick={() => setSelectedId(p.id)}
                  >
                    <span className="swatch" style={{ background: colorOf(p.classId) }} />
                    {nameOf(p.classId)}（{p.points.length}点{p.source === "sam" ? " / SAM" : ""}）
                  </li>
                ))
              : boxes.map((b) => (
                  <li
                    key={b.id}
                    className={b.id === selectedId ? "selected" : ""}
                    onClick={() => setSelectedId(b.id)}
                  >
                    <span className="swatch" style={{ background: colorOf(b.classId) }} />
                    {nameOf(b.classId)}
                  </li>
                ))}
            {((isSeg && polys.length === 0) || (!isSeg && boxes.length === 0)) && (
              <li className="muted">まだありません</li>
            )}
          </ul>

          {isSeg && candidates.length > 0 && (
            <div className="sam-candidates">
              <div className="side-head">
                <h3>SAM候補（{candidates.length}）</h3>
                <button className="secondary" onClick={() => setCandidates([])}>
                  すべて破棄
                </button>
              </div>
              <ul className="compact cand-list">
                {candidates.map((c) => (
                  <li key={c.candidate_id}>
                    <span className="muted">
                      {c.points.length}点{c.score != null ? ` / ${c.score.toFixed(2)}` : ""}
                      {c.merged ? ` / 結合(${c.source_mask_count ?? "?"}領域)` : ""}
                    </span>
                    <span className="cand-actions">
                      <button onClick={() => adoptCandidate(c)}>採用</button>
                      <button className="secondary" onClick={() => discardCandidate(c.candidate_id)}>
                        破棄
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <details className="side-details">
            <summary>YOLO形式プレビュー</summary>
            <textarea readOnly className="yolo-preview" value={yoloText} />
          </details>

          <details className="side-details" open={isSeg}>
            <summary>操作ヘルプ</summary>
            <ol className="help-list">
              {isSeg && segMode === "manual" && (
                <>
                  <li>クリックで頂点追加、Enter / ダブルクリックで確定</li>
                  <li>Escで作成キャンセル、polygonクリックで選択</li>
                  <li>選択中は頂点ハンドルをドラッグで移動、辺付近クリックで頂点追加</li>
                  <li>頂点を選択してDeleteで削除（最低3点は維持）</li>
                </>
              )}
              {isSeg && segMode === "sam_box" && (
                <>
                  <li>ドラッグで範囲を囲み、Enter または「SAM実行」で候補生成</li>
                  <li>候補生成後は数字キーでクラス変更、もう一度Enterで採用（枠は自動で消えます）</li>
                </>
              )}
              {isSeg && segMode === "sam_point" && (
                <>
                  <li>左=positive / Alt+左・右=negative、Enterで候補生成</li>
                  <li>候補生成後は数字キーでクラス変更、もう一度Enterで採用（点は自動で消えます）</li>
                </>
              )}
              {!isSeg && (
                <>
                  <li>ドラッグで矩形作成、クリックで選択</li>
                  <li>辺・角にカーソルを近づけてドラッグでサイズ変更、枠内ドラッグで移動</li>
                </>
              )}
              <li>Deleteで削除、数字キーでクラス切替、←→で画像移動</li>
              <li>Ctrl+ホイールで拡大縮小、拡大中はホイール/Shift+ホイールでスクロール</li>
              <li>Ctrl+Sで保存</li>
            </ol>
          </details>
        </div>
      </div>
    </div>
  );
}
