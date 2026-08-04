import { defineConfig } from "@playwright/test";

const baseURL = process.env.JOBSCRAPER_E2E_BASE_URL;

if (baseURL === undefined) {
  throw new Error("JOBSCRAPER_E2E_BASE_URL doit être défini par scripts/run-e2e.sh");
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: {
    timeout: 15_000,
  },
  outputDir: process.env.JOBSCRAPER_E2E_ARTIFACTS,
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
  },
});
