import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JobDescription } from "./JobDescription";

describe("JobDescription", () => {
  it("rend les sections et listes avec une sémantique accessible", () => {
    render(
      <JobDescription description={"MISSIONS\n- Concevoir\n- Tester"} />,
    );
    const region = screen.getByRole("region", { name: "Description" });
    expect(within(region).getByRole("heading", { name: "MISSIONS" })).toBeVisible();
    expect(within(region).getByRole("list")).toBeVisible();
    expect(within(region).getAllByRole("listitem")).toHaveLength(2);
  });

  it("affiche le pseudo-HTML comme texte inerte", () => {
    const { container } = render(
      <JobDescription description={'<img src="x" onerror="alert(1)">'} />,
    );
    expect(screen.getByText('<img src="x" onerror="alert(1)">')).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });

  it("ne rend rien pour une description vide", () => {
    const { container } = render(<JobDescription description="   " />);
    expect(container).toBeEmptyDOMElement();
  });
});
