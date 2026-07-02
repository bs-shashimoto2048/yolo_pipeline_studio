// データ拡張（学習時オーギュメンテーション）パネル。学習画面の右カラムに埋め込み、
// プリセットの選択・パラメータ確認・編集・保存・削除を1画面で行えるようにする。
// selected（学習に使うプリセット名）を親と同期する。
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import InfoTooltip from "./InfoTooltip";
import type { AugmentationParams, AugmentationPreset } from "../types";

// バックエンドの AUG_SPEC と範囲を揃える（jp=日本語訳, desc=ホバー説明）
const PARAM_SPEC: { key: string; jp: string; desc: string; min: number; max: number; step: number; int?: boolean }[] = [
  { key: "degrees", jp: "回転角度", desc: "画像をランダムに±この角度まで回転させる拡張。", min: 0, max: 180, step: 1 },
  { key: "translate", jp: "平行移動", desc: "画像を上下左右にランダム移動させる割合。", min: 0, max: 1, step: 0.01 },
  { key: "scale", jp: "拡大縮小", desc: "画像をランダムに拡大/縮小させる割合。", min: 0, max: 2, step: 0.05 },
  { key: "shear", jp: "せん断", desc: "画像を斜めに歪ませるせん断変形（度）。", min: 0, max: 45, step: 0.5 },
  { key: "perspective", jp: "遠近変形", desc: "遠近感を付ける変形。値は非常に小さく設定する。", min: 0, max: 0.001, step: 0.0001 },
  { key: "flipud", jp: "上下反転", desc: "画像を上下反転する確率。", min: 0, max: 1, step: 0.05 },
  { key: "fliplr", jp: "左右反転", desc: "画像を左右反転する確率。", min: 0, max: 1, step: 0.05 },
  { key: "mosaic", jp: "モザイク合成", desc: "4枚の画像を合成して学習する拡張。小物体の検出に効く場合がある。", min: 0, max: 1, step: 0.05 },
  { key: "mixup", jp: "画像混合", desc: "2枚の画像を半透明で重ねる拡張。", min: 0, max: 1, step: 0.05 },
  { key: "copy_paste", jp: "コピー＆ペースト合成", desc: "物体を切り出して別画像へ貼り付ける拡張（セグメンテーション向け）。", min: 0, max: 1, step: 0.05 },
  { key: "hsv_h", jp: "色相変化", desc: "色相(Hue)をランダムに変化させる割合。", min: 0, max: 1, step: 0.005 },
  { key: "hsv_s", jp: "彩度変化", desc: "彩度(Saturation)をランダムに変化させる割合。", min: 0, max: 1, step: 0.05 },
  { key: "hsv_v", jp: "明度変化", desc: "明度(Value)をランダムに変化させる割合。", min: 0, max: 1, step: 0.05 },
  { key: "close_mosaic", jp: "終盤モザイク停止epoch", desc: "学習終盤のこのepoch数だけmosaicを無効化し、本来の画像で仕上げる。", min: 0, max: 50, step: 1, int: true },
];

const STANDARD: AugmentationParams = {
  degrees: 5.0, translate: 0.1, scale: 0.5, shear: 0.0, perspective: 0.0,
  flipud: 0.0, fliplr: 0.5, mosaic: 1.0, mixup: 0.0, copy_paste: 0.0,
  hsv_h: 0.015, hsv_s: 0.7, hsv_v: 0.4, close_mosaic: 10,
};

interface Props {
  selected: string; // 学習に使用するプリセット名（親と同期）
  onSelect: (name: string) => void;
}

