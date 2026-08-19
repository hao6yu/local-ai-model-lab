import { useEffect, useState } from "react";
import { getHealth, getRuntime } from "../api/client";
import { ExperimentalBadge } from "../components/ExperimentalBadge";
import type { HealthResponse, RuntimeResponse } from "../types/health";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; health: HealthResponse; runtime: RuntimeResponse };

export function HomePage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    Promise.all([getHealth(), getRuntime()])
      .then(([health, runtime]) => {
        if (!cancelled) {
          setState({ kind: "ready", health, runtime });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Unknown error";
          setState({ kind: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return <p className="status" data-testid="portal-status">Checking portal health…</p>;
  }

  if (state.kind === "error") {
    return (
      <p className="status error" data-testid="portal-status" role="alert">
        Portal unavailable: {state.message}
      </p>
    );
  }

  const { health, runtime } = state;
  const modelState = health.model.state;

  return (
    <main className="page">
      <h1>Local AI Model Lab</h1>
      <p className="status" data-testid="portal-status">
        Portal: healthy
      </p>
      <section className={`model ${modelState}`} aria-label="Upstream model status">
        <h2>
          Upstream model: <span className="state">{modelState}</span>
        </h2>
        {health.model.detail ? <p className="detail">{health.model.detail}</p> : null}
        <dl>
          <div>
            <dt>Model ID</dt>
            <dd>{runtime.model_id ?? "Not configured"}</dd>
          </div>
          <div>
            <dt>Profile label</dt>
            <dd>
              {runtime.profile_label ?? "No profile label set"}
              <ExperimentalBadge visible={runtime.experimental} />
            </dd>
          </div>
          <div>
            <dt>Context window</dt>
            <dd>
              {runtime.context_window !== null
                ? `${runtime.context_window.toLocaleString()} tokens`
                : "Not declared"}
            </dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
