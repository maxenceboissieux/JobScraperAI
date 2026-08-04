import { describe, expect, it } from "vitest";

import {
  parseJobDescription,
  type DescriptionBlock,
} from "./job-description-parser";

function joinBlockContent(blocks: DescriptionBlock[]) {
  return blocks
    .flatMap((block) => (block.type === "list" ? block.items : [block.text]))
    .join("\n");
}

describe("parseJobDescription", () => {
  it("sépare les titres connus concaténés sans reformuler le contenu", () => {
    expect(
      parseJobDescription(
        "PRÉSENTATION DE L’ENTREPRISEL’entreprise compte 150 personnes." +
          "DESCRIPTION DU POSTEIntégré(e) à l’équipe Scrum, vous développez le produit.",
      ),
    ).toEqual([
      { type: "heading", text: "PRÉSENTATION DE L’ENTREPRISE" },
      { type: "paragraph", text: "L’entreprise compte 150 personnes." },
      { type: "heading", text: "DESCRIPTION DU POSTE" },
      {
        type: "paragraph",
        text: "Intégré(e) à l’équipe Scrum, vous développez le produit.",
      },
    ]);
  });

  it("reconnaît les titres français et anglais sur leurs propres lignes", () => {
    expect(
      parseJobDescription("Missions\nConstruire le produit.\nABOUT THE ROLE\nOwn the API."),
    ).toEqual([
      { type: "heading", text: "Missions" },
      { type: "paragraph", text: "Construire le produit." },
      { type: "heading", text: "ABOUT THE ROLE" },
      { type: "paragraph", text: "Own the API." },
    ]);
  });

  it("ne promeut pas un titre connu présent dans une phrase ou un autre mot", () => {
    expect(
      parseJobDescription("Les missions du poste sont variées.\nLes commissions internes sont publiées."),
    ).toEqual([
      {
        type: "paragraph",
        text: "Les missions du poste sont variées.\nLes commissions internes sont publiées.",
      },
    ]);
  });

  it("reconnaît les libellés sans tenir compte de la casse", () => {
    expect(parseJobDescription("about us\nWe build useful tools.")).toEqual([
      { type: "heading", text: "about us" },
      { type: "paragraph", text: "We build useful tools." },
    ]);
  });

  it("applique les limites de mots et de majuscules aux titres génériques", () => {
    expect(parseJobDescription("ROLE API")).toEqual([{ type: "heading", text: "ROLE API" }]);
    expect(parseJobDescription("ROLE")).toEqual([{ type: "paragraph", text: "ROLE" }]);
    expect(parseJobDescription("ABCDE ef")).toEqual([{ type: "heading", text: "ABCDE ef" }]);
    expect(parseJobDescription("ABCD efg")).toEqual([{ type: "paragraph", text: "ABCD efg" }]);
    expect(
      parseJobDescription("ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT"),
    ).toEqual([{ type: "heading", text: "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT" }]);
    expect(
      parseJobDescription("ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE"),
    ).toEqual([{ type: "paragraph", text: "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE" }]);
  });

  it("convertit les marqueurs explicites en liste", () => {
    expect(parseJobDescription("Vos missions :\n- Concevoir\n• Tester\n* Documenter")).toEqual([
      { type: "heading", text: "Vos missions" },
      { type: "list", items: ["Concevoir", "Tester", "Documenter"] },
    ]);
  });

  it("convertit une énumération au point-virgule uniquement après une introduction", () => {
    expect(
      parseJobDescription("Vos missions : Comprendre le besoin ; Développer ; Livrer."),
    ).toEqual([
      { type: "heading", text: "Vos missions" },
      { type: "list", items: ["Comprendre le besoin", "Développer", "Livrer."] },
    ]);
  });

  it("laisse un texte ambigu dans un paragraphe", () => {
    expect(parseJobDescription("Paris ; Lyon ; télétravail possible")).toEqual([
      { type: "paragraph", text: "Paris ; Lyon ; télétravail possible" },
    ]);
  });

  it("conserve les chaînes ressemblant à du HTML comme texte", () => {
    expect(parseJobDescription("<img src=x onerror=alert(1)> Profil recherché")).toEqual([
      { type: "paragraph", text: "<img src=x onerror=alert(1)>" },
      { type: "heading", text: "Profil recherché" },
    ]);
  });

  it("conserve dans l’ordre les segments non structurels d’une longue description", () => {
    const segments = Array.from(
      { length: 260 },
      (_, index) => `Segment ${String(index).padStart(3, "0")} : contenu métier inchangé.`,
    );
    const description = `Missions\n${segments.join("\n")}\n- Concevoir\n- Tester\n`;
    const content = joinBlockContent(parseJobDescription(description));

    expect(description.length).toBeGreaterThan(10_000);
    let previousPosition = -1;
    for (const segment of segments) {
      const position = content.indexOf(segment);
      expect(position).toBeGreaterThan(previousPosition);
      previousPosition = position;
    }
    expect(content).toContain("Concevoir\nTester");
  });
});
