# Contributing

改善提案、バグ報告、ドキュメント修正を歓迎します。

## 開発手順

1. リポジトリをForkして作業ブランチを作成します。
2. `python -m venv .venv` で仮想環境を作成します。
3. `pip install -r requirements-dev.txt` を実行します。
4. 変更後に `pytest` と `python run_screen.py --demo --as-of 2026-09-11` を実行します。
5. 目的、変更内容、検証結果をPull Requestに記載します。

採点ルールを変更する場合は、根拠と期待する影響を説明し、対応するテストも更新してください。実在銘柄の将来利益を保証する表現、APIキー、個人の売買履歴はコミットしないでください。
