"""Use immutable XML names so Nav2 cannot reuse a stale cached tree."""

import hashlib
from pathlib import Path


def snapshot_navigation_trees(source_directory, cache_directory):
    source_directory, cache_directory = Path(source_directory), Path(cache_directory)
    cache_directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for operation, filename in (("goal", "offline_to_pose.xml"),
                                ("route", "offline_through_poses.xml")):
        contents = (source_directory / filename).read_bytes()
        digest = hashlib.sha256(contents).hexdigest()[:16]
        target = cache_directory / f"{operation}-{digest}.xml"
        if not target.exists():
            target.write_bytes(contents)
        result[operation] = str(target)
    return result
