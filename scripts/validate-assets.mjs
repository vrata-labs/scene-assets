import { createHash } from "node:crypto";
import { readFile, readdir, stat } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import validator from "gltf-validator";

import { buildManifest, serializeManifest } from "./build-manifest.mjs";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(scriptPath), "..");
const maxBundleBytes = 15 * 1024 * 1024;
const maxPunctualLightIntensity = 10;
const currentArtCandidateVersion = "0.2.2";
const finalTemplateVersion = "1.0.0";
const maxOptimizedReleaseMeshes = 100;
const bundleFileNames = ["LICENSES.md", "preview.webp", "scene.glb", "scene.json"];
const finalPromotions = [
  {
    sourceSceneId: "personal-workspace-review-v1",
    finalSceneId: "personal-workspace-v1",
    sourceSha256: "041cd832447b1cd4a6d26c7d4694f66cfc2e988a3516100201243d19bebcd2b9",
    surfaceAspects: new Map([["debug-main", 2]])
  },
  {
    sourceSceneId: "meeting-room-review-v1",
    finalSceneId: "meeting-room-v1",
    sourceSha256: "760213b87a75f4bb08dbf87abc392ef1c726b060d0b19efad5f3b2f9228e5d52",
    surfaceAspects: new Map([["debug-main", 16 / 9], ["whiteboard-wall", 48 / 25]])
  },
  {
    sourceSceneId: "presentation-room-review-v1",
    finalSceneId: "presentation-room-v1",
    sourceSha256: "8753a48345b2d2fe7567328013b8c05addd258b4a0b849d1131adf50015095eb",
    surfaceAspects: new Map([["debug-main", 16 / 9]])
  }
];
const optimizedReleaseSurfaceAspects = new Map(finalPromotions.flatMap((promotion) => [
  [`${promotion.sourceSceneId}@${currentArtCandidateVersion}`, promotion.surfaceAspects],
  [`${promotion.finalSceneId}@${finalTemplateVersion}`, promotion.surfaceAspects]
]));
optimizedReleaseSurfaceAspects.set(
  "meeting-room-review-v2@0.3.0",
  new Map([["debug-main", 16 / 9], ["whiteboard-wall", 48 / 25]])
);
const trackedReviewSources = [
  {
    sceneId: "meeting-room-review-v2",
    sha256: "d150bef942b9f7ee91a5b582008111a151da2b315a49a1db367ad67295e7ca93"
  }
];
const knownOverbrightReleases = new Set([
  "meeting-room-review-v1@0.2.0",
  "personal-workspace-review-v1@0.2.0",
  "presentation-room-review-v1@0.2.0"
]);

function assert(condition, code) {
  if (!condition) throw new Error(code);
}

