import argparse
import json
import sys
from pathlib import Path
from pydantic import ValidationError
if __package__:
    from .engine import Plan
    from .models import Exam, Preset, Conflict
else:
    from engine import Plan
    from models import Exam, Preset, Conflict


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('exam')
    parser.add_argument('--preset', action='append', default=[])
    parser.add_argument('--previous', help='Previously approved preview JSON')
    parser.add_argument('--swap', nargs=2, metavar=('SOURCE', 'TARGET'))
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    try:
        exam = Exam.model_validate(load(args.exam))
        for path in args.preset:
            exam.rules.extend(Preset.model_validate(load(path)).rules)
        old = load(args.previous) if args.previous else None
        if args.seconds <= 0 or (args.swap and old is None):
            parser.error('Supply positive --seconds and use --previous with --swap.')
        plan = Plan(exam, old)
        preview = plan.edit(old, *args.swap) if args.swap else plan.allocate(args.seconds)
        print(json.dumps(preview, indent=2))
    except (ValidationError, ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error':str(exc), 'suggestion':getattr(exc, 'hint', 'Review the input JSON.')}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
