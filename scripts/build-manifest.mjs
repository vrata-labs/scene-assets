import { createHash } from "node:crypto";
import { readFile, readdir, stat, writeFile } from "node:fs/promises";
import { basename, dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = resolve(dirname(scriptPath), "..");

function toPosix(path) {
  return path.split(sep).join("/");
}

async function sha256(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

async function fileRecord(path) {
  const info = await stat(path);
  return {
    sha256: await sha256(path),
    sizeBytes: info.size
  };
}

function primitiveTriangleCount(primitive) {
  const count = primitive.getIndices()?.getCount() ?? primitive.getAttribute("POSITION")?.getCount() ?? 0;
  const mode = primitive.getMode();
  if (mode === 4) return Math.floor(count / 3);
  if (mode === 5 || mode === 6) return Math.max(0, count - 2);
  return 0;
}

async function glbStats(path) {
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS);
  const document = await io.read(path);
  const root = document.getRoot();
  const meshes = root.listMeshes();
  return {
    triangles: meshes.reduce(
      (total, mesh) => total + mesh.listPrimitives().reduce((sum, primitive) => sum + primitiveTriangleCount(primitive), 0),
      0
    ),
    nodes: root.listNodes().length,
    meshes: meshes.length,
    primitives: meshes.reduce((total, mesh) => total + mesh.listPrimitives().length, 0),
    materials: root.listMaterials().length,
    textures: root.listTextures().length,
    animations: root.listAnimations().length
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

async function buildRelease(releaseDir) {
  const sceneJsonPath = join(releaseDir, "scene.json");
  const scene = JSON.parse(await readFile(sceneJsonPath, "utf8"));
  const version = basename(releaseDir);
  const requiredFiles = ["scene.json", scene.glbPath, scene.preview, "LICENSES.md"];
  const files = {};
  for (const name of requiredFiles) files[name] = await fileRecord(join(releaseDir, name));
  return {
    sceneId: scene.sceneId,
    version,
    releasePath: toPosix(relative(repoRoot, releaseDir)),
    files,
    stats: await glbStats(join(releaseDir, scene.glbPath))
  };
}

export async function buildManifest() {
  const platformValidatorCommit = (await readFile(join(repoRoot, "platform-validator.lock"), "utf8")).trim();
  const releases = [];
  for (const releaseDir of await releaseDirectories()) releases.push(await buildRelease(releaseDir));
  return {
    schemaVersion: 1,
    blenderVersion: "4.5.12 LTS",
    platformValidatorCommit,
    releases
  };
}

export function serializeManifest(manifest) {
  return `${JSON.stringify(manifest, null, 2)}\n`;
}

async function main() {
  const outputPath = join(repoRoot, "manifest.json");
  const expected = serializeManifest(await buildManifest());
  if (process.argv.includes("--check")) {
    const actual = await readFile(outputPath, "utf8");
    if (actual !== expected) throw new Error("release_manifest_out_of_date");
    process.stdout.write("Release manifest is current.\n");
    return;
  }
  await writeFile(outputPath, expected);
  process.stdout.write(`Wrote ${toPosix(relative(repoRoot, outputPath))}.\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await main();
}
