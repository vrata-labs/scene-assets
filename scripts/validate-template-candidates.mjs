import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const repoRoot = resolve(import.meta.dirname, "..");
const platformRoot = resolve(repoRoot, process.env.VRATA_PLATFORM_ROOT ?? ".platform");
const candidateVersion = "0.2.2";
const candidates = [
  { templateId: "personal-room-basic", sceneId: "personal-workspace-review-v1" },
  { templateId: "meeting-room-basic", sceneId: "meeting-room-review-v1" },
  { templateId: "presentation-room-basic", sceneId: "presentation-room-review-v1" }
];

const assetPipeline = await import(pathToFileURL(join(platformRoot, "packages/asset-pipeline/dist/index.js")));
const templates = await import(pathToFileURL(join(platformRoot, "packages/templates/dist/index.js")));

for (const candidate of candidates) {
  const productContract = templates.getStandardRoomTemplateSceneContract(candidate.templateId, "1.0.0");
  if (!productContract) throw new Error(`missing_platform_template_contract:${candidate.templateId}@1.0.0`);

  const releasePath = join(repoRoot, "assets/scenes", candidate.sceneId, candidateVersion);
  const result = await assetPipeline.validateSceneBundlePath(releasePath, {
    maxMainAssetBytes: 15 * 1024 * 1024,
    maxBundleBytes: 15 * 1024 * 1024,
    templateContract: productContract,
    sceneVersion: candidateVersion
  });
  const errorCodes = result.issues
    .filter((issue) => issue.severity === "error")
    .map((issue) => issue.code)
    .sort();
  const expectedTransitionalErrorCodes = ["template_scene_id_mismatch", "template_scene_version_mismatch"];
  if (JSON.stringify(errorCodes) !== JSON.stringify(expectedTransitionalErrorCodes)) {
    for (const issue of result.issues) {
      process.stderr.write(`${candidate.sceneId}@${candidateVersion}:${issue.code}:${issue.message}\n`);
    }
    throw new Error(`template_candidate_validation_failed:${candidate.sceneId}@${candidateVersion}`);
  }
  process.stdout.write(`${candidate.sceneId}@${candidateVersion} matches ${candidate.templateId}@1.0.0 surfaces and seats; final scene identity/version remain intentionally pending.\n`);
}