function normalizePromotedScene(scene) {
  const normalizeScopedId = (id) => {
    assert(typeof id === "string" && id.startsWith(`${scene.sceneId}-`), `invalid_scene_scoped_id:${scene.sceneId}:${id}`);
    return `<scene-id>${id.slice(scene.sceneId.length)}`;
  };
  return {
    ...scene,
    sceneId: "<scene-id>",
    label: "<release-label>",
    anchors: {
      ...scene.anchors,
      seatAnchors: (scene.anchors?.seatAnchors ?? []).map((seat) => ({ ...seat, id: normalizeScopedId(seat.id) }))
    },
    rights: {
      ...scene.rights,
      sourceAssets: (scene.rights?.sourceAssets ?? []).map((asset) => ({ ...asset, id: normalizeScopedId(asset.id) }))
    },
    visual: scene.visual ? { ...scene.visual, reviewStage: "<release-stage>" } : scene.visual,
    notes: "<release-notes>"
  };
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
  assert(/^\d+\.\d+\.\d+$/.test(basename(releaseDir)), "invalid_release_version");
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

function parseGlbJson(glb) {
  assert(glb.readUInt32LE(0) === 0x46546c67, "invalid_glb_magic");
  const jsonLength = glb.readUInt32LE(12);
  assert(glb.readUInt32LE(16) === 0x4e4f534a, "missing_glb_json_chunk");
  return JSON.parse(glb.subarray(20, 20 + jsonLength).toString("utf8").trimEnd());
}

async function validateRelease(releaseDir, releaseRecord) {
  const scene = JSON.parse(await readFile(join(releaseDir, "scene.json"), "utf8"));
  validateManifestShape(scene, releaseDir);
  const releaseKey = `${scene.sceneId}@${basename(releaseDir)}`;
  const expectedSurfaceAspects = optimizedReleaseSurfaceAspects.get(releaseKey);
  if (expectedSurfaceAspects) {
    assert(releaseRecord.stats.meshes <= maxOptimizedReleaseMeshes, `optimized_release_mesh_budget_exceeded:${releaseKey}`);
    for (const [surfaceId, expectedAspect] of expectedSurfaceAspects) {
      const surface = scene.mediaSurfaces?.find((candidate) => candidate.surfaceId === surfaceId);
      assert(surface, `missing_optimized_release_surface:${releaseKey}:${surfaceId}`);
      const physicalAspect = surface.widthM / surface.heightM;
      const pixelAspect = surface.widthPx / surface.heightPx;
      assert(Math.abs(physicalAspect - expectedAspect) / expectedAspect <= 0.02, `optimized_release_physical_aspect_mismatch:${releaseKey}:${surfaceId}`);
      assert(Math.abs(pixelAspect - expectedAspect) / expectedAspect <= 0.02, `optimized_release_pixel_aspect_mismatch:${releaseKey}:${surfaceId}`);
    }
  }
  const releaseEntries = await readdir(releaseDir, { withFileTypes: true });
  const releaseFileNames = releaseEntries.filter((entry) => entry.isFile()).map((entry) => entry.name).sort();
  assert(releaseEntries.every((entry) => entry.isFile()), `unexpected_release_directory:${scene.sceneId}`);
  assert(JSON.stringify(releaseFileNames) === JSON.stringify(bundleFileNames), `unexpected_release_files:${scene.sceneId}`);
  let bundleBytes = 0;
  for (const name of bundleFileNames) {
    bundleBytes += (await stat(join(releaseDir, name))).size;
  }
  assert(bundleBytes <= maxBundleBytes, `review_bundle_too_large:${scene.sceneId}`);
  assert(releaseRecord.stats.triangles <= 90_000, `triangle_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.nodes <= 500, `node_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.meshes <= 250, `mesh_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.materials <= 96, `material_budget_exceeded:${scene.sceneId}`);
  assert(releaseRecord.stats.textures <= 48, `texture_budget_exceeded:${scene.sceneId}`);

  const glb = await readFile(join(releaseDir, scene.glbPath));
  if (!knownOverbrightReleases.has(releaseKey)) {
    const gltf = parseGlbJson(glb);
    for (const light of gltf.extensions?.KHR_lights_punctual?.lights ?? []) {
      assert(
        light.intensity === undefined || light.intensity <= maxPunctualLightIntensity,
        `punctual_light_intensity_exceeded:${scene.sceneId}:${light.name ?? "unnamed"}`
      );
    }
  }
  const report = await validator.validateBytes(new Uint8Array(glb), {
    uri: `${scene.sceneId}/${basename(releaseDir)}/scene.glb`,
    maxIssues: 200
  });
  assert(report.issues.numErrors === 0, `gltf_validation_failed:${scene.sceneId}:${report.issues.numErrors}`);
  if (report.issues.numWarnings > 0) {
    const warningCounts = new Map();
    for (const issue of report.issues.messages.filter((message) => message.severity === 1)) {
      warningCounts.set(issue.code, (warningCounts.get(issue.code) ?? 0) + 1);
    }
    process.stdout.write(`${scene.sceneId}@${basename(releaseDir)} warning codes: ${Array.from(warningCounts.entries()).map(([code, count]) => `${code}=${count}`).join(", ")}\n`);
    for (const issue of report.issues.messages.filter((message) => message.severity === 1).slice(0, 10)) {
      process.stdout.write(`  ${issue.code}: ${issue.pointer ?? issue.message}\n`);
    }
  }
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
  assert(releaseKeys.has(`${sceneId}@${currentArtCandidateVersion}`), `missing_current_art_candidate:${sceneId}`);
}
for (const promotion of finalPromotions) {
  assert(releaseKeys.has(`${promotion.finalSceneId}@${finalTemplateVersion}`), `missing_final_template_release:${promotion.finalSceneId}`);
  const [sourceSceneFile, finalSceneFile, sourceBlend] = await Promise.all([
    readFile(join(repoRoot, "assets/scenes", promotion.sourceSceneId, currentArtCandidateVersion, "scene.json"), "utf8"),
    readFile(join(repoRoot, "assets/scenes", promotion.finalSceneId, finalTemplateVersion, "scene.json"), "utf8"),
    readFile(join(repoRoot, "sources", promotion.sourceSceneId, "source.blend"))
  ]);
  const sourceScene = normalizePromotedScene(JSON.parse(sourceSceneFile));
  const finalScene = normalizePromotedScene(JSON.parse(finalSceneFile));
  assert(JSON.stringify(sourceScene) === JSON.stringify(finalScene), `final_promotion_manifest_mismatch:${promotion.finalSceneId}`);
  const sourceSha256 = createHash("sha256").update(sourceBlend).digest("hex");
  assert(sourceSha256 === promotion.sourceSha256, `tracked_source_hash_mismatch:${promotion.sourceSceneId}`);
  for (const fileName of ["scene.glb", "preview.webp"]) {
    const [sourceFile, finalFile] = await Promise.all([
      readFile(join(repoRoot, "assets/scenes", promotion.sourceSceneId, currentArtCandidateVersion, fileName)),
      readFile(join(repoRoot, "assets/scenes", promotion.finalSceneId, finalTemplateVersion, fileName))
    ]);
    assert(sourceFile.equals(finalFile), `final_promotion_asset_mismatch:${promotion.finalSceneId}:${fileName}`);
  }
}
for (const source of trackedReviewSources) {
  const sourceBlend = await readFile(join(repoRoot, "sources", source.sceneId, "source.blend"));
  const sourceSha256 = createHash("sha256").update(sourceBlend).digest("hex");
  assert(sourceSha256 === source.sha256, `tracked_source_hash_mismatch:${source.sceneId}`);
}
for (let index = 0; index < releaseDirs.length; index += 1) {
  await validateRelease(releaseDirs[index], generatedManifest.releases[index]);
}
process.stdout.write("All scene asset releases are valid.\n");
