import argparse

from screener import run


def main() -> None:
    parser = argparse.ArgumentParser(description="日本株4要素スクリーナー")
    parser.add_argument("--as-of", help="基準日 YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--demo", action="store_true", help="APIなしの合成データで動作確認")
    args = parser.parse_args()
    try:
        output = run(args.as_of, args.demo)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        parser.exit(2, f"エラー: {exc}\n")
    print(f"完了: {output}")


if __name__ == "__main__":
    main()
