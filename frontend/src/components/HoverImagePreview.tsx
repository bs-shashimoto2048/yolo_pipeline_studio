// サムネイルにホバーすると大きめの浮動プレビューを表示する汎用コンポーネント。
import { useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  thumbSrc: string;
  fullSrc: string;
  alt?: string;
  className?: string;
  large?: boolean; // 評価成果物など大きめに表示
  maxW?: number; // 拡大プレビューの最大幅(px)。指定時は large より優先
  maxH?: number; // 拡大プレビューの最大高さ(px)。指定時は large より優先
  center?: boolean; // カーソル追従せず画面中央に浮かせる
}

export default function HoverImagePreview({ thumbSrc, fullSrc, alt, className, large, maxW, maxH, center }: Props) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const w = maxW ?? (large ? 720 : 480);
  const h = maxH ?? (large ? 520 : 360);

  function onMove(e: React.MouseEvent) {
    if (center) {
      // 中央固定モードでは座標計算は不要（表示ON/OFFのみ管理）
      setPos((p) => p ?? { x: 0, y: 0 });
      return;
    }
    // カーソル右上に表示しつつ画面外にはみ出さないよう調整
    const x = Math.min(e.clientX + 16, window.innerWidth - (w + 16));
    const y = Math.min(Math.max(e.clientY - h / 2, 8), window.innerHeight - (h + 16));
    setPos({ x: Math.max(8, x), y });
  }

  return (
    <span
      className={"hover-img " + (className ?? "")}
      onMouseMove={onMove}
      onMouseLeave={() => setPos(null)}
    >
      <img src={thumbSrc} alt={alt} loading="lazy" />
      {pos &&
        // 拡大プレビューは body 直下に描画する。
        // （祖先の transform / overflow:hidden による position:fixed のクリップを回避）
        createPortal(
          <img
            className={"hover-img-preview" + (large ? " lg" : "") + (center ? " centered" : "")}
            src={fullSrc}
            alt={alt}
            // maxW/maxH 指定時はインラインで上書き（CSSの max-width/height より優先）。
            // center 時は left/top を指定せず CSS で中央寄せする。
            style={{
              ...(center ? {} : { left: pos.x, top: pos.y }),
              ...(maxW ? { maxWidth: maxW } : {}),
              ...(maxH ? { maxHeight: maxH } : {}),
            }}
          />,
          document.body
        )}
    </span>
  );
}
