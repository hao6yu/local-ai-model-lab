import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExperimentalBadge } from "./ExperimentalBadge";

describe("ExperimentalBadge", () => {
  it("renders when visible", () => {
    render(<ExperimentalBadge visible />);
    expect(screen.getByTestId("experimental-badge")).toHaveTextContent("experimental");
  });

  it("renders nothing when hidden", () => {
    render(<ExperimentalBadge visible={false} />);
    expect(screen.queryByTestId("experimental-badge")).not.toBeInTheDocument();
  });
});
