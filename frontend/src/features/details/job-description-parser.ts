export type DescriptionBlock =
  | { type: "heading"; text: string }
  | { type: "paragraph"; text: string }
  | { type: "list"; items: string[] };

const SECTION_LABELS = [
  "présentation de l’entreprise",
  "présentation de l'entreprise",
  "description du poste",
  "missions",
  "vos missions",
  "missions principales",
  "profil recherché",
  "votre profil",
  "compétences",
  "avantages",
  "à propos",
  "about the role",
  "about us",
  "responsibilities",
  "requirements",
  "benefits",
] as const;

const sectionLabelPattern = new RegExp(
  `(${SECTION_LABELS.slice().sort((left, right) => right.length - left.length).map(escapeRegExp).join("|")})`,
  "gi",
);

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isSectionLabel(value: string) {
  return SECTION_LABELS.some((label) => label.localeCompare(value, undefined, { sensitivity: "accent" }) === 0);
}

function hasStructuralContextBefore(description: string, index: number) {
  return /(?:^|\n)[\t ]*$|[.!?]\s*$|>\s*$/u.test(description.slice(0, index));
}

function hasStructuralContextAfter(description: string, index: number) {
  const remainder = description.slice(index);
  return /^[\t ]*(?:$|\n|:)/u.test(remainder) || /^\p{Lu}/u.test(remainder);
}

function insertSectionBoundaries(description: string) {
  let result = "";
  let cursor = 0;

  for (const match of description.matchAll(sectionLabelPattern)) {
    const index = match.index ?? 0;
    const label = match[0];
    const end = index + label.length;
    result += description.slice(cursor, index);
    result += hasStructuralContextBefore(description, index) && hasStructuralContextAfter(description, end)
      ? `\n${label}\n`
      : label;
    cursor = end;
  }

  return result + description.slice(cursor);
}

function isUppercaseHeading(value: string) {
  const words = value.match(/[\p{L}\p{N}]+/gu) ?? [];
  const letters = value.match(/\p{L}/gu) ?? [];
  const uppercaseLetters = letters.filter((letter) => letter === letter.toLocaleUpperCase());

  return words.length >= 2 && words.length <= 8 && letters.length > 0 && uppercaseLetters.length / letters.length >= 0.7;
}

function addParagraph(blocks: DescriptionBlock[], lines: string[]) {
  if (lines.length > 0) {
    blocks.push({ type: "paragraph", text: lines.join("\n") });
    lines.length = 0;
  }
}

function addList(blocks: DescriptionBlock[], items: string[]) {
  if (items.length > 0) {
    blocks.push({ type: "list", items: [...items] });
    items.length = 0;
  }
}

export function parseJobDescription(description: string): DescriptionBlock[] {
  const normalized = description.replace(/\r\n?/g, "\n").replace(/^[\t ]+$/gm, "");
  const lines = insertSectionBoundaries(normalized).split("\n");
  const blocks: DescriptionBlock[] = [];
  const paragraphLines: string[] = [];
  const listItems: string[] = [];
  let lastBlockWasRecognizedHeading = false;

  const flush = () => {
    addParagraph(blocks, paragraphLines);
    addList(blocks, listItems);
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flush();
      continue;
    }

    const markedItem = line.match(/^(?:[-*•]\s*|\d+[.)]\s+)(.+)$/u);
    if (markedItem) {
      addParagraph(blocks, paragraphLines);
      listItems.push(markedItem[1].trim());
      lastBlockWasRecognizedHeading = false;
      continue;
    }

    addList(blocks, listItems);

    if (isSectionLabel(line) || isUppercaseHeading(line)) {
      addParagraph(blocks, paragraphLines);
      blocks.push({ type: "heading", text: line });
      lastBlockWasRecognizedHeading = isSectionLabel(line);
      continue;
    }

    if (lastBlockWasRecognizedHeading && line.startsWith(":")) {
      const introduced = line.slice(1).trim();
      if (!introduced) {
        continue;
      }
      const items = introduced.split(";").map((item) => item.trim()).filter(Boolean);
      if (items.length > 1) {
        blocks.push({ type: "list", items });
      } else {
        paragraphLines.push(introduced);
      }
      lastBlockWasRecognizedHeading = false;
      continue;
    }

    paragraphLines.push(line);
    lastBlockWasRecognizedHeading = false;
  }

  flush();
  return blocks;
}
