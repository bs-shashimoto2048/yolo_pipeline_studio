// 画像取り込みパネル（プロジェクト準備画面のセクション）。
// フォルダ単位の一括取り込み（主導線）＋ 個別アップロード（従来）＋ 登録画像一覧。
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import HoverImagePreview from "./HoverImagePreview";
import type { FolderImportResponse, ImageInfo, UploadResponse } from "../types";

const ALL_EXTS = [".jpg", ".jpeg", ".png", ".bmp", ".webp"];
const DEFAULT_EXTS = [".jpg", ".jpeg", ".png"];

function extOf(filename: string): string {
  const m = /\.[^./\\]+$/.exec(filename);
  return m ? m[0].toLowerCase() : "";
}

function relDepth(file: File): number {
  const rel = (file as unknown as { webkitRelativePath?: string }).webkitRelativePath;
  if (!rel) return 1;
  return rel.split("/").filter(Boolean).length;
}

export default function ImagesPanel() {
  const { name = "" } = useParams();
  const [images, setImages] = useState<ImageInfo[]>([]);
  const [error, setError] = useState("");

  const [picked, setPicked] = useState<File[]>([]);
  const [exts, setExts] = useState<Set<string>>(new Set(DEFAULT_EXTS));
  const [includeSub, setIncludeSub] = useState(true);
  const [folderResult, setFolderResult] = useState<FolderImportResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const folderRef = useRef<HTMLInputElement>(null);

  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload() {
    try {
      setImages((await api.listImages(name)).images);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    reload();
  }, [name]);

  const { target, excluded } = useMemo(() => {
    const tgt: File[] = [];
    let exc = 0;
    for (const f of picked) {
      const okExt = exts.has(extOf(f.name));
      const okSub = includeSub || relDepth(f) <= 2;
      if (okExt && okSub) tgt.push(f);
      else exc++;
    }
    return { target: tgt, excluded: exc };
  }, [picked, exts, includeSub]);

  function onPickFolder(e: React.ChangeEvent<HTMLInputElement>) {
    setFolderResult(null);
    setPicked(e.target.files ? Array.from(e.target.files) : []);
  }

  function toggleExt(ext: string) {
    setExts((prev) => {
      const next = new Set(prev);
      if (next.has(ext)) next.delete(ext);
      else next.add(ext);
      return next;
    });
  }

  async function runImport() {
    if (target.length === 0) return;
    setBusy(true);
    setError("");
    setFolderResult(null);
    try {
      const res = await api.importFolder(name, target, Array.from(exts), includeSub);
      setFolderResult(res);
      setPicked([]);
      if (folderRef.current) folderRef.current.value = "";
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setBusy(true);
    setError("");
    setUploadResult(null);
    try {
      setUploadResult(await api.uploadImages(name, files));
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <section className="card">
      <h2>画像取り込み</h2>

      {/* 取り込み方法を2つのコンテナに分けて表示 */}
      <div className="import-methods">
        <div className="import-method">
          <div className="ds-group-title">
            フォルダ取り込み<span className="im-badge">推奨</span>
          </div>
          <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 8px" }}>
            フォルダを選ぶと、指定拡張子の画像のみ一括取り込み。重複・破損・対象外は自動スキップし、
            ファイル名は安全な名前に正規化されます。
          </p>
          <div className="row im-exts">
            {ALL_EXTS.map((ext) => (
              <label key={ext}>
                <input type="checkbox" checked={exts.has(ext)} onChange={() => toggleExt(ext)} /> {ext}
              </label>
            ))}
            <label>
              <input type="checkbox" checked={includeSub} onChange={(e) => setIncludeSub(e.target.checked)} /> サブフォルダを含める
            </label>
          </div>
          <div className="row">
            <input
              ref={folderRef}
              type="file"
              multiple
              onChange={onPickFolder}
              {...({ webkitdirectory: "true", directory: "true" } as Record<string, string>)}
            />
          </div>
          {picked.length > 0 && (
            <div className="row im-picked">
              <span className="muted" style={{ fontSize: "0.8rem" }}>
                対象 <strong>{target.length}</strong> / 除外 <strong>{excluded}</strong>（選択 {picked.length}）
              </span>
              <button onClick={runImport} disabled={busy || target.length === 0}>
                {busy ? "取り込み中…" : "取り込み実行"}
              </button>
            </div>
          )}
          {folderResult && (
            <div className="import-result">
              <span className="success">取り込み {folderResult.imported_count} 件</span>
              <span className="muted">
                {" "}／ スキップ {folderResult.skipped_count}（重複 {folderResult.duplicate_count} / 破損{" "}
                {folderResult.broken_count} / 対象外 {folderResult.unsupported_count}）
              </span>
            </div>
          )}
        </div>

        <div className="import-method">
          <div className="ds-group-title">個別アップロード</div>
          <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 8px" }}>
            少数の画像を直接選んで追加します（jpg / jpeg / png / bmp / webp）。
            重複・破損は自動スキップされ、下の登録画像に反映されます。
          </p>
          <div className="row">
            <input
              ref={fileRef}
              type="file"
              accept=".jpg,.jpeg,.png,.bmp,.webp"
              multiple
              onChange={onUpload}
              disabled={busy}
            />
          </div>
          <p className="muted im-hint" style={{ fontSize: "0.76rem" }}>
            大量の画像はフォルダ取り込みの方が高速です。
          </p>
          {uploadResult && (
            <div className="import-result">
              <span className="success">追加 {uploadResult.added} 件</span>
              <span className="muted"> ／ スキップ {uploadResult.skipped} 件</span>
            </div>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="im-registered-head">
        <div className="ds-group-title" style={{ margin: 0 }}>登録画像</div>
        <span className="chip-count">{images.length} 枚</span>
      </div>
      <div className="thumb-grid im-grid">
        {images.map((img) => (
          <figure key={img.filename} className="thumb">
            <HoverImagePreview
              thumbSrc={api.thumbnailUrl(name, img.filename)}
              fullSrc={api.imageUrl(name, img.filename)}
              alt={img.filename}
            />
            <figcaption>
              <div className="thumb-name" title={img.filename}>
                {img.filename}
              </div>
              <div className="muted">
                {img.width}×{img.height}
                {img.low_resolution && <span className="warn"> 低解像度</span>}
                {img.has_label && <span className="success"> ラベル有</span>}
              </div>
            </figcaption>
          </figure>
        ))}
        {images.length === 0 && <p className="muted">画像がありません。</p>}
      </div>
    </section>
  );
}
