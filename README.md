# Vrata Scene Assets

Original, versioned scene bundles for Vrata web and XR rooms.

The first release track contains three visual-review blockouts. These are not
active product templates yet:

- `personal-workspace-review-v1/0.1.1`
- `meeting-room-review-v1/0.1.1`
- `presentation-room-review-v1/0.1.1`

The original `0.1.0` paths remain immutable. `0.1.1` closes the room ceilings
after the first runtime review exposed black background above the walls.

## Layout

```text
sources/<scene-id>/source.blend
assets/scenes/<scene-id>/<version>/scene.json
assets/scenes/<scene-id>/<version>/scene.glb
assets/scenes/<scene-id>/<version>/preview.webp
assets/scenes/<scene-id>/<version>/LICENSES.md
manifest.json
```

Published version directories are immutable. Any visual or behavioral change
must use a new version directory.

## Toolchain

- Blender `4.5.12 LTS`
- Node.js `22`
- pnpm `10.0.0`
- glTF Transform `4.4.2`
- Khronos glTF Validator `2.0.0-dev.3.10`
- Vrata platform validator pinned by `platform-validator.lock`

## Build

```bash
pnpm install
REVIEW_VERSION=0.1.2 BLENDER_BIN=/path/to/blender pnpm build:scenes
pnpm validate
pnpm inspect
```

The Blender source is procedural and uses no external meshes, textures,
fonts, photographs, or private scene files.
