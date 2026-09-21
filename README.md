# 日本株4要素スクリーナー（半自動運用版）

日本株を「需給・テクニカル・材料・財務」の説明可能な固定ルールで比較する、オープンソースのPythonツールです。ブラックボックスな売買シグナルではなく、入力値・配点・除外理由をExcelとCSVに残すことを重視しています。

需給・テクニカル・材料・財務を固定ルールで採点し、次の3ランキングを同時に作ります。

- 通常型：4要素のバランス重視
- 噴き上げ型：テクニカルとRVOL重視
- 初動需給型：RVOLと需給の軽さ重視

出力は `output/screening_YYYY-MM-DD.xlsx`、監査用CSV、ChatGPTに渡せるMarkdownレポートです。これは投資判断を補助するスクリーニングであり、売買推奨や利益保証ではありません。

## 特徴

- APIなしのデモモードで、インストール直後に動作確認
- J-Quants API V2または手動OHLCV CSVに対応
- 閾値・重みを `config.yaml` で管理
- 入力データの充足率、一次フィルターの除外銘柄、全スコアを保存
- 注文発注機能なし。分析と実取引を明確に分離

## 初回セットアップ

Python 3.11以上を推奨します。

### Windows（PowerShell）

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

J-Quants V2を使う場合は `.env` の `JQUANTS_API_KEY` を自分のキーに置き換えます。APIキーはチャットやCSVに貼らないでください。

まずAPIなしで動作確認します。

```bash
python run_screen.py --demo --as-of 2026-09-11
```

成功すると `output/screening_2026-09-11.xlsx` が作成されます。開発に参加する場合は `pip install -r requirements-dev.txt` のあと `pytest` を実行してください。

## 毎日の運用（約3分＋API取得時間）

1. `input/universe.csv` に監視対象を登録する。
2. 証券会社等の画面・CSVから、当日の `信用倍率 / 貸借倍率 / 回転日数` を `input/supply_demand.csv` に貼る。
3. 決算・適時開示を確認した銘柄だけ `input/catalysts.csv` の材料点（0〜100）と根拠を更新する。
4. 次を実行する。

```bash
python run_screen.py --as-of 2026-09-11
```

5. `output/screening_YYYY-MM-DD.xlsx` をChatGPTに添付し、「今日のスクリーニング」と送る。

`--as-of` を省略するとPC上の今日の日付を使います。引け後の利用を想定しています。

## 入力ファイル

| ファイル | 用途 | 更新目安 |
|---|---|---|
| `universe.csv` | 対象コードと銘柄名 | 必要時 |
| `supply_demand.csv` | 信用倍率・貸借倍率・回転日数 | 毎日または取得元の更新時 |
| `fundamentals.csv` | 自己資本比率・利回り・成長率の上書き | 決算時 |
| `catalysts.csv` | 材料点・見出し・出所 | 適時開示時 |
| `prices_manual.csv` | APIを使わない場合のOHLCV | 毎日追記 |

同じコードが複数行ある場合、日付が最新の行を採用します。コードは4桁でも5桁でも入力できます。

### 材料スコアの目安

| 点 | 目安 |
|---:|---|
| 80〜100 | 上方修正、大幅増益、強い受注・還元など明確な好材料 |
| 60〜79 | 予想超過、増配、小〜中規模の好材料 |
| 40〜59 | 中立、織り込み済み、材料なし |
| 20〜39 | 未達、慎重見通し、希薄化懸念 |
| 0〜19 | 下方修正、重大な不祥事・財務懸念 |

根拠がないときは空欄にします。空欄は採点上50点の中立値ですが、データ充足率が下がります。

## 一次フィルター

既定値は次のすべてです。

- 信用倍率 ≤ 7.0
- 貸借倍率 ≤ 7.0
- 回転日数 ≤ 7.0
- 出来高 ≥ 100万株、または売買代金 ≥ 10億円

`config.yaml` の `strict_supply_data: true` により、需給3項目のどれかが欠ける銘柄は通過しません。まずはこの設定を維持してください。

J-Quantsの `LongVol / ShrtVol` から計算した比率は信用倍率の補完に使います。ただし、貸借倍率と回転日数は別概念なので自動代用しません。

## チャート判定

- `今買える`：終値が5MAより上、かつ5MA傾きがプラス
- `押し待ち`：5MA乖離が+5%以上、または上記に完全一致しない中間状態
- `見送り/押し待ち`：5MA乖離がマイナス

スコアでは5/25/75MAの並び、5MA・25MA傾き、5日・20日騰落、20日高値接近、5MA乖離、RVOLも使います。閾値と配点は `config.yaml` と `screener.py` に明示され、毎回同じです。

## 手動CSVモード

J-Quantsを使わない場合は `config.yaml` の `data.source` を `manual_csv` に変更し、`prices_manual.csv` に最低80営業日分を入れます。列はテンプレートどおりにし、日付は `YYYY-MM-DD` にします。

## よくある停止理由

- ランキングが0件：`supply_demand.csv` の空欄、または一次フィルター閾値を確認。
- API 401/403：APIキー、契約プラン、対象エンドポイントを確認。
- API 429：`request_interval_seconds` を大きくするか、対象銘柄数を減らす。
- 80営業日未満：移動平均の計算に不足。取得期間またはCSV履歴を増やす。
- 休日に当日データがない：`--as-of` に直近取引日を指定。

## ChatGPT用の最終指示

Excelを添付し、次だけ送れば運用できます。

> 今日のスクリーニング。3パターンのTOP10を表で提示し、重複上位と通常型上位について、需給・テクニカル・材料・財務の4点から強み、リスク、5MA乖離状態をコメント。材料は最新の一次情報を確認し、事実と推測を分ける。データ欠損は明記する。

## データ上の注意

J-Quants V2は `x-api-key` 方式です。株価は調整後OHLCVを優先して使います。信用残の定義や提供頻度、契約プランごとの取得可能期間は変更される場合があるため、エラー時はJ-Quants公式リファレンスを確認してください。本実装はJSONの列順ではなく項目名で読みますが、APIの項目名変更には追随が必要です。

## プロジェクトへの参加

IssueやPull Requestを歓迎します。詳細は `CONTRIBUTING.md`、脆弱性の連絡方法は `SECURITY.md` を参照してください。本プロジェクトはMIT Licenseで公開できます。
