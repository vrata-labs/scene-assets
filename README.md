# Vrata Scene Assets

Original, versioned scene bundles for Vrata web and XR rooms.

The current release track contains three art-direction candidates. These are
not active product templates yet:

- `personal-workspace-review-v1/0.2.1`
- `meeting-room-review-v1/0.2.1`
- `presentation-room-review-v1/0.2.1`

The `0.1.x` paths remain immutable blockout history. `0.2.0` adds an original
embedded PBR material kit, detailed furniture and fixtures, layered ceilings,
and exportable punctual lights for runtime art-direction review. `0.2.1`
calibrates those lights for the Three.js runtime's physical intensity units.

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
RELEASE_VERSION=0.2.1 BLENDER_BIN=/path/to/blender pnpm build:scenes
pnpm validate
pnpm inspect
```

After generating a candidate, confirm that the tracked Blender sources
reproduce the release GLBs byte-for-byte:

```bash
RELEASE_VERSION=0.2.1 BLENDER_BIN=/path/to/blender pnpm verify:source-exports
```

The Blender source is procedural and uses no external meshes, textures,
fonts, photographs, or private scene files.
