// ホバーで説明を表示する小さな「?」ツールチップ。
interface Props {
  text: string;
  placement?: "up" | "down"; // テーブルヘッダー等、上が隠れる場所では down
}

export default function InfoTooltip({ text, placement = "up" }: Props) {
  return (
    <span className="info-tip" tabIndex={0}>
      ?
      <span className={"info-tip-body" + (placement === "down" ? " down" : "")}>
        {text}
      </span>
    </span>
  );
}
