import argparse

from screener import run


def main() -> None:
    parser = argparse.ArgumentParser(description="日本株4要素スクリーナー")
    parser.add_argument("--as-of", help="基準日 YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--demo", action="store_true", help="APIなしの合成データで動作確認")
    parser.add_argument("--free", action="store_true", help="Yahoo Finance由来の価格で一次抽出（需給未確認）")
    args = parser.parse_args()
    output = run(args.as_of, args.demo, args.free)
    print(f"完了: {output}")


if __name__ == "__main__":
    main()
