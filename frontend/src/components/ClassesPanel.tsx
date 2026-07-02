// クラス設計パネル（プロジェクト準備画面のセクション）。追加・編集・色設定・保存。
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

interface Row {
  name: string;
  color: string;
}

const PALETTE = [
  "#ff4d4f", "#1677ff", "#52c41a", "#faad14", "#722ed1",
  "#13c2c2", "#eb2f96", "#a0d911", "#fa8c16", "#2f54eb",
];

export default function ClassesPanel() {
  const { name = "" } = useParams();
  const [rows, setRows] = useState<Row[]>([]);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  useEffect(() => {
    api
      .getClasses(name)
      .then((r) => setRows(r.classes.map((c) => ({ name: c.name, color: c.color }))))
      .catch((e) => setError(String(e)));
  }, [name]);

  function addClass() {
    const n = newName.trim();
    if (!n) return;
    setRows([...rows, { name: n, color: PALETTE[rows.length % PALETTE.length] }]);
    setNewName("");
    setSaved("");
  }

  function editName(i: number, value: string) {
    const next = [...rows];
    next[i] = { ...next[i], name: value };
    setRows(next);
    setSaved("");
  }

  function editColor(i: number, value: string) {
    const next = [...rows];
    next[i] = { ...next[i], color: value };
    setRows(next);
    setSaved("");
  }

  function removeClass(i: number) {
    setRows(rows.filter((_, idx) => idx !== i));
    setSaved("");
  }

  async function save() {
    setError("");
    setSaved("");
    try {
      const r = await api.saveClasses(
        name,
        rows.map((row) => ({ name: row.name, color: row.color }))
      );
      setRows(r.classes.map((c) => ({ name: c.name, color: c.color })));
      setSaved("保存しました（classes.yaml）。");
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <section className="card">
      <h2>クラス設計</h2>
      <p className="muted" style={{ fontSize: "0.78rem" }}>
        IDは並び順から0始まりで自動採番。色はアノテ枠の表示用（保存ラベルには含みません）。
      </p>

      <div className="class-add">
        <input
          placeholder="クラス名を追加（例: ct_h）"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addClass()}
        />
        <button onClick={addClass} disabled={!newName.trim()}>
          追加
        </button>
      </div>

      <ul className="class-list">
        {rows.map((row, i) => (
          <li key={i} className="class-item" style={{ borderLeftColor: row.color }}>
            <span className="class-id">{i}</span>
            <input
              type="color"
              className="class-color"
              value={row.color}
              title="色を変更"
              onChange={(e) => editColor(i, e.target.value)}
            />
            <input
              className="class-name"
              value={row.name}
              onChange={(e) => editName(i, e.target.value)}
            />
            <button className="class-del" title="削除" onClick={() => removeClass(i)}>
              ×
            </button>
          </li>
        ))}
        {rows.length === 0 && <li className="muted">クラスがありません。</li>}
      </ul>

      <div className="row">
        <button onClick={save} disabled={rows.length === 0}>
          保存
        </button>
        {saved && <span className="success">{saved}</span>}
      </div>
      {error && <div className="error">{error}</div>}
    </section>
  );
}
