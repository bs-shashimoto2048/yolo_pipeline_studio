// 未実装工程の共通プレースホルダ画面
interface Props {
  title: string;
  description?: string;
}

export default function StubPage({ title, description }: Props) {
  return (
    <div className="stub-page">
      <h1>{title}</h1>
      <div className="stub-banner">骨組み段階（未実装）</div>
      {description && <p className="muted">{description}</p>}
      <p className="muted">
        この工程は今後のIssueで実装します。バックエンドのAPIはスタブとして
        登録済みで、現在は 501 を返します。
      </p>
    </div>
  );
}
