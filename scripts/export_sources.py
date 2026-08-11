import argparse
import re
import sys
from pathlib import Path

import bpy


BLENDER_VERSION = (4, 5, 12)
SCENE_IDS = (
    "personal-workspace-review-v1",
    "meeting-room-review-v1",
    "presentation-room-review-v1",
)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--scene-id",
        action="append",
        choices=SCENE_IDS + ("personal-workspace-review-v2", "meeting-room-review-v2"),
    )
    return parser.parse_args(argv)


def main():
    if bpy.app.version[:3] != BLENDER_VERSION:
        raise RuntimeError(f"expected_blender_{BLENDER_VERSION}_got_{bpy.app.version[:3]}")
    args = parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise RuntimeError(f"invalid_release_version:{args.version}")

    repo_root = Path(args.repo_root).resolve()
    output_root = Path(args.output_root).resolve()
    for scene_id in args.scene_id or SCENE_IDS:
        source_path = repo_root / "sources" / scene_id / "source.blend"
        output_dir = output_root / scene_id
        output_dir.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.open_mainfile(filepath=str(source_path))
        bpy.ops.export_scene.gltf(
            filepath=str(output_dir / "scene.glb"),
            export_format="GLB",
            export_cameras=False,
            export_lights=True,
            export_tangents=True,
            export_yup=True,
            export_apply=False,
            export_image_format="AUTO",
        )
        print(f"Exported {scene_id}@{args.version} from tracked source.blend")


main()
