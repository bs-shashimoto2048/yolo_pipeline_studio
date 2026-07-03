// データセット作成画面。作成フォーム・結果サマリー・作成済み一覧を表示する。
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import LabelCheckPanel from "../components/LabelCheckPanel";
import type {
  DatasetCreateResponse,
  DatasetListItem,
} from "../types";

export default function DatasetPage() {
  const { name = "" } = useParams();
  const [datasetName, setDatasetName] = useState("dataset_001");
  const [trainRatio, setTrainRatio] = useState(0.8);
  const [valRatio, setValRatio] = useState(0.2);
  const [testRatio, setTestRatio] = useState(0.0);
  const [seed, setSeed] = useState(42);
  const [includeEmpty, setIncludeEmpty] = useState(true);
  const [includeUnlabeled, setIncludeUnlabeled] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [imageSource, setImageSource] = useState("auto");
  const [useSelection, setUseSelection] = useState(true);
  const [includeReview, setIncludeReview] = useState(false);

  const [datasets, setDatasets] = useState<DatasetListItem[]>([]);
  const [result, setResult] = useState<DatasetCreateResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    try {
      const r = await api.listDatasets(name);
      setDatasets(r.datasets);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    reload();
  }, [name]);

  const ratioSum = trainRatio + valRatio + testRatio;
  const ratioValid = Math.abs(ratioSum - 1.0) < 1e-6;

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const res = await api.createDataset(name, {
        dataset_name: datasetName.trim(),
        train_ratio: trainRatio,
        val_ratio: valRatio,
        test_ratio: testRatio,
        seed,
        include_empty_labels: includeEmpty,
        include_unlabeled_images: includeUnlabeled,
        overwrite,
        image_source: imageSource,
        use_selection: useSelection,
        include_review_images: includeReview,
      });
      setResult(res);
      await reload();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>データセット作成: {name}</h1>
      <p className="muted">
        raw/images と annotations/labels、classes.yaml から YOLO 学習用データセット
        （train/val/test 分割 + data.yaml）を生成します。<strong>まず右の「ラベル品質チェック」で
        error がないことを確認</strong>してから、左のフォームで作成してください。
      </p>

      {/* 左: 作成フォーム(4) / 右: ラベル品質チェック(6) */}
      <div className="dataset-cols">
        {/* 左: 作成フォーム */}
        <section className="card">
          <h2>作成フォーム</h2>
          <form onSubmit={onCreate}>
            <h3 className="ds-group-title">基本</h3>
            <div className="dataset-fields">
              <label className="field field-wide">
                dataset_name
                <input value={datasetName} onChange={(e) => setDatasetName(e.target.value)} required />
              </label>
              <label className="field">
                seed
                <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
              </label>
            </div>

            <h3 className="ds-group-title">
              分割比率
              <span className={"ds-ratio " + (ratioValid ? "muted" : "error")}>合計 {ratioSum.toFixed(2)}</span>
            </h3>
            <div className="dataset-fields">
              <label className="field">
                train_ratio
                <input type="number" step="0.05" min="0" max="1" value={trainRatio} onChange={(e) => setTrainRatio(Number(e.target.value))} />
              </label>
              <label className="field">
                val_ratio
                <input type="number" step="0.05" min="0" max="1" value={valRatio} onChange={(e) => setValRatio(Number(e.target.value))} />
              </label>
              <label className="field">
                test_ratio
                <input type="number" step="0.05" min="0" max="1" value={testRatio} onChange={(e) => setTestRatio(Number(e.target.value))} />
              </label>
            </div>

            <h3 className="ds-group-title">対象画像</h3>
            <div className="dataset-fields">
              <label className="field field-wide">
                画像ソース
                <select value={imageSource} onChange={(e) => setImageSource(e.target.value)}>
                  <option value="auto">auto（processed優先）</option>
                  <option value="raw">raw</option>
                  <option value="processed">processed</option>
                </select>
              </label>
            </div>
            <div className="ds-checks">
              <label>
                <input type="checkbox" checked={useSelection} onChange={(e) => setUseSelection(e.target.checked)} /> 画像選別を反映（excludedを除外）
              </label>
              <label>
                <input type="checkbox" checked={includeReview} onChange={(e) => setIncludeReview(e.target.checked)} /> review画像も含める
              </label>
              <label>
                <input type="checkbox" checked={includeEmpty} onChange={(e) => setIncludeEmpty(e.target.checked)} /> 空ラベル画像を含める
              </label>
              <label>
                <input type="checkbox" checked={includeUnlabeled} onChange={(e) => setIncludeUnlabeled(e.target.checked)} /> 未ラベル画像を含める
              </label>
            </div>

            <h3 className="ds-group-title">実行</h3>
            <div className="row ds-run">
              <label>
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> 上書き（overwrite）
              </label>
              <button type="submit" disabled={busy || !ratioValid || !datasetName.trim()}>
                {busy ? "作成中…" : "作成"}
              </button>
            </div>
          </form>
          {error && <div className="error">{error}</div>}
          {result && (
            <div className="card">
              <strong>作成しました: {result.dataset_name}</strong>
              {result.warning && <div className="warn">{result.warning}</div>}
              <ul className="compact">
                <li>画像ソース: {result.image_source}</li>
                <li>train: {result.summary.train_image_count} 枚</li>
                <li>val: {result.summary.val_image_count} 枚</li>
                <li>test: {result.summary.test_image_count} 枚</li>
                <li>合計: {result.summary.total_image_count} 枚 / クラス数: {result.summary.class_count}</li>
                <li>data.yaml: <code>{result.data_yaml_path}</code></li>
              </ul>
            </div>
          )}
        </section>

        {/* 右: ラベル品質チェック（作成前チェック） */}
        <LabelCheckPanel />
      </div>

      <section className="card">
        <h2>作成済みデータセット（{datasets.length}）</h2>
        {datasets.length === 0 ? (
          <p className="muted">まだありません。</p>
        ) : (
          <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>名前</th>
                <th>作成日時</th>
                <th>train</th>
                <th>val</th>
                <th>test</th>
                <th>クラス</th>
                <th>data.yaml</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((d) => (
                <tr key={d.dataset_name}>
                  <td>{d.dataset_name}</td>
                  <td className="muted">{d.created_at ?? "-"}</td>
                  <td>{d.train_image_count}</td>
                  <td>{d.val_image_count}</td>
                  <td>{d.test_image_count}</td>
                  <td>{d.class_count}</td>
                  <td>
                    <code>{d.data_yaml_path}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </section>
    </div>
  );
}
