"""学習ログのユーティリティ（ANSI除去・レベル判定・エラー要約）。

train_worker からも import せずに使えるよう、依存のない純関数のみで構成する。
"""

from __future__ import annotations

import re

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """ANSIエスケープ（カラーコード等）を除去する。"""
    return ANSI_RE.sub("", text)


def classify_line(text: str) -> str:
    """ログ1行のレベルを簡易判定する。"""
    low = text.lower()
    if (
        "[error]" in low
        or "traceback" in low
        or "error:" in low
        or "runtimeerror" in low
        or "filenotfounderror" in low
        or "exception" in low
        or "missing path" in low
        or "images not found" in low
        or "out of memory" in low
    ):
        return "error"
    if "[warn]" in low or "warning" in low:
        return "warning"
    if "[info]" in low:
        return "info"
    return "normal"


# (検出パターン（小文字）, 表示要約)
_ERROR_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (
        ("images not found", "missing path"),
        "data.yaml の画像パスが見つかりません。データセットを再作成してください。",
    ),
    (
        ("cuda out of memory",),
        "GPUメモリ不足です。batch を下げるか imgsz を小さくしてください。",
    ),
    (
        ("no module named 'ultralytics'",),
        "ultralytics が未導入です。requirements-train.txt または Windows GPU 導入手順を確認してください。",
    ),
    (
        ("no module named 'torch'",),
        "torch が未導入です。requirements-train.txt または Windows GPU 導入手順を確認してください。",
    ),
    (
        ("cuda is not available",),
        "CUDAが利用できません。CUDA対応PyTorchが入っているか確認してください。",
    ),
    (
        ("torch not compiled with cuda",),
        "CUDAが利用できません。CUDA対応PyTorchが入っているか確認してください。",
    ),
]


def error_summary(text: str) -> str | None:
    """ログ全文から既知エラーパターンを拾って分かりやすい要約を返す。"""
    low = text.lower()
    for needles, summary in _ERROR_PATTERNS:
        if all(n in low for n in needles):
            return summary
    return None


def build_lines(text: str) -> list[dict]:
    """ログ全文を行ごとに {level, text} のリストへ整形する（ANSI除去済み前提）。"""
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line == "":
            continue
        out.append({"level": classify_line(line), "text": line})
    return out
