import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HealthResponse, RuntimeResponse } from "../types/health";
import { HomePage } from "./HomePage";

const reachableHealth: HealthResponse = {
  portal: "ok",
  model: { state: "reachable", detail: null },
};

const experimentalRuntime: RuntimeResponse = {
  model_id: "qwen3.8-27b",
  profile_label: "community uncensored Qwen3.8-27B NVFP4 + optimized DSpark",
  context_window: 131072,
  experimental: true,
};

const officialRuntime: RuntimeResponse = {
  model_id: "qwen3.8-27b",
  profile_label: "official Qwen3.8-27B NVFP4 + optimized DSpark",
  context_window: 131072,
  experimental: false,
};

interface MockApisOptions {
  health?: HealthResponse;
  runtime?: RuntimeResponse;
  fail?: boolean;
  neverResolve?: boolean;
}

function mockApis(options: MockApisOptions) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (options.neverResolve) {
        await new Promise(() => {});
        return new Response("{}");
      }
      if (options.fail) {
        throw new Error("network failure");
      }
      const path = String(input);
      const payload = path.endsWith("/api/health") ? options.health : options.runtime;
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HomePage health states", () => {
  it("shows a healthy portal with a reachable model and experimental badge", async () => {
    mockApis({ health: reachableHealth, runtime: experimentalRuntime });
    render(<HomePage />);

    expect(await screen.findByText("Portal: healthy")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /upstream model/i })).toHaveTextContent("reachable");
    expect(screen.getByText("qwen3.8-27b")).toBeInTheDocument();
    expect(
      screen.getByText("community uncensored Qwen3.8-27B NVFP4 + optimized DSpark"),
    ).toBeInTheDocument();
    expect(screen.getByText(/131[,]072 tokens/)).toBeInTheDocument();
    expect(screen.getByTestId("experimental-badge")).toBeInTheDocument();
  });

  it("distinguishes a healthy portal from an unavailable model endpoint", async () => {
    mockApis({
      health: {
        portal: "ok",
        model: { state: "unavailable", detail: "could not connect to model endpoint" },
      },
      runtime: officialRuntime,
    });
    render(<HomePage />);

    expect(await screen.findByText("Portal: healthy")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /upstream model/i })).toHaveTextContent("unavailable");
    expect(screen.getByText("could not connect to model endpoint")).toBeInTheDocument();
    expect(screen.queryByTestId("experimental-badge")).not.toBeInTheDocument();
  });

  it("flags the experimental badge only for experimental profiles", async () => {
    mockApis({ health: reachableHealth, runtime: officialRuntime });
    render(<HomePage />);

    expect(await screen.findByText("official Qwen3.8-27B NVFP4 + optimized DSpark"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("experimental-badge")).not.toBeInTheDocument();
  });

  it("shows a loading state before the backend responds", () => {
    mockApis({ neverResolve: true });
    render(<HomePage />);

    expect(screen.getByTestId("portal-status")).toHaveTextContent("Checking portal health");
  });

  it("shows an error state when the backend is unreachable", async () => {
    mockApis({ fail: true });
    render(<HomePage />);

    expect(await screen.findByText(/portal unavailable/i)).toHaveTextContent("network failure");
  });
});
