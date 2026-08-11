# Visual Direction Contract

## Status

The published `personal-workspace-v1/1.0.0`, `meeting-room-v1/1.0.0`, and
`presentation-room-v1/1.0.0` bundles remain immutable technical compatibility
releases. They are not visually approved product defaults and must not be
activated without a replacement art review.

## Reference Policy

SenseTower scenes are private visual references only. They may be inspected to
understand architectural richness, scale, composition, material contrast,
lighting hierarchy, prop density, and spatial identity.

The following are prohibited in public bundles and tracked sources:

- imported SenseTower meshes or scene hierarchy;
- copied textures, materials, images, fonts, logos, or shader assets;
- traced decorative motifs or scene-specific trade dress;
- private source files, screenshots, or private asset URLs.

All shipped geometry, textures, materials, lighting, and decorative content
must be original Vrata work with independent source provenance.

## Quality Bar

Every replacement candidate must provide:

- an intentional architectural composition, not a decorated rectangular shell;
- at least three visually distinct material families with readable scale;
- layered wall and ceiling treatment with a clear focal hierarchy;
- original furniture silhouettes and secondary props at human scale;
- a spawn view that immediately communicates the room's purpose;
- lighting that separates navigation, faces, surfaces, and focal objects;
- clear interaction surfaces and seats integrated into the visual design;
- mobile-lite and XR budgets without replacing detail with broad flat planes.

## Reference Mapping

- Meeting room: Meeting_small is the primary benchmark for layered wood, stone,
  glazing, integrated planting, a sculptural ceiling feature, and a focused
  collaboration wall.
- Personal workspace: BlueOffice and office scenes are benchmarks for material
  depth, work-focused zoning, storage, and warm task lighting.
- Presentation room: TheLectureHall and Hall are benchmarks for spatial rhythm,
  audience focus, architectural framing, and controlled stage lighting.

The mapping describes qualities to evaluate, not elements to reproduce.

## Approval Gate

A candidate remains a review asset until all of the following are true:

1. Static validation and source reproduction are green.
2. The exact immutable candidate is loaded in a staging review room.
3. Desktop spawn framing and interaction surfaces are verified.
4. Mobile and Meta Quest budgets and navigation are verified.
5. The product owner explicitly approves the visual result.

Technical validation alone never grants visual approval. Promotion must copy
the approved candidate bytes into a new immutable product release; it must not
regenerate or overwrite an existing release.
