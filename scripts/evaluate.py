"""Run the ethical evaluation framework on a consented, labelled dataset.

Usage:
    python scripts/evaluate.py --manifest manifest.json --config run.json \
        --ground-truth truth.json --predictions predictions.json --out report.json [--split test]

Refuses to run unless the manifest states that consent was verified. Prints a
JSON report; exits non-zero on invalid input. See docs/EVALUATION.md.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.evaluation.runner import DatasetManifest, EvaluationError, RunConfig, evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--out")
    parser.add_argument("--split", default="test")
    args = parser.parse_args()

    def load(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    try:
        report = evaluate(DatasetManifest(**load(args.manifest)), RunConfig(**load(args.config)), load(args.ground_truth), load(args.predictions), args.split)
    except (EvaluationError, ValueError, KeyError) as error:
        print(f"Evaluation refused: {error}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
