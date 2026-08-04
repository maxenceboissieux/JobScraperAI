import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

const detailLogPath = process.env.JOBSCRAPER_FAKE_DETAIL_LOG;

if (detailLogPath === undefined) {
  throw new Error("JOBSCRAPER_FAKE_DETAIL_LOG doit être défini par le runner E2E");
}

async function detailCalls(source: string): Promise<number> {
  try {
    const contents = await readFile(detailLogPath, "utf8");
    return contents.split("\n").filter((line) => line === source).length;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return 0;
    }
    throw error;
  }
}

test("recherche, synchronisation, filtres, cache et doublon possible", async ({
  page,
}) => {
  const localOrigin = new URL(process.env.JOBSCRAPER_E2E_BASE_URL ?? "").origin;
  const unexpectedNetwork: string[] = [];
  const detailApiRequests: string[] = [];
  page.on("request", (request) => {
    const requested = new URL(request.url());
    if (requested.protocol.startsWith("http") && requested.origin !== localOrigin) {
      unexpectedNetwork.push(request.url());
    }
    if (
      request.method() === "GET" &&
      requested.origin === localOrigin &&
      /^\/api\/jobs\/[^/]+$/.test(requested.pathname)
    ) {
      detailApiRequests.push(request.url());
    }
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Nouvelle recherche" }).click();
  await page.getByLabel("Nom").fill("Backend remote");
  await page.getByLabel("Mots-clés").fill("backend");
  await page.getByLabel("Free-Work").check();
  await page.getByLabel("HelloWork").check();
  await page.getByRole("button", { name: "Enregistrer la recherche" }).click();
  await expect(page.getByRole("status")).toContainText(
    "La recherche « Backend remote » a été créée.",
  );

  await page.getByRole("button", { name: "Actualiser" }).click();
  await expect(page.getByText("Free-Work : terminée")).toBeVisible();
  await expect(page.getByText("HelloWork : terminée")).toBeVisible();
  await expect(page.getByText("Synchronisation terminée", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "24 h" }).click();
  await expect(page.getByText("1 offre", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Voir l’offre Développeur Python" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "3 jours" }).click();
  await expect(page.getByText("2 offres", { exact: true })).toBeVisible();
  await page.getByLabel("Doublons").selectOption("possible");
  await expect(page.getByText("2 offres", { exact: true })).toBeVisible();
  await expect(page.getByText("Doublon possible")).toHaveCount(2);

  await page.getByLabel("Sources", { exact: true }).selectOption("freework");
  await expect(page.getByText("1 offre", { exact: true })).toBeVisible();
  const pythonCard = page.getByRole("article").filter({
    has: page.getByRole("button", { name: "Voir l’offre Développeur Python" }),
  });
  await expect(pythonCard).toContainText("CDI");
  await expect(pythonCard).toContainText("Senior");
  await expect(pythonCard).toContainText("Télétravail");
  await expect(pythonCard).toContainText("Free-Work");
  await expect(pythonCard).toContainText("Doublon possible");

  await page.getByRole("button", { name: "Effacer les filtres" }).click();
  await expect(page.getByText("2 offres", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Voir l’offre Développeur Python" }).click();
  let drawer = page.getByRole("dialog", { name: "Détails de l’offre" });
  await expect(drawer).toContainText("Description mise en cache");
  await expect(drawer).toContainText("Compétences");
  await expect(drawer).toContainText("FastAPI");
  await expect(drawer).toContainText("Avantages");
  const freeWorkLink = drawer.getByRole("link", { name: /Free-Work/ });
  await expect(freeWorkLink).toHaveAttribute(
    "href",
    "https://example.invalid/freework/developpeur-python",
  );
  await expect.poll(() => detailCalls("freework")).toBe(1);
  expect(detailApiRequests).toHaveLength(1);

  await page.getByRole("button", { name: "Fermer les détails" }).click();
  await page.reload();
  await page.getByRole("button", { name: "Voir l’offre Développeur Python" }).click();
  drawer = page.getByRole("dialog", { name: "Détails de l’offre" });
  await expect(drawer).toContainText("Description mise en cache");
  await expect.poll(() => detailCalls("freework")).toBe(1);
  expect(detailApiRequests).toHaveLength(2);

  await drawer
    .getByRole("button", { name: /Voir l’offre similaire Développeur Backend Python/ })
    .click();
  await expect(drawer.getByRole("heading", { name: "Développeur Backend Python" })).toBeVisible();
  await expect(drawer.getByRole("link", { name: /HelloWork/ })).toHaveAttribute(
    "href",
    "https://example.invalid/hellowork/developpeur-backend-python",
  );
  await expect(
    drawer.getByRole("button", { name: "Voir l’offre similaire Développeur Python" }),
  ).toBeVisible();

  expect(unexpectedNetwork).toEqual([]);
});
