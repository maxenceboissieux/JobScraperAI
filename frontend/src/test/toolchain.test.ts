import { describe, expect, it } from "vitest";

import projectManifest from "../../package.json";
import pnpmManifest from "./fixtures/pnpm-10.28.2.package.json";

const approvedNodeFloors = ["20.19.0", "22.12.0"];

function supportsSimpleMinimum(engine: string, version: string): boolean {
  const minimum = /^>=(\d+)\.(\d+)$/.exec(engine);
  if (minimum === null) {
    return false;
  }
  const [major, minor] = version.split(".").map(Number);
  const minimumMajor = Number(minimum[1]);
  const minimumMinor = Number(minimum[2]);
  return major > minimumMajor || (major === minimumMajor && minor >= minimumMinor);
}

describe("métadonnées de l’outil pnpm", () => {
  it("épingle un gestionnaire dont le manifest publié accepte les deux planchers Node", () => {
    expect(projectManifest.packageManager).toBe(
      `${pnpmManifest.name}@${pnpmManifest.version}`,
    );
    expect(projectManifest.engines.pnpm).toBe(pnpmManifest.version);
    expect(
      approvedNodeFloors.every((version) =>
        supportsSimpleMinimum(pnpmManifest.engines.node, version),
      ),
    ).toBe(true);
  });
});
