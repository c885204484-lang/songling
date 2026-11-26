"""Use immutable XML names so Nav2 cannot reuse a stale cached tree."""

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET


def navigation_tree_files(directory, use_lidar):
    prefix = "offline" if use_lidar else "offline_fixed"
    directory = Path(directory)
    return {
        "goal": directory / f"{prefix}_to_pose.xml",
        "route": directory / f"{prefix}_through_poses.xml",
    }


def snapshot_navigation_trees(source_directory, cache_directory, *, use_lidar=True, position_only=False):
    cache_directory = Path(cache_directory)
    cache_directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for operation, source in navigation_tree_files(source_directory, use_lidar).items():
        contents = source.read_bytes()
        if position_only:
            tree = ET.fromstring(contents)
            for follow in tree.iter("FollowPath"):
                follow.set("goal_checker_id", "position_goal_checker")
            contents = ET.tostring(tree, encoding="utf-8")
        digest = hashlib.sha256(contents).hexdigest()[:16]
        target = cache_directory / f"{operation}-{digest}.xml"
        if not target.exists():
            target.write_bytes(contents)
        result[operation] = str(target)
    return result
