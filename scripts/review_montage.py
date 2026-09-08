"""目視アノテーション補助: raw画像を指定クロップでグリッド montage 化する（read-only）。

projects/<project名>/raw/images と annotations/labels を読み取るだけで、
どちらも一切変更しない。出力は --out で指定した1枚のmontage画像のみ。

使い方:
    .venv\\Scripts\\python.exe scripts\\review_montage.py --project meter --prefix src_003_ \
        --crop 0.50 0.76 0.44 0.68 --cols 5 --start 0 --count 20 \
        --out /path/to/output/src_003_batch01.jpg --show-boxes

--project を省略した場合は既定で "meter" を対象にする（後方互換）。
--show-boxes を付けると、現在の annotations/labels の矩形・クラスをクロップ画像上に重ねて表示する
（目視で読んだ数字と現在のラベルを比較しやすくするため）。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np

PROJECTS_ROOT = Path(__file__).resolve().parents[1] / "projects"

CELL_H = 220  # クロップ後の各セル高さ(px)


def natural_key(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def load_boxes(labels_dir: Path, stem: str):
    p = labels_dir / f"{stem}.txt"
    if not p.exists():
        return []
    boxes = []
    for ln in p.read_text(encoding="utf-8").strip().splitlines():
        if not ln.strip():
            continue
        c, xc, yc, w, h = ln.split()
        boxes.append((int(c), float(xc), float(yc), float(w), float(h)))
    return boxes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="meter", help="projects/配下の対象プロジェクト名（既定: meter）")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--names", nargs="*", default=None, help="明示的なファイル名リスト（拡張子含む）")
    ap.add_argument("--crop", nargs=4, type=float, required=True, metavar=("X0", "X1", "Y0", "Y1"))
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", required=True)
    ap.add_argument("--show-boxes", action="store_true")
    args = ap.parse_args()

    project_dir = PROJECTS_ROOT / args.project
    raw_dir = project_dir / "raw" / "images"
    labels_dir = project_dir / "annotations" / "labels"
    if not raw_dir.exists():
        print(f"project not found (raw/images does not exist): {project_dir}")
        return

    if args.names:
        names = args.names
    else:
        names = sorted(
            (p.name for p in raw_dir.iterdir() if p.is_file() and p.name.startswith(args.prefix)),
            key=natural_key,
        )
    batch = names[args.start : args.start + args.count]
    if not batch:
        print("no images in range")
        return

    x0, x1, y0, y1 = args.crop
    cells = []
    labels_txt = []
    for name in batch:
        stem = Path(name).stem
        img = cv2.imread(str(raw_dir / name))
        if img is None:
            continue
        h, w = img.shape[:2]
        cx0, cx1, cy0, cy1 = int(x0 * w), int(x1 * w), int(y0 * h), int(y1 * h)
        crop = img[cy0:cy1, cx0:cx1].copy()
        if args.show_boxes:
            for c, xc, yc, bw, bh in load_boxes(labels_dir, stem):
                bx1 = int(xc * w - bw * w / 2) - cx0
                by1 = int(yc * h - bh * h / 2) - cy0
                bx2 = int(xc * w + bw * w / 2) - cx0
                by2 = int(yc * h + bh * h / 2) - cy0
                cv2.rectangle(crop, (bx1, by1), (bx2, by2), (0, 255, 0), 2)
                cv2.putText(crop, str(c), (bx1, max(0, by1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        ch, cw = crop.shape[:2]
        scale = CELL_H / ch
        crop = cv2.resize(crop, (int(cw * scale), CELL_H))
        # キャプション帯（ファイル名の時刻部分だけ抜粋）
        cap = stem
        bar = np.zeros((28, crop.shape[1], 3), dtype=np.uint8)
        cv2.putText(bar, cap, (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cell = np.vstack([bar, crop])
        cells.append(cell)
        labels_txt.append(cap)

    max_w = max(c.shape[1] for c in cells)
    max_h = max(c.shape[0] for c in cells)
    padded = []
    for c in cells:
        pad = np.zeros((max_h, max_w, 3), dtype=np.uint8)
        pad[: c.shape[0], : c.shape[1]] = c
        padded.append(pad)

    cols = args.cols
    rows = (len(padded) + cols - 1) // cols
    grid = np.zeros((rows * max_h, cols * max_w, 3), dtype=np.uint8)
    for i, cell in enumerate(padded):
        r, c = divmod(i, cols)
        grid[r * max_h : (r + 1) * max_h, c * max_w : (c + 1) * max_w] = cell

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), grid)
    print("saved", out_path, "cells:", len(padded))
    for i, t in enumerate(labels_txt):
        print(i, t)


if __name__ == "__main__":
    main()
