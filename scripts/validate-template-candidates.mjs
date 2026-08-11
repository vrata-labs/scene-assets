import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const repoRoot = resolve(import.meta.dirname, "..");
const platformRoot = resolve(repoRoot, process.env.VRATA_PLATFORM_ROOT ?? ".platform");
const releases = [
  {
    templateId: "personal-room-basic",
    sceneId: "personal-workspace-review-v1",
    sceneVersion: "0.2.2",
    expectedErrorCodes: ["template_scene_id_mismatch", "template_scene_version_mismatch"]
  },
  {
    templateId: "personal-room-basic",
    sceneId: "personal-workspace-review-v2",
    sceneVersion: "0.3.0",
    expectedErrorCodes: ["template_scene_id_mismatch", "template_scene_version_mismatch"]
  },
  {
    templateId: "meeting-room-basic",
    sceneId: "meeting-room-review-v1",
    sceneVersion: "0.2.2",
    expectedErrorCodes: ["template_scene_id_mismatch", "template_scene_version_mismatch"]
  },
  {
    templateId: "meeting-room-basic",
    sceneId: "meeting-room-review-v2",
    sceneVersion: "0.3.0",
    expectedErrorCodes: ["template_scene_id_mismatch", "template_scene_version_mismatch"]
  },
  {
    templateId: "meeting-room-basic",
    sceneId: "meeting-room-review-v2",
    sceneVersion: "0.3.1",
    expectedErrorCodes: ["template_scene_id_mismatch", "template_scene_version_mismatch"]
  },
  {
    templateId: "presentation-room-basic",
    sceneId: "presentation-room-review-v1",
    sceneVersion: "0.2.2",
    expectedErrorCodes: ["template_scene_id_mismatch", "template_scene_version_mismatch"]
  },
  { templateId: "personal-room-basic", sceneId: "personal-workspace-v1", sceneVersion: "1.0.0", expectedErrorCodes: [] },
  { templateId: "meeting-room-basic", sceneId: "meeting-room-v1", sceneVersion: "1.0.0", expectedErrorCodes: [] },
  { templateId: "presentation-room-basic", sceneId: "presentation-room-v1", sceneVersion: "1.0.0", expectedErrorCodes: [] }
];

const assetPipeline = await import(pathToFileURL(join(platformRoot, "packages/asset-pipeline/dist/index.js")));
const templates = await import(pathToFileURL(join(platformRoot, "packages/templates/dist/index.js")));

for (const release of releases) {
  const productContract = templates.getStandardRoomTemplateSceneContract(release.templateId, "1.0.0");
  if (!productContract) throw new Error(`missing_platform_template_contract:${release.templateId}@1.0.0`);

  const releasePath = join(repoRoot, "assets/scenes", release.sceneId, release.sceneVersion);
  const result = await assetPipeline.validateSceneBundlePath(releasePath, {
    maxMainAssetBytes: 15 * 1024 * 1024,
    maxBundleBytes: 15 * 1024 * 1024,
    templateContract: productContract,
    sceneVersion: release.sceneVersion
  });
  const errorCodes = result.issues
    .filter((issue) => issue.severity === "error")
    .map((issue) => issue.code)
    .sort();
  if (JSON.stringify(errorCodes) !== JSON.stringify(release.expectedErrorCodes)) {
    for (const issue of result.issues) {
      process.stderr.write(`${release.sceneId}@${release.sceneVersion}:${issue.code}:${issue.message}\n`);
    }
    throw new Error(`template_release_validation_failed:${release.sceneId}@${release.sceneVersion}`);
  }
  const status = errorCodes.length === 0
    ? "passes final scene identity, surface geometry, and seat count checks"
    : "matches final surfaces and seats; identity/version remain transitional";
  process.stdout.write(`${release.sceneId}@${release.sceneVersion} ${status} for ${release.templateId}@1.0.0.\n`);
}
