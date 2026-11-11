"""Fetch optional public transistor models; no installation into a system PDK."""

import argparse
from pathlib import Path

from validation.pad_sources import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("local/pad-spice"))
    args = parser.parse_args()
    receipt = prepare(args.root, download=True)
    print(
        f"Verified {len(receipt['files'])} model/archive files; lock {receipt['lock_sha256']}"
    )


if __name__ == "__main__":
    main()
