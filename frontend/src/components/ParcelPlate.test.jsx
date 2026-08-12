import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import ParcelPlate from "./ParcelPlate.jsx";

// UI_SPEC.md §2.3: all randomness is seeded from the listing ID, so a
// given lot renders identically in Consider and Compare -- this is not
// cosmetic, inconsistent rendering would be an uncontrolled variable
// inside the pairwise training data. SVG <defs> IDs are namespaced per
// listing so two plates can render side by side in Compare without
// colliding.

const BASE_LISTING = {
  id: "L-1042",
  address: "418 Wrenwood Ct",
  parcelCanopy: 74,
  neighborhoodCanopy: 68,
  protectedRatio: 0.41,
  edges: { n: "marsh", e: "buildable", s: "road", w: "buildable" },
};

describe("ParcelPlate", () => {
  it("renders identical SVG for the same listing id", () => {
    const { container: a } = render(<ParcelPlate listing={BASE_LISTING} />);
    const { container: b } = render(<ParcelPlate listing={{ ...BASE_LISTING }} />);
    expect(a.querySelector("svg").outerHTML).toBe(b.querySelector("svg").outerHTML);
  });

  it("renders different output for a different listing id", () => {
    const { container: a } = render(<ParcelPlate listing={BASE_LISTING} />);
    const { container: b } = render(<ParcelPlate listing={{ ...BASE_LISTING, id: "L-9999" }} />);
    expect(a.querySelector("svg").outerHTML).not.toBe(b.querySelector("svg").outerHTML);
  });

  it("namespaces defs ids per listing so two plates don't collide", () => {
    const { container: a } = render(<ParcelPlate listing={BASE_LISTING} />);
    const { container: b } = render(<ParcelPlate listing={{ ...BASE_LISTING, id: "L-9999" }} />);

    const idsOf = (container) =>
      [...container.querySelectorAll("[id]")].map((el) => el.id);

    const idsA = idsOf(a);
    const idsB = idsOf(b);
    expect(idsA.length).toBeGreaterThan(0);
    expect(idsA.some((id) => idsB.includes(id))).toBe(false);
    expect(idsA.every((id) => id.startsWith("pL1042"))).toBe(true);
  });

  it("sanitizes non-alphanumeric characters out of the listing id for the namespace", () => {
    const { container } = render(<ParcelPlate listing={BASE_LISTING} />);
    const hatch = container.querySelector("pattern[id]");
    expect(hatch.id).toBe("pL1042-hatch");
  });
});
