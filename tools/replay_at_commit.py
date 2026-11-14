"""Run a historical command (usually a frozen stage's --verify) at its own Git commit.

Frozen plans hash their source files. Replaying in a detached worktree at the
commit that produced the evidence keeps those hashes valid while HEAD code is
free to change. Only the imported source inputs under results/physical-calibration
are shared with the worktree; they are checked by the replayed command itself.

Example (any frozen stage with a --verify mode):
  python tools/replay_at_commit.py --anchor docs/evidence/atplace-case1-step-size-v1.json -- \
      python tools/<frozen_stage_runner> --verify \
      --result docs/evidence/atplace-case1-step-size-v1.json --output results/replay/step-size.json
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SHARED = Path('results/physical-calibration')


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def anchor_commit(path):
    """Last commit that changed the evidence file, i.e. the code that produced it."""
    sha = git('log', '-1', '--format=%H', '--', path)
    if not sha:
        raise SystemExit(f'no commit touches {path}')
    return sha


def replay(commit, command):
    commit = git('rev-parse', '--verify', commit + '^{commit}')
    tree = ROOT/'results'/'replay-worktrees'/commit[:12]
    if not tree.exists():
        tree.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(['git', '-C', str(ROOT), 'worktree', 'add', '--detach', str(tree), commit])
    shared = tree/SHARED
    if not shared.exists():
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.symlink_to(ROOT/SHARED, target_is_directory=True)
    (tree/'results'/'replay').mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(tree/'src'), os.environ.get('PYTHONPATH')])))
    code = subprocess.call(command, cwd=tree, env=env)
    print(json.dumps(dict(commit=commit, worktree=str(tree), command=command, exit_code=code)))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument('--commit')
    where.add_argument('--anchor', help='evidence file; replay at the last commit that changed it')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('give the command to replay after --')
    sys.exit(replay(args.commit or anchor_commit(args.anchor), command))


if __name__ == '__main__':
    main()
