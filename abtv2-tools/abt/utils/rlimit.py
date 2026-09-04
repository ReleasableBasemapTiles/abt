"""
rlimit.py

Raises this process's open-file limit (RLIMIT_NOFILE) so every tool it
spawns inherits the higher ceiling.
"""

import resource
from typing import Tuple

# Tried from the top down, but only when the hard limit is reported as
# unlimited: macOS advertises an infinite hard RLIMIT_NOFILE while still
# refusing any soft value above kern.maxfilesperproc, so there's no single
# value to ask for.
UNLIMITED_FALLBACK_TARGETS = (1048576, 262144, 65536, 10240)


def raise_open_file_limit() -> Tuple[int, int]:
    """Raises this process's RLIMIT_NOFILE soft limit to its hard limit.

    Subprocesses inherit the limit, which is the whole point: tippecanoe
    sizes itself to the host's core count, needing roughly ten descriptors
    per reader plus a pool of temporary files, so on a many-core host the
    usual soft limit of 1024 leaves it dying part-way through setup with
    "Too many open files" and exit code 111 (EXIT_OPEN) -- for every layer,
    since every layer runs the same setup on the same host.

    Raising it here means a run no longer depends on the invoking shell
    having picked up the limits setup_ubuntu.sh writes to
    /etc/security/limits.d, which PAM applies only to login sessions
    created after that point.

    Returns (previous_soft, current_soft); the two are equal when nothing
    could be, or needed to be, raised.
    """
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == hard:
        return soft, soft

    targets = UNLIMITED_FALLBACK_TARGETS if hard == resource.RLIM_INFINITY else (hard,)
    for target in targets:
        # The ladder descends, so once it drops to what we already have
        # there's nothing left worth trying -- and setting it would lower
        # the limit rather than raise it.
        if target <= soft:
            break
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        except (OSError, ValueError):
            continue
        return soft, target
    return soft, soft
