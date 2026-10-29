"""Validate a proposed training launch; deliberately cannot execute training."""

import argparse
from pathlib import Path

from _common import emit, guarded, load_json
from training import validate_training_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true", required=True)
    args = parser.parse_args()
    emit(validate_training_plan(load_json(args.plan), load_json(args.authorization)))
    return 0


if __name__ == "__main__":
    guarded(main)
