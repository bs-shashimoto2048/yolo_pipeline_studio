// shared server mode: user identity（認証ではない、job/project所有者識別用。Issue #49 §7/§81）。
// localStorageに保持し、ブラウザを閉じても同じidentityとして復帰する（§79）。
const USER_ID_KEY = "yts_user_id";
const DISPLAY_NAME_KEY = "yts_display_name";

function generateUserId(): string {
  // crypto.randomUUID()はsecure context(https / localhost)でのみ利用可能。
  // Issue #49の主要ユースケースであるLAN経由のhttpアクセスでは使えないため、
  // Math.randomベースのUUID風文字列にフォールバックする
  // （認証ではなくjob/project所有者識別用のため暗号学的強度は不要）。
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      // secure contextでないと実行時に例外になる場合があるため、下のfallbackへ進む
    }
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function getOrCreateUserId(): string {
  let id = localStorage.getItem(USER_ID_KEY);
  if (!id) {
    id = generateUserId();
    localStorage.setItem(USER_ID_KEY, id);
  }
  return id;
}

export function getDisplayName(): string | null {
  return localStorage.getItem(DISPLAY_NAME_KEY);
}

export function setDisplayName(name: string): void {
  localStorage.setItem(DISPLAY_NAME_KEY, name);
}

// HTTPヘッダはASCII以外を直接格納できないため、日本語表示名はencodeURIComponent()
// してから送る（backend側 app.core.identity.get_current_user が unquote()する）。
export function identityHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "X-YTS-User-Id": getOrCreateUserId() };
  const displayName = getDisplayName();
  if (displayName) {
    headers["X-YTS-Display-Name"] = encodeURIComponent(displayName);
  }
  return headers;
}