export default function AugmentationPanel({ selected, onSelect }: Props) {
  const { name = "" } = useParams();
  const [presets, setPresets] = useState<AugmentationPreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const [description, setDescription] = useState("");
  const [params, setParams] = useState<AugmentationParams>({ ...STANDARD });
  const [builtin, setBuiltin] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function reload(): Promise<AugmentationPreset[]> {
    try {
      const r = await api.listPresets(name);
      setPresets(r.presets);
      return r.presets;
    } catch (e) {
      setError(String(e));
      return [];
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);

  // 学習で選択中のプリセットをエディタへ読み込む（一覧更新・選択変更に追従）
  useEffect(() => {
    if (presets.length === 0) return;
    const p = presets.find((x) => x.name === selected) ?? presets[0];
    if (!p) return;
    setPresetName(p.name);
    setDescription(p.description);
    setParams({ ...STANDARD, ...p.params });
    setBuiltin(p.builtin);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, presets]);

  function loadPreset(p: AugmentationPreset) {
    setError("");
    setMsg("");
    onSelect(p.name);
  }

  function newPreset() {
    setPresetName("");
    setDescription("");
    setParams({ ...STANDARD });
    setBuiltin(false);
    setError("");
    setMsg("");
  }

  function setParam(key: string, value: number) {
    setParams((prev) => ({ ...prev, [key]: value }));
  }

  async function save() {
    setError("");
    setMsg("");
    if (!presetName.trim()) {
      setError("プリセット名を入力してください。");
      return;
    }
    try {
      const saved = presetName.trim();
      await api.savePreset(name, saved, description, params);
      setMsg(`保存しました: ${saved}`);
      setBuiltin(false);
      await reload();
      onSelect(saved); // 保存したプリセットを学習に使用
    } catch (e) {
      setError(String(e));
    }
  }

  async function remove(p: AugmentationPreset) {
    if (p.builtin) return;
    if (!window.confirm(`プリセット '${p.name}' を削除しますか？`)) return;
    try {
      await api.deletePreset(name, p.name);
      const rest = await reload();
      if (selected === p.name) onSelect(rest[0]?.name ?? "standard");
    } catch (e) {
      setError(String(e));
    }
  }

  const selectedIsUser = presets.find((p) => p.name === selected && !p.builtin);

  return (
    <div className="aug-panel">
      <p className="muted" style={{ fontSize: "0.8rem", marginTop: 0 }}>
        学習時に画像へ回転・拡大縮小・色変化などを加え、汎化性能を高める設定です。
        ここで選択・保存したプリセットが左の学習ジョブに使われます。
      </p>

      <div className="row aug-preset-bar">
        <label className="field aug-preset-select" style={{ flex: 1, minWidth: 240 }}>
          使用プリセット
          <select
            value={selected}
            style={{ width: "100%" }}
            onChange={(e) => loadPreset(presets.find((p) => p.name === e.target.value)!)}
          >
            {presets.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
                {p.builtin ? "（builtin）" : "（user）"}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={newPreset}>＋ 新規</button>
        {selectedIsUser && (
          <button type="button" className="danger" onClick={() => remove(selectedIsUser)}>
            削除
          </button>
        )}
      </div>

      <div className="row">
        <label className="field">
          プリセット名
          <input
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            placeholder="例: my_light"
            style={{ width: 180 }}
          />
        </label>
        <label className="field" style={{ flex: 1, minWidth: 160 }}>
          説明
          <input value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: "100%" }} />
        </label>
      </div>
      {builtin && (
        <div className="warn" style={{ fontSize: "0.78rem" }}>
          builtin プリセットです。編集内容は別名で保存すると新規ユーザープリセットになります。
        </div>
      )}

      <div className="table-scroll aug-table">
        <table className="table">
          <thead>
            <tr><th>パラメータ</th><th>スライダー</th><th>値</th></tr>
          </thead>
          <tbody>
            {PARAM_SPEC.map((s) => (
              <tr key={s.key}>
                <td className="aug-pname">
                  <code>{s.key}</code>（{s.jp}）<InfoTooltip text={s.desc} />
                </td>
                <td className="aug-slider">
                  <input
                    type="range"
                    min={s.min}
                    max={s.max}
                    step={s.step}
                    value={params[s.key] ?? 0}
                    onChange={(e) => setParam(s.key, Number(e.target.value))}
                    style={{ width: "100%" }}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min={s.min}
                    max={s.max}
                    step={s.step}
                    value={params[s.key] ?? 0}
                    onChange={(e) => setParam(s.key, s.int ? Math.round(Number(e.target.value)) : Number(e.target.value))}
                    style={{ width: 80 }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="row">
        <button type="button" onClick={save}>プリセットを保存</button>
        {msg && <span className="success">{msg}</span>}
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}
