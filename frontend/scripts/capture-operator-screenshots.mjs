// 作業者向けマニュアル(Issue #2)用のスクリーンショットを自動撮影するスクリプト。
//
// 前提:
//   - フロントエンド dev server (デフォルト http://localhost:5173) が起動していること
//   - バックエンド (http://localhost:8000) が起動していること
//   - 秘密情報を含まない専用のテストプロジェクトで実行すること
//     （本スクリプトは "operator_docs_demo" という名前のプロジェクトを新規作成して使う）
//   - 学習/推論/映像/ONNX/SAM/撮影は YTS_*_DRY_RUN=1 でバックエンドを起動しておくと高速・安全
//
// 実行:
//   node scripts/capture-operator-screenshots.mjs [--base-url=http://localhost:5173] [--out=../docs/images/operator]
//
// このスクリプトは docs 作成(Issue #2 Checkpoint 2)専用で、アプリ本体のコードは一切変更しない。
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function argValue(flag, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${flag}=`));
  return hit ? hit.split("=").slice(1).join("=") : fallback;
}

const BASE_URL = argValue("base-url", "http://localhost:5173");
const API_BASE = argValue("api-base", "http://localhost:8000");
const OUT_DIR = path.resolve(__dirname, argValue("out", "../../docs/images/operator"));
const SAMPLE_DIR = argValue("sample-dir", null);
const PROJECT_NAME = "operator_docs_demo";

// 発見事項: page.waitForFunction() に非同期の述語関数を渡すと、ブラウザ内でのポーリング
// タイミングの都合で真の完了より大幅に早く解決してしまう事象が再現した（原因未特定）。
// バックエンドへは Node 側から直接 fetch する方が確実なため、ジョブ完了待ちはブラウザを
// 介さずここで行う。
async function waitForJobStatus(kind, jobId, { timeoutMs = 120000, intervalMs = 1000 } = {}) {
  const url = `${API_BASE}/api/projects/${PROJECT_NAME}/${kind}/${jobId}`;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        if (d.status === "completed" || d.status === "failed") {
          return d.status;
        }
      }
    } catch {
      // 一時的な接続エラーは無視してリトライする
    }
    await new Promise((res) => setTimeout(res, intervalMs));
  }
  throw new Error(`waitForJobStatus timeout: ${kind}/${jobId}`);
}

fs.mkdirSync(OUT_DIR, { recursive: true });

const results = []; // { file, ok, note }

function shotPath(name) {
  return path.join(OUT_DIR, name);
}

async function shoot(page, name, opts = {}) {
  const p = shotPath(name);
  await page.screenshot({ path: p, fullPage: opts.fullPage ?? true });
  results.push({ file: name, ok: true, note: opts.note ?? "" });
  console.log("[OK]", name);
}

async function step(label, fn) {
  try {
    await fn();
  } catch (e) {
    console.error("[FAIL]", label, e.message);
    results.push({ file: label, ok: false, note: String(e.message).split("\n")[0] });
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // --- 1. 入口 / プロジェクト選択 ---
  await step("01-projects-list.png", async () => {
    await page.goto(BASE_URL + "/", { waitUntil: "networkidle" });
    await page.waitForSelector("text=新規プロジェクト作成");
    await shoot(page, "01-projects-list.png", { note: "入口: プロジェクト一覧+新規作成フォーム" });
  });

  // --- プロジェクト作成 ---
  // 発見事項: 作成しても自動でプロジェクトへ遷移しない実装（onCreateはリスト再読込のみ）。
  // 一覧に追加された行の「開く」を押して初めてプロジェクトへ入る（作業者マニュアルに明記が必要）。
  await step("create-project", async () => {
    await page.fill('input[placeholder^="プロジェクト名"]', PROJECT_NAME);
    await page.fill('input[placeholder^="説明"]', "作業者マニュアル用テストプロジェクト（秘密情報なし）");
    await page.click('button[type="submit"]:has-text("作成")');
    await page.waitForSelector(`text=${PROJECT_NAME}`, { timeout: 10000 });
  });
  await step("01b-projects-list-after-create.png", async () => {
    await shoot(page, "01b-projects-list-after-create.png", {
      note: "プロジェクト作成後の一覧（「開く」を押して入る）",
    });
  });
  await step("open-project", async () => {
    const row = page.locator("tr", { hasText: PROJECT_NAME });
    await row.locator("button:has-text('開く')").click();
    await page.waitForFunction(
      (proj) => location.pathname.includes(`/p/${proj}/setup`),
      PROJECT_NAME,
      { timeout: 15000 }
    );
    console.log("  -> URL after open:", page.url());
  });

  // --- 2. プロジェクト準備（概要/クラス設計） ---
  await step("02-setup-overview-classes.png", async () => {
    await shoot(page, "02-setup-overview-classes.png", { note: "プロジェクト準備: 概要+クラス設計（初期状態）" });
  });

  await step("add-classes", async () => {
    const names = ["object_a", "object_b", "object_c"];
    for (const n of names) {
      await page.fill('input[placeholder^="クラス名を追加"]', n);
      await page.click('button:has-text("追加")');
    }
    await page.click('button:has-text("保存"):not(:has-text("フォルダ"))');
    await page.waitForSelector("text=保存しました", { timeout: 5000 });
  });

  await step("03-setup-classes-saved.png", async () => {
    await shoot(page, "03-setup-classes-saved.png", { note: "クラス設計: 追加・保存後" });
  });

  // --- 画像取り込み: 個別アップロード ---
  await step("upload-images", async () => {
    await page.click('button:has-text("個別アップロード")');
    await page.waitForSelector(".im-method-upload");
    if (SAMPLE_DIR) {
      const files = fs
        .readdirSync(SAMPLE_DIR)
        .filter((f) => /\.(jpg|jpeg|png)$/i.test(f))
        .map((f) => path.join(SAMPLE_DIR, f));
      await page.locator(".im-method-upload input[type=file]").setInputFiles(files);
      await page.waitForSelector(".import-result", { timeout: 15000 });
    }
  });

  await step("04-setup-images-uploaded.png", async () => {
    await shoot(page, "04-setup-images-uploaded.png", { note: "画像取り込み: 個別アップロード結果+登録画像一覧" });
  });

  // --- 画像取り込み: カメラ・URLで撮影タブ（空状態。実カメラ/URLは接続しない） ---
  await step("05-setup-capture-tab.png", async () => {
    await page.click('button:has-text("カメラ・URLで撮影")');
    await page.waitForSelector("text=撮影ソース", { timeout: 5000 }).catch(() => {});
    await shoot(page, "05-setup-capture-tab.png", { note: "撮影ソース（カメラ/URL）タブ: 初期状態（未登録）" });
  });

  // --- 撮影ソース新規登録フォーム（placeholderの実IPを修正済みのため撮影可能） ---
  await step("05b-setup-capture-add-form.png", async () => {
    await page.click('button:has-text("ソースを追加")');
    await page.waitForSelector(".capture-source-add", { timeout: 5000 });
    await page.locator(".capture-source-add select").first().selectOption("url");
    await page.locator('.capture-source-add input[placeholder*="mjpg"]').fill("http://192.0.2.10/mjpg/video.mjpg?camera=1");
    await page.locator('.capture-source-add label:has-text("名前") input').fill("デモ用カメラ");
    await shoot(page, "05b-setup-capture-add-form.png", {
      note: "撮影ソース新規登録フォーム（例示用ダミーURLを入力。placeholder修正後で実IP非表示）",
    });
    await page.click('.capture-source-add button:has-text("キャンセル")');
  });

  // --- 画像取り込み: フォルダ取り込みタブ（ローカルパスは入力しない、UIのみ） ---
  await step("06-setup-folder-import-tab.png", async () => {
    await page.click('button:has-text("フォルダ取り込み")');
    await page.waitForSelector(".im-method-folder");
    await shoot(page, "06-setup-folder-import-tab.png", { note: "フォルダ取り込みタブ（パス未入力の初期状態）" });
  });

  // --- 3. 画像選別 ---
  await step("goto-selection", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/selection`, { waitUntil: "networkidle" });
  });
  await step("07-selection-before-run.png", async () => {
    await shoot(page, "07-selection-before-run.png", { note: "画像選別: 実行前" });
  });
  await step("run-selection", async () => {
    await page.click('button:has-text("チェック実行")');
    await page.waitForSelector("text=実行中…", { timeout: 3000 }).catch(() => {});
    await page.waitForFunction(
      () => !document.body.innerText.includes("実行中…"),
      { timeout: 20000 }
    );
  });
  await step("08-selection-after-run.png", async () => {
    await shoot(page, "08-selection-after-run.png", { note: "画像選別: 実行後（included/excluded/review）" });
  });

  // --- 4. 前処理 ---
  await step("goto-preprocess", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/preprocess`, { waitUntil: "networkidle" });
  });
  await step("09-preprocess-settings.png", async () => {
    await shoot(page, "09-preprocess-settings.png", { note: "前処理設定画面（実行前）" });
  });
  await step("run-preprocess", async () => {
    await page.click('button:has-text("前処理を実行")');
    await page.waitForFunction(() => !document.body.innerText.includes("実行中…"), { timeout: 30000 });
  });
  await step("10-preprocess-after-run.png", async () => {
    await shoot(page, "10-preprocess-after-run.png", { note: "前処理: 実行後（processed情報）" });
  });

  // --- 5. アノテーション ---
  await step("goto-annotate", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/annotate`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
  });
  await step("11-annotate-initial.png", async () => {
    await shoot(page, "11-annotate-initial.png", { note: "アノテーション画面: 初期状態（画像+クラス一覧）" });
  });
  await step("annotate-draw-box", async () => {
    // 最初のクラスを選択してからキャンバス上でドラッグしてBBOXを1つ作成する
    const classChip = page.locator(".annot-classes button, .class-chip, button:has-text('object_a')").first();
    if (await classChip.count()) {
      await classChip.click();
    }
    const canvas = page.locator(".konvajs-content canvas").first();
    const box = await canvas.boundingBox();
    if (box) {
      const x0 = box.x + box.width * 0.35;
      const y0 = box.y + box.height * 0.3;
      const x1 = box.x + box.width * 0.6;
      const y1 = box.y + box.height * 0.6;
      await page.mouse.move(x0, y0);
      await page.mouse.down();
      await page.mouse.move(x1, y1, { steps: 8 });
      await page.mouse.up();
      await page.waitForTimeout(300);
    }
  });
  await step("12-annotate-with-box.png", async () => {
    await shoot(page, "12-annotate-with-box.png", { note: "アノテーション: BBOX作成後" });
  });
  await step("annotate-save-and-label-rest", async () => {
    // Walkthrough発見事項: マニュアルは1枚のBBOX作成のみを示しており、「次の画像へ進んで
    // 全画像を繰り返しラベル付けする」操作が明記されていなかった。実データでの学習・推論・
    // 分析を検証するため、ここで全6枚を保存する。
    await page.click('button.primary:has-text("保存")');
    await page.waitForTimeout(300);
    for (let i = 0; i < 5; i++) {
      await page.click('button[title="次の画像 (→)"]');
      await page.waitForTimeout(300);
      const canvas = page.locator(".konvajs-content canvas").first();
      const box = await canvas.boundingBox();
      if (box) {
        const x0 = box.x + box.width * 0.3;
        const y0 = box.y + box.height * 0.25;
        const x1 = box.x + box.width * 0.55;
        const y1 = box.y + box.height * 0.55;
        await page.mouse.move(x0, y0);
        await page.mouse.down();
        await page.mouse.move(x1, y1, { steps: 8 });
        await page.mouse.up();
        await page.waitForTimeout(200);
      }
      await page.click('button.primary:has-text("保存")');
      await page.waitForTimeout(300);
    }
  });

  // --- 6. データセット作成 ---
  await step("goto-dataset", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/dataset`, { waitUntil: "networkidle" });
  });
  await step("13-dataset-form.png", async () => {
    await shoot(page, "13-dataset-form.png", { note: "データセット作成フォーム（ラベル品質チェック含む）" });
  });
  await step("relax-dataset-filters-for-demo", async () => {
    // デモ用の合成画像は選別で review/excluded になり得るため、対象画像0枚を避けるべく
    // 「review画像も含める」「未ラベル画像を含める」を有効化する（実在するUI操作の組み合わせ）。
    const includeReview = page.locator('label:has-text("review画像も含める") input[type=checkbox]');
    const includeUnlabeled = page.locator('label:has-text("未ラベル画像を含める") input[type=checkbox]');
    if ((await includeReview.count()) && !(await includeReview.isChecked())) {
      await includeReview.check();
    }
    if ((await includeUnlabeled.count()) && !(await includeUnlabeled.isChecked())) {
      await includeUnlabeled.check();
    }
  });
  await step("create-dataset", async () => {
    await page.click('button[type="submit"]:has-text("作成")');
    await page.waitForFunction(() => !document.body.innerText.includes("作成中…"), { timeout: 20000 });
    const ok = await page.locator("text=作成しました").count();
    const err = await page.locator(".error").allTextContents();
    console.log("  -> dataset create success text found:", ok > 0, "errors:", err);
  });
  await step("14-dataset-created.png", async () => {
    await shoot(page, "14-dataset-created.png", { note: "データセット作成後（一覧に追加）" });
  });

  // --- 7. 学習 ---
  await step("goto-train", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/train`, { waitUntil: "networkidle" });
  });
  await step("15-train-form.png", async () => {
    await shoot(page, "15-train-form.png", { note: "学習ジョブ開始フォーム+データ拡張プリセット" });
  });
  await step("select-dataset-and-start-train", async () => {
    const sel = page.locator("select").first();
    const optCount = await sel.locator("option").count();
    console.log("  -> dataset select option count:", optCount);
    if (optCount > 1) {
      await sel.selectOption({ index: 1 });
    }
    // 実学習でも短時間で完了するよう、epochs/imgsz/batchを小さくする
    // （ドライラン時はこれらの値は無視されるため無害）。
    await page.locator('label:has-text("epochs") input').fill("3");
    await page.locator('label:has-text("imgsz") input').fill("320");
    await page.locator('label:has-text("batch") input').fill("2");
    await page.click('button[type="submit"]:has-text("開始")');
    await page.waitForTimeout(1000);
  });
  await step("16-train-job-started.png", async () => {
    await shoot(page, "16-train-job-started.png", { note: "学習ジョブ開始直後（一覧・状態）" });
  });
  await step("wait-train-complete", async () => {
    // 発見事項: page.waitForFunction()にブラウザ内非同期述語を渡す方式は、真の完了より
    // 大幅に早く解決してしまう事象が繰り返し再現した（原因未特定、Playwright側の挙動の
    // 可能性）。Node側から直接APIをポーリングする方式に切り替えて確実性を担保する。
    const t0 = Date.now();
    const status = await waitForJobStatus("train-jobs", "train_001", { timeoutMs: 120000 });
    console.log("  -> [debug] train job reached", status, "after", Date.now() - t0, "ms");
    await page.goto(page.url(), { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(500);
  });
  await step("17-train-job-completed.png", async () => {
    await shoot(page, "17-train-job-completed.png", { note: "学習ジョブ完了後の状態表示" });
  });

  // --- 8. 評価 ---
  await step("goto-eval", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/eval`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
  });
  await step("18-evaluate.png", async () => {
    await shoot(page, "18-evaluate.png", { note: "学習成果物・評価サマリー" });
  });

  // --- 9. モデル選択 ---
  await step("goto-models", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/models`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
  });
  await step("19-models-list.png", async () => {
    await shoot(page, "19-models-list.png", { note: "モデル管理: best/last一覧" });
  });

  // --- 10. 静止画推論 ---
  await step("goto-infer", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/infer`, { waitUntil: "networkidle" });
    // 学習ジョブ選択肢が「completed」を表示するまで待つ（起動直後は一覧取得が
    // 学習完了より前のタイミングで走り「running」のまま残ることがあるため）。
    await page.waitForFunction(
      () => document.querySelector("select")?.textContent?.includes("completed"),
      { timeout: 15000 }
    ).catch(async () => {
      await page.reload({ waitUntil: "networkidle" });
    });
  });
  await step("20-infer-image-form.png", async () => {
    await shoot(page, "20-infer-image-form.png", { note: "推論テスト: 画像モード フォーム" });
  });
  await step("run-image-predict", async () => {
    const trainSel = page.locator("select").first();
    const optCount = await trainSel.locator("option").count();
    console.log("  -> train_job_id select option count:", optCount);
    if (optCount > 1) {
      await trainSel.selectOption({ index: 1 });
    }
    // 推論対象画像を最低1枚選択しないと「1枚以上選択してください」で弾かれる。
    await page.locator(".predict-thumb-grid figure.thumb.selectable").first().click();
    await page.click('button[type="submit"].predict-start');
    // train同様、Node側から直接APIをポーリングして完了を確認する。
    const status = await waitForJobStatus("predict-jobs", "predict_001", { timeoutMs: 30000 });
    console.log("  -> [debug] predict job reached", status);
    await page.goto(page.url(), { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(500);
  });
  await step("21-infer-image-result.png", async () => {
    await shoot(page, "21-infer-image-result.png", { note: "推論テスト: 画像モード 実行結果" });
  });

  // --- 11. 映像/URL推論（UIのみ。実カメラ/URLへは接続しない） ---
  await step("open-video-mode", async () => {
    await page.click('button:has-text("映像（カメラ/URL）")');
    await page.waitForTimeout(500);
  });
  await step("22-infer-video-camera-form.png", async () => {
    await shoot(page, "22-infer-video-camera-form.png", { note: "推論テスト: 映像モード（カメラ）フォーム" });
  });
  await step("switch-to-url-source", async () => {
    await page.locator("select").filter({ hasText: "ローカルカメラ" }).selectOption("url").catch(async () => {
      // フォールバック: 値指定
      const sels = page.locator("select");
      const count = await sels.count();
      for (let i = 0; i < count; i++) {
        const has = await sels.nth(i).locator('option[value="url"]').count();
        if (has) {
          await sels.nth(i).selectOption("url");
          break;
        }
      }
    });
    await page.waitForTimeout(300);
  });
  await step("fill-safe-example-url", async () => {
    // placeholderは既にRFC5737の例示アドレスへ修正済みだが、念のため入力欄にも
    // 明示的にダミーURLを入れて撮影する（防御的な二重対策）。
    const urlInput = page.locator('input[placeholder*="mjpg"]').first();
    if (await urlInput.count()) {
      await urlInput.fill("http://192.0.2.10/mjpg/video.mjpg?camera=1");
    }
  });
  await step("23-infer-video-url-form.png", async () => {
    await shoot(page, "23-infer-video-url-form.png", {
      note: "推論テスト: 映像モード（URL）フォーム（例示用ダミーURLを入力。placeholderの実IPが映らないよう上書き）",
    });
  });

  // --- 12. 誤検出分析 / 実験履歴 / レポート ---
  await step("goto-analysis", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/analysis`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
  });
  await step("run-analysis", async () => {
    // 推論ジョブが存在する場合は選択して分析実行まで行う（実データでの表示を撮影するため）。
    const sel = page.locator("select").first();
    const optCount = await sel.locator("option").count();
    console.log("  -> predict job select option count (analysis):", optCount);
    if (optCount > 1) {
      await sel.selectOption({ index: 1 });
      await page.click('button:has-text("分析実行")');
      await page.waitForFunction(() => !document.body.innerText.includes("分析中…"), { timeout: 20000 });
    }
  });
  await step("24-analysis.png", async () => {
    await shoot(page, "24-analysis.png", { note: "誤検出分析画面" });
  });

  await step("goto-experiments", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/experiments`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
  });
  await step("25-experiments.png", async () => {
    await shoot(page, "25-experiments.png", { note: "実験履歴画面" });
  });

  await step("goto-reports", async () => {
    await page.goto(`${BASE_URL}/p/${PROJECT_NAME}/reports`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
  });
  await step("26-reports-form.png", async () => {
    await shoot(page, "26-reports-form.png", { note: "レポート生成フォーム" });
  });
  await step("generate-report", async () => {
    await page.click('button:has-text("レポート生成")');
    await page.waitForTimeout(2000);
  });
  await step("27-reports-generated.png", async () => {
    await shoot(page, "27-reports-generated.png", { note: "レポート生成後の一覧" });
  });

  // --- 13. よくあるエラー ---
  // 長時間の単一ページセッション後は描画プロセスが不安定になり得るため、
  // 最後のエラー実例撮影は新しいページで行う。
  let errPage = page;
  await step("fresh-page-for-errors", async () => {
    errPage = await context.newPage();
  });

  await step("error-duplicate-project", async () => {
    await errPage.goto(BASE_URL + "/", { waitUntil: "networkidle" });
    await errPage.fill('input[placeholder^="プロジェクト名"]', PROJECT_NAME);
    await errPage.click('button[type="submit"]:has-text("作成")');
    await errPage.waitForSelector(".error", { timeout: 5000 });
  });
  await step("28-error-duplicate-project.png", async () => {
    await shoot(errPage, "28-error-duplicate-project.png", { note: "エラー例: 既存プロジェクト名での作成失敗" });
  });

  await step("error-duplicate-job", async () => {
    await errPage.goto(`${BASE_URL}/p/${PROJECT_NAME}/train`, { waitUntil: "networkidle" });
    const sel = errPage.locator("select").first();
    const optCount = await sel.locator("option").count();
    if (optCount > 1) {
      await sel.selectOption({ index: 1 });
    }
    await errPage.click('button[type="submit"]:has-text("開始")');
    await errPage.waitForSelector(".error", { timeout: 8000 });
  });
  await step("29-error-duplicate-job.png", async () => {
    await shoot(errPage, "29-error-duplicate-job.png", { note: "エラー例: 同名学習ジョブの重複（409）" });
  });

  await browser.close();

  const summaryPath = path.join(OUT_DIR, "_capture-summary.json");
  fs.writeFileSync(summaryPath, JSON.stringify(results, null, 2), "utf-8");
  console.log("\n=== SUMMARY ===");
  for (const r of results) {
    console.log(r.ok ? "OK  " : "FAIL", r.file, "-", r.note);
  }
  console.log("\nWritten to:", OUT_DIR);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
