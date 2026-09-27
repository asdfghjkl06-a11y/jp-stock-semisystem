import argparse
from x_engine import build_queue, collect_metrics, export_queue, performance_report, publish_approved, set_status


def parse_ids(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(',') if x.strip()]


def main():
    p = argparse.ArgumentParser(description='X半自動運用エンジン')
    sub = p.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('build'); q.add_argument('--as-of'); q.add_argument('--count', type=int, default=8)
    a = sub.add_parser('approve'); a.add_argument('ids')
    r = sub.add_parser('reject'); r.add_argument('ids')
    pub = sub.add_parser('publish'); pub.add_argument('--live', action='store_true'); pub.add_argument('--limit', type=int, default=8)
    sub.add_parser('metrics'); sub.add_parser('report'); sub.add_parser('export')
    args = p.parse_args()
    if args.cmd == 'build': print(f'{build_queue(args.as_of,args.count)}件を投稿キューへ追加しました: {export_queue()}')
    elif args.cmd == 'approve': set_status(parse_ids(args.ids),'approved'); print('承認しました')
    elif args.cmd == 'reject': set_status(parse_ids(args.ids),'rejected'); print('却下しました')
    elif args.cmd == 'publish': print('\n\n'.join(publish_approved(dry_run=not args.live,limit=args.limit)) or '承認済み投稿はありません')
    elif args.cmd == 'metrics': print(f'{collect_metrics()}件の指標を保存しました')
    elif args.cmd == 'report': print(performance_report())
    elif args.cmd == 'export': print(export_queue())

if __name__ == '__main__': main()
