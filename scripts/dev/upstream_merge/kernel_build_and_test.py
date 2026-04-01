#!/usr/bin/env python3
"""User Story 1: Clone NI Linux, fetch stable-RT tags, merge latest RT, notify."""

import os
import sys
import re
import argparse

# --------------------
# Import shared utils
# --------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
dev_dir = os.path.dirname(script_dir)
upstream_merge_dir = os.path.join(dev_dir, "upstream_merge")
sys.path.append(upstream_merge_dir)

from log_and_email_utils import setup_logging, write_log_and_send_email
from utils.git_commands import (
    git_fetch, git_remote, git_merge,
    git_reset, git_clean, git_merge_abort,
    git_tag, git_status,
    git_clone, git_checkout
)
from utils.git_repo import GitRepo
from json_config import JsonConfig

config = None

# --------------------
# CLI
# --------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Stable-RT merge automation")
    parser.add_argument(
        "-c", "--config",
        default="scripts/dev/upstream_merge/kernel_conf.json"
    )
    parser.add_argument("--skip-merge", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--work-dir", default=None)
    return parser.parse_args()


# --------------------
# Kernel repo handling
# --------------------
def clone_kernel_repository():
    print("[INFO] Cloning kernel repository")

    repo = os.path.abspath(config.kernel_src_dir)
    config.kernel_src_dir = repo

    os.makedirs(os.path.dirname(repo), exist_ok=True)
    git_clone(config.repo_url, repo)


# --------------------
# RT Merge (US-1)
# --------------------
def run_upstream_merge_script(args):
    original_cwd = os.getcwd()
    print("[INFO] Running upstream RT merge")

    clone_kernel_repository()

    kernel_repo = GitRepo(
        local_repo=config.kernel_src_dir,
        upstream_repo_url=config.repo_url,
        upstream_branch=config.target_branch
    )

    os.chdir(config.kernel_src_dir)

    # Clean state (always safe for fresh clone)
    try:
        git_merge_abort()
    except Exception:
        pass

    git_reset(hard=True)
    git_clean(force=True, directories=True, ignored_files=True)

    # Fetch origin & checkout target branch
    git_fetch("origin")
    git_checkout(config.target_branch, create=True, force_checkout=True)
    git_reset(hard=True, target=f"origin/{config.target_branch}")

    # Fetch stable-RT tags
    _, remotes = git_remote()
    if "stable-rt" not in remotes:
        git_remote("stable-rt", config.stable_rt_remote)

    git_fetch("stable-rt", "--tags")

    # Find latest RT tag
    kernel_version = config.target_branch.split("/")[-1]
    _, tags = git_tag(list_pattern=f"v{kernel_version}.*-rt*")

    clean_tags = [
        t for t in tags.splitlines()
        if re.match(rf"^v{kernel_version}\.\d+-rt\d+$", t)
    ]

    if not clean_tags:
        raise RuntimeError("No stable-RT tags found")

    latest_tag = sorted(
        clean_tags,
        key=lambda t: list(map(int, re.findall(r"\d+", t)))
    )[-1]

    print(f"[INFO] Latest RT tag: {latest_tag}")

    # Perform merge
    result = git_merge(
        latest_tag,
        signoff=True,
        message=f"Merge latest upstream {latest_tag}"
    )

    # --------------------
    # Failure case
    # --------------------
    if result[0] != 0:
        _, status_out = git_status()

        merge_details = (
            status_out if ("both modified" in status_out or "unmerged" in status_out)
            else "Merge failed before conflicts were created."
        )

        merge_report = {
            kernel_repo: (
         1,
         merge_details
             ),
    "Build and Test": (
        1,
        "Skipped because merge failed"
    )
}
        os.chdir(original_cwd)
        write_log_and_send_email(
            email_from=config.email_from,
            email_to=config.email_to,
            merge_report=merge_report,
            email_log_level=0,
            skip_push_and_pr=True
        )

    # --------------------
    # Success case
    # --------------------
    print("[INFO] RT merge successful")

    merge_report = {
    kernel_repo: (
        0,
        f"RT tag {latest_tag} merged successfully.\n"
        f"Branch: {config.target_branch}"
    ),
    "Build and Test": (
        0,
        "Not executed (US-1: RT merge only)"
    )
}
    os.chdir(original_cwd)
    write_log_and_send_email(
        email_from=config.email_from,
        email_to=config.email_to,
        merge_report=merge_report,
        email_log_level=0,
        skip_push_and_pr=True
    )


# --------------------
# Main
# --------------------
def main():
    global config

    setup_logging()
    args = parse_args()

    config = JsonConfig(config_path=args.config, work_item_id=None)

    if args.work_dir:
        config.kernel_src_dir = os.path.join(
            args.work_dir, "nilrt-kernel-build", "linux"
        )

    print(
        f"[INFO] Branch: {config.target_branch}, "
        f"Arch: {config.arch}"
    )

    if not args.skip_merge:
        run_upstream_merge_script(args)


if __name__ == "__main__":
    main()