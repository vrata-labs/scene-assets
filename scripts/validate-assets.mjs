import { readFile, readdir, stat } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import validator from "gltf-validator";

import { buildManifest, serializeManifest } from "./build-manifest.mjs";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(scriptPath), "..");
const maxBundleBytes = 15 * 1024 * 1024;

function assert(condition, code) {
  if (!condition) throw new Error(code);
}

async function releaseDirectories() {
  const scenesRoot = join(repoRoot, "assets", "scenes");
  const sceneEntries = await readdir(scenesRoot, { withFileTypes: true });
  const releases = [];
  for (const sceneEntry of sceneEntries) {
    if (!sceneEntry.isDirectory()) continue;
    const sceneRoot = join(scenesRoot, sceneEntry.name);
    const versionEntries = await readdir(sceneRoot, { withFileTypes: true });
    for (const versionEntry of versionEntries) {
      if (versionEntry.isDirectory()) releases.push(join(sceneRoot, versionEntry.name));
    }
  }
  return releases.sort();
}

function validateManifestShape(scene, releaseDir) {
  assert(scene.schemaVersion === 1, "invalid_scene_schema_version");
  assert(/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(scene.sceneId), "invalid_scene_id");
  assert(basename(dirname(releaseDir)) === scene.sceneId, "scene_id_path_mismatch");
  assert(/^0\.1\.\d+$/.test(basename(releaseDir)), "invalid_review_version");
  assert(scene.glbPath === "scene.glb", "invalid_glb_path");
  assert(scene.preview === "preview.webp", "invalid_preview_path");
  assert(Array.isArray(scene.spawnPoints) && scene.spawnPoints[0]?.id === "main", "invalid_main_spawn");
  assert(scene.bounds?.width > 0 && scene.bounds?.height > 0 && scene.bounds?.depth > 0, "invalid_bounds");
  assert(scene.rights?.owner === "vrata", "invalid_rights_owner");
  assert(scene.rights?.license === "internal-original", "invalid_rights_license");
  for (const scope of ["staging", "production", "web-runtime", "screenshots", "optimization"]) {
    assert(scene.rights.clearedFor?.includes(scope), `missing_rights_scope:${scope}`);
  }
  const seatIds = new Set();
  for (const seat of scene.anchors?.seatAnchors ?? []) {
    assert(!seatIds.has(seat.id), `duplicate_seat_id:${seat.id}`);
    seatIds.add(seat.id);
    assert(Number.isFinite(seat.yaw) && seat.radius > 0, `invalid_seat:${seat.id}`);
  }
  const surfaceIds = new Set();
  for (const surface of scene.mediaSurfaces ?? []) {
    assert(!surfaceIds.has(surface.surfaceId), `duplicate_surface_id:${surface.surfaceId}`);
    surfaceIds.add(surface.surfaceId);
    assert(surface.widthM > 0 && surface.heightM > 0, `invalid_surface:${surface.surfaceId}`);
  }
}

async function validateRelease(releaseDir, releaseRecord) {
  const scene = JSON.parse(await readFile(join(releaseDir, "scene.json"), "utf8"));
  validateManifestShape(scene, releaseDir);
  let bundleBytes = 0;
  for (const name of ["scene.json", "scene.glb", "preview.webp", "LICENSES.md"]) {
    bundleBytes += (await stat(join(releaseDir, name))).size;
  }
  assert(bundleBytes <= maxBundleBytes, `review_bundle_too_large:${scene.sceneId}`);
  assert(releaseRecord.stats.triangles <= 90_000, `triangle_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.nodes <= 500, `node_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.meshes <= 250, `mesh_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.materials <= 96, `material_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.textures <= 48, `texture_budget_exceeded:${scene.sceneId}`);

  const glb = await readFile(join(releaseDir, scene.glbPath));
  const report = await validator.validateBytes(new Uint8Array(glb), {
    uri: `${scene.sceneId}/${basename(releaseDir)}/scene.glb`,
    maxIssues: 200
  });
  assert(report.issues.numErrors === 0, `gltf_validation_failed:${scene.sceneId}:${report.issues.numErrors}`);
  process.stdout.write(
    `${scene.sceneId}@${basename(releaseDir)}: ${releaseRecord.stats.triangles} triangles, ` +
    `${releaseRecord.stats.nodes} nodes, ${bundleBytes} bytes, ${report.issues.numWarnings} glTF warnings\n`
  );
}

const generatedManifest = await buildManifest();
const checkedManifest = await readFile(join(repoRoot, "manifest.json"), "utf8");
assert(checkedManifest === serializeManifest(generatedManifest), "release_manifest_out_of_date");
const releaseDirs = await releaseDirectories();
const releaseKeys = new Set(generatedManifest.releases.map((release) => `${release.sceneId}@${release.version}`));
assert(releaseKeys.size === generatedManifest.releases.length, "duplicate_scene_release");
for (const sceneId of ["personal-workspace-review-v1", "meeting-room-review-v1", "presentation-room-review-v1"]) {
  assert(releaseKeys.has(`${sceneId}@0.1.1`), `missing_current_review_release:${sceneId}`);
}
for (let index = 0; index < releaseDirs.length; index += 1) {
  await validateRelease(releaseDirs[index], generatedManifest.releases[index]);
}
process.stdout.write("All scene asset releases are valid.\n");
