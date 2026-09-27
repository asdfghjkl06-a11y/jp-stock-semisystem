# 日本株4要素スクリーナー（半自動運用版）

需給・テクニカル・材料・財務を固定ルールで採点し、次の3ランキングを同時に作ります。

- 通常型：4要素のバランス重視
- 噴き上げ型：テクニカルとRVOL重視
- 初動需給型：RVOLと需給の軽さ重視

出力は `output/screening_YYYY-MM-DD.xlsx`、監査用CSV、ChatGPTに渡せるMarkdownレポートです。これは投資判断を補助するスクリーニングであり、売買推奨や利益保証ではありません。

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

J-Quants V2は `x-api-key` 方式です。株価は調整後OHLCVを優先して使います。週次信用残はAPIから取得しますが、2026年9月28日に日次化・項目追加が予定されています。本実装はJSONの列順ではなく項目名で読むため、その変更に備えています。取得元の定義変更があった場合は、READMEだけでなく実データの列名も点検してください。


## X半自動運用（追加機能）

スクリーニング結果からX投稿候補を最大8本作り、**人間が承認したものだけ**投稿します。初期状態は必ずDRY RUNです。完全自動の大量投稿・大量返信ではなく、事実確認と承認を残す設計です。

### 1. 投稿候補を作る

先に通常のスクリーニングを実行し、その日の `candidates_YYYY-MM-DD.csv` を作ります。

```bash
python run_screen.py --demo --as-of 2026-09-11
python run_x_engine.py build --as-of 2026-09-11 --count 8
```

候補は `output/x_post_queue.csv` と `output/x_growth.db` に保存されます。各投稿は FACT / 見方 / 次に確認する仮説を分離しています。

### 2. 内容を確認して承認する

```bash
python run_x_engine.py approve 1,2,3
python run_x_engine.py reject 4
```

### 3. DRY RUNで確認する

```bash
python run_x_engine.py publish
```

このコマンドはXへ投稿しません。承認済み本文を表示するだけです。

### 4. X APIを設定して実投稿する

`.env` にX Developer Portalで取得した認証情報を設定します。秘密情報はチャットに貼らないでください。X側で投稿権限が付与されたUser Contextのトークンが必要です。

```bash
python run_x_engine.py publish --live --limit 1
```

最初は必ず `--limit 1` で1投稿だけ確認してください。正常動作を確認してから増やします。

### 5. 投稿成績を保存する

APIプラン・認証権限で利用可能な指標は異なります。

```bash
python run_x_engine.py metrics
python run_x_engine.py report
```

`output/x_performance.csv` に時系列で保存されます。これを翌日の投稿改善に使えます。

### 安全設計

- デフォルトはDRY RUN。`--live` を明示しない限り投稿しない。
- AI生成後に人間承認を必須にする。
- 同一本文はSHA-256で重複登録を防止する。
- 投資投稿は売買推奨ではなく監視メモとして生成する。
- 自動リプ機能は初版では意図的に実装していない。大量自動返信によるスパム判定を避けるため、まず投稿運用と計測を安定させる。

## 📱 iPhoneで見る GitHub Actions の暫定DRY RUN

Macを起動し続ける必要はありません。`Stock candidates DRY RUN` は平日07:30 JSTにGitHub上で実行されます。現在の定期実行はYahoo Financeの非公式データを `yfinance` で取得し、`input/universe.csv` の20銘柄だけを価格・出来高・5MAで一次抽出します。J-QuantsやXのAPIキーは不要です。データ取得元の制限や変更で失敗する可能性があります。

1. GitHubの **Actions → Stock candidates DRY RUN** を開きます。
2. 実データを今すぐ試す場合は **Run workflow** で `demo` をOFFにします。`demo` ONは架空データの動作確認です。
3. 完了した実行の **Artifacts → stock-candidates-番号** をダウンロードして、`mobile_preview.md` を開きます。`output` フォルダ内のファイルがリポジトリに自動コミットされるわけではありません。

投稿候補は最大8本です。条件を満たす銘柄が少なければ本数も減ります。暫定候補には「需給未確認」と表示します。信用倍率・貸借倍率・回転日数と材料・財務の裏付けは自動取得していません。各候補の取引日、価格、出来高、開示を確認してからご自身で判断してください。Xへの自動投稿はしません。`--live` を指定する別の手動コマンドをこのワークフローは呼びません。

データ提供元の利用条件を確認してください。`yfinance` はYahooの非公式APIを使い、個人的な研究用途を想定しています。公開投稿への転載許諾があるという意味ではありません。リポジトリは非公開を推奨します。既存のJ-Quants方式で需給を含める場合は、利用プランと入力CSVを別途整えてください。
