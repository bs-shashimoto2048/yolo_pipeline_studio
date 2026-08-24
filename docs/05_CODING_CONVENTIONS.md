# コーディング規約

実ソースから読み取れる規約のみを記載する。明文化されたスタイルガイド（`.editorconfig`, ESLint/Ruff設定等）は存在しない。

## 命名規則

| 対象 | 規則 | 例 |
|---|---|---|
| Python 関数・変数 | snake_case | `list_projects`, `is_valid_project_name`（`backend/app/`） |
| Python クラス | PascalCase | `ProjectSummary`, `ProjectConflictError`（`backend/app/schemas/`, `services/`） |
| Python 例外クラス | `<機能名>Error` を基底に `<機能名>ValidationError`(400) / `<機能名>NotFoundError`(404) / `<機能名>ConflictError`(409) を派生 | `ProjectError` → `ProjectConflictError`（`backend/app/services/project_service.py`） |
| TypeScript 関数・変数 | camelCase | `listProjects` 等（`frontend/src/api/client.ts`） |
| React コンポーネント / TSインターフェース | PascalCase | `ProjectLayout`, `ProjectSummary`（`frontend/src/components/`, `types.ts`） |
| React コンポーネントファイル | PascalCase + `.tsx` | `AnnotatePage.tsx`, `ImagesPanel.tsx` |
| ルーター/サービスファイル | snake_case + `.py` | `label_validation.py`, `onnx_export_service.py` |

## ファイル配置

- バックエンドは `routers/` → `services/` → `schemas/` の3層構造で、機能ごとに同名（または対応する）ファイルを1つずつ置く（例: `routers/projects.py` ⇔ `services/project_service.py` ⇔ `schemas/project.py`, `schemas/cls.py`）。
- ワーカーは `backend/workers/` に置き、`backend/app/` パッケージから import せず独立実行可能にする（`docs/architecture.md`）。
- スモークテストは `backend/tests/smoke_<機能名>.py` の命名で1テストファイルにまとめる。
- フロントエンドの画面は `frontend/src/pages/<Name>Page.tsx`、再利用コンポーネントは `frontend/src/components/<Name>.tsx` に置く。

## コメント・docstring

- Python: モジュール先頭に日本語1行docstring（例: `"""プロジェクト管理 + クラス設計 API。"""`, `backend/app/routers/projects.py`）。関数・クラスにも日本語docstringが付与されている（例: `backend/app/services/project_service.py`）。
- 全 Python ファイルの先頭に `from __future__ import annotations` が置かれている（確認したファイル全てで一致）。
- TypeScript/TSXのコメントも日本語（`frontend/src/` 各ファイルで確認）。

## エラーハンドリング

`docs/architecture.md` および実際のルーター/サービスの実装で確認された方針。

- services 層は業務エラーを Python 例外として投げる。基底クラス `<機能名>Error(Exception)` と、意味ごとの派生クラス（`ValidationError`=400 / `NotFoundError`=404 / `ConflictError`=409）を機能ごとに定義する。
- routers 層は `try/except` で該当する例外クラスを捕捉し、`fastapi.HTTPException` に変換する（`raise HTTPException(status_code=..., detail=str(e)) from e`）。
- 変換順序は具体的なサブクラス（例: `ProjectConflictError`）を先に、基底クラス（`ProjectError`）を後に catch する（`backend/app/routers/projects.py` の `delete_project` 参照）。

```python
# backend/app/routers/projects.py の実例
@router.delete("/{name}", response_model=MessageResponse)
def delete_project(name: str) -> MessageResponse:
    try:
        project_service.delete_project(name)
    except ProjectConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return MessageResponse(message=f"プロジェクト '{name}' を削除しました。")
```

## 非同期処理

- バックエンドのルーター関数は大半が同期 `def`（`async def` ではない）。`async def` は `backend/app/routers/images.py`（`upload_images`, `import_folder`）と `backend/app/main.py`（lifespanフック）でのみ使用されている（grep実測: `async def`/`await` は `backend/app/` 全体で5件のみ）。重い処理（学習・推論・映像・撮影・ONNXエクスポート）は非同期化ではなく `subprocess.Popen` による別プロセス化＋ポーリングで対応している（[`01_ARCHITECTURE.md`](01_ARCHITECTURE.md)）。
- フロントエンドは `async`/`await` を広く使用（`frontend/src/` 全体で232件、17ファイル）。`frontend/src/api/client.ts` の全メソッドが `fetch()` を `await` する非同期関数。

## 型定義

- フロントエンド: `frontend/src/types.ts`（1021行）に `export interface` が106個定義されている。バックエンドのPydanticモデルに対応する型をTypeScript側で個別に定義する運用（自動生成ではなく手書き、`.tsx`ファイル内でのimportから確認）。
- バックエンド: Pydantic v2 の `BaseModel` を `schemas/*.py` に定義し、リクエスト/レスポンスの型として `response_model=` 等で利用する。

## クラスID・データ整合性に関する規約

- `classes.yaml` の `id` は0始まり・追加順の連番であり、学習済みモデルやデータセット作成後の並び替えは既存ラベル/モデルとの整合性を崩すため禁止（`README.md`, `docs/architecture.md`）。

## 依存追加の方針

- 軽量な `requirements.txt` と重い `requirements-train.txt` / `backend/requirements-sam.txt` を明確に分離し、アノテーション等の軽量作業がGPU/学習系ライブラリのインストールを要求しないようにする（[`03_TECH_STACK.md`](03_TECH_STACK.md)）。

## 確認できなかった項目

- ESLint / Prettier / Ruff / Black / mypy 等の自動フォーマット・静的解析ルールは設定ファイル・依存として存在せず、規約は上記のような**既存コードからの読み取りベース**に留まる。
