# Vrata Scene Assets

Original, versioned scene bundles for Vrata web and XR rooms.

The technical compatibility release track contains three contract-complete scene bundles:

- `personal-workspace-v1/1.0.0`
- `meeting-room-v1/1.0.0`
- `presentation-room-v1/1.0.0`

Their GLB and preview files are byte-identical promotions of the previously
accepted `0.2.2` technical candidates. The manifests provide product scene identities,
seat anchors, and contract-checked surface geometry. Runtime-significant
manifest values remain equal to the candidates after normalizing identity and
release-facing descriptions. Product catalog activation is managed separately
by the platform repository. These `1.0.0` releases are not approved as the
final visual direction and must not be activated as product defaults.

The `0.1.x` paths remain immutable blockout history. `0.2.0` adds an original
embedded PBR material kit, detailed furniture and fixtures, layered ceilings,
and exportable punctual lights for runtime art-direction review. `0.2.1`
calibrates those lights for the Three.js runtime's physical intensity units.
`0.2.2` aligns media geometry with the template surface contracts, clears the
runtime planes from decorative overlays, and consolidates static furniture for
mobile/XR mesh headroom.

The replacement art track includes `meeting-room-review-v2/0.3.x` and
`personal-workspace-review-v2/0.3.0`. It uses private SenseTower scenes only as
a visual benchmark. No private geometry, materials, textures, images, or source
files may enter this repository. See `docs/visual-direction.md` for the
mandatory visual approval gate.

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
RELEASE_VERSION=0.2.2 BLENDER_BIN=/path/to/blender pnpm build:scenes
pnpm validate
pnpm inspect
```

After generating a candidate, confirm that the tracked Blender sources
reproduce the release GLBs byte-for-byte:

```bash
RELEASE_VERSION=0.2.2 BLENDER_BIN=/path/to/blender pnpm verify:source-exports
```

Final `1.0.0` releases must not be generated with `pnpm build:scenes`. They
promote the accepted candidate GLB and preview without changing either binary.
Validation also locks each source blend hash and compares normalized candidate
and final manifests. The source verifier maps the tracked review source IDs to
the final product IDs:

```bash
RELEASE_VERSION=1.0.0 BLENDER_BIN=/path/to/blender pnpm verify:source-exports
```

The Blender source is procedural and uses no external meshes, textures,
fonts, photographs, or private scene files.

The meeting replacement candidate can be rebuilt and verified independently:

```bash
RELEASE_VERSION=0.3.1 BUILD_SCENE=meeting-v2 BLENDER_BIN=/path/to/blender pnpm build:scenes
RELEASE_VERSION=0.3.1 SOURCE_SCENE_IDS=meeting-room-review-v2 BLENDER_BIN=/path/to/blender pnpm verify:source-exports
```

The personal workspace replacement candidate uses the same selective path:

```bash
RELEASE_VERSION=0.3.0 BUILD_SCENE=personal-v2 BLENDER_BIN=/path/to/blender pnpm build:scenes
RELEASE_VERSION=0.3.0 SOURCE_SCENE_IDS=personal-workspace-review-v2 BLENDER_BIN=/path/to/blender pnpm verify:source-exports
```

The official origin is `https://github.com/vrata-labs/scene-assets`. Runtime
URLs must use a full 40-character commit SHA, for example
`https://cdn.jsdelivr.net/gh/vrata-labs/scene-assets@<commit-sha>/assets/scenes/<scene-id>/<version>/scene.json`.
