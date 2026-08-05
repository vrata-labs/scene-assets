# Authoring Contract

## DCC

Scene sources are generated and saved with Blender 4.5.12 LTS. One Blender
unit equals one meter. The walkable floor is at Z=0 in Blender and Y=0 after
glTF export.

## Review Releases

The `0.1.x` line is for visual blockout review. It must remain technically
loadable through the normal Vrata Scene Bundle path, but it is not the final
`1.0.0` product art release.

Blender 4.5 bevel evaluation currently preserves scene structure, validation
stats, and rendered previews but is not bit-identical at the GLB buffer level
across fresh processes. For `0.1.x`, the published full Git commit SHA and its
checked `manifest.json` are authoritative. Product `1.0.0` promotion remains
blocked until deterministic post-processing produces repeatable GLB hashes.

## Rights

The current scenes are entirely procedural original work. No external meshes,
textures, scans, photographs, fonts, HDR files, audio, or private source files
are included. Publication does not grant a general reuse license; all rights
remain with Vrata unless a later repository license says otherwise.

## Publishing

Never replace files under an already published scene/version path. Create a
new version, rebuild `manifest.json`, validate it, and publish the resulting
Git commit. Runtime URLs must reference a full Git commit SHA.
