import { useEffect, useState } from "react";
import { api } from "../api/client";
import { getDisplayName, setDisplayName } from "../api/identity";

// shared server mode時のみ、初回アクセスで簡単な名前入力を行う。
// これはセキュリティ認証ではなく、job/projectの所有者識別用（Issue #49 §7）。
export default function IdentityPrompt() {
  const [needsName, setNeedsName] = useState(false);
  const [input, setInput] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .getServerInfo()
      .then((info) => {
        if (!cancelled && info.shared_server_mode && !getDisplayName()) {
          setNeedsName(true);
        }
      })
      .catch(() => {
        // server-info取得に失敗した場合はlocal mode相当として何も表示しない
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!needsName) return null;

  const submit = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    setDisplayName(trimmed);
    setNeedsName(false);
  };

  return (
    <div className="identity-overlay">
      <div className="card identity-card">
        <h2>お名前を入力してください</h2>
        <p className="muted">
          このサーバーは複数人で共有しています。入力したお名前は学習ジョブ・
          プロジェクトの所有者表示にのみ使われます（ログイン認証ではありません）。
        </p>
        <input
          autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="例: 橋本"
        />
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button onClick={submit} disabled={!input.trim()}>
            開始
          </button>
        </div>
      </div>
    </div>
  );
}
