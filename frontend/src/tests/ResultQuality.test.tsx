import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultQuality, inspectTaskQuality } from "@/components/ResultQuality";
import type { ReconTask, ScanKnowledgeSummary, TaskList } from "@/lib/api";

const now = "2026-08-25T00:00:00Z";

function task(id: number, output_summary: Record<string, unknown>): ReconTask {
  return {
    id,
    target_id: 9,
    input_asset_id: null,
    parent_task_id: null,
    cache_hit_task_id: null,
    module_name: "toolbox.subfinder",
    module_version: "1",
    capability: "domain.subdomain_discovery",
    scope_basis: "direct",
    status: "completed",
    priority: 50,
    attempts: 1,
    max_attempts: 3,
    timeout_seconds: 120,
    available_at: now,
    started_at: now,
    completed_at: now,
    error_code: null,
    error_detail: null,
    output_summary,
  };
}

const taskSample: TaskList = {
  items: [
    task(1, {
      pagination_truncated: true,
      raw_output_truncated: true,
      validation_error_count: 3,
    }),
    task(2, {}),
  ],
  total: 600,
  page: 1,
  page_size: 500,
};

const summary: ScanKnowledgeSummary = {
  assets_total: 42,
  relationships_total: 30,
  observations_total: 75,
  tasks_total: 600,
  assets_by_kind: { domain: 42 },
  relationships_by_type: { has_subdomain: 30 },
  tasks_by_status: { completed: 3, failed: 1 },
  observations_by_module: { "toolbox.subfinder": 75 },
  source_yield: [
    {
      source_module: "toolbox.subfinder",
      source_name: "crtsh",
      observations: 50,
      distinct_assets: 38,
      exclusive_assets: 17,
      average_confidence: 0.91,
      last_observed_at: now,
    },
  ],
  module_health: [
    {
      module_name: "toolbox.subfinder",
      capability: "domain.subdomain_discovery",
      tasks_total: 4,
      tasks_by_status: { completed: 3, failed: 1 },
      failure_rate: 0.25,
    },
  ],
};

describe("ResultQuality", () => {
  it("derives bounded discovery, evidence, and validation signals", () => {
    expect(inspectTaskQuality(taskSample)).toEqual({
      sampled: 2,
      total: 600,
      discoveryBoundTasks: 1,
      evidenceBoundTasks: 1,
      rejectedEmissions: 3,
    });
  });

  it("shows provider yield, aggregate module health, and explicit sample limits", () => {
    render(
      <ResultQuality
        summary={summary}
        taskSample={taskSample}
        loading={false}
      />,
    );

    expect(screen.getByText("crtsh")).toBeInTheDocument();
    expect(screen.getByText("via toolbox.subfinder")).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("degraded")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getAllByText("1 task(s)")[0].closest("li")).toHaveTextContent(
      /bounded pagination/,
    );
    expect(screen.getByText("3 malformed emission(s)").closest("li")).toHaveTextContent(
      /Normalization rejected/,
    );
    expect(screen.getByText(/first 2 of 600 tasks/)).toBeInTheDocument();
  });

  it("prefers exact server completeness and shows zero yield, latency, and error groups", () => {
    render(
      <ResultQuality
        summary={{
          ...summary,
          completeness: {
            tasks_inspected: 600,
            tasks_total: 600,
            truncated_tasks: 3,
            discovery_truncated_tasks: 2,
            evidence_truncated_tasks: 3,
            validation_rejections: 7,
          },
          source_yield: [
            ...(summary.source_yield ?? []),
            {
              source_module: "builtin.empty-provider",
              source_name: null,
              observations: 0,
              distinct_assets: 0,
              exclusive_assets: 0,
              average_confidence: 0,
              last_observed_at: null,
            },
          ],
          module_health: [
            {
              ...(summary.module_health?.[0] as NonNullable<ScanKnowledgeSummary["module_health"]>[number]),
              error_codes: { provider_timeout: 2 },
              duration_sample_size: 40,
              duration_total: 50,
              average_duration_seconds: 1.5,
              p95_duration_seconds: 4,
            },
          ],
        }}
        taskSample={taskSample}
        loading={false}
      />,
    );

    expect(screen.getByText("600/600 tasks aggregated")).toBeInTheDocument();
    expect(screen.getByText(/Exact scan totals/)).toBeInTheDocument();
    expect(screen.getByText("2 task(s)").closest("li")).toHaveTextContent(
      /bounded pagination/,
    );
    expect(screen.getByText("7 malformed emission(s)")).toBeInTheDocument();
    expect(screen.getByText(/3 unique task\(s\)/)).toBeInTheDocument();
    expect(screen.getByText("completed module · zero persisted yield")).toBeInTheDocument();
    expect(screen.getByText("1.5s / 4.0s")).toBeInTheDocument();
    expect(screen.getByText("40/50 timings")).toBeInTheDocument();
    expect(screen.getByText("provider_timeout ×2")).toBeInTheDocument();
    expect(screen.queryByText(/first 2 of 600 tasks/)).not.toBeInTheDocument();
  });

  it("distinguishes a live empty scan from missing result quality", () => {
    render(
      <ResultQuality
        summary={{ ...summary, observations_total: 0, source_yield: [], module_health: [] }}
        taskSample={{ items: [], total: 0, page: 1, page_size: 500 }}
        loading={false}
        scanIsLive
      />,
    );

    expect(screen.getByText(/No provenance has been persisted yet/)).toBeInTheDocument();
    expect(screen.getByText(/No module tasks have started yet/)).toBeInTheDocument();
    expect(screen.getByText("live · still changing")).toBeInTheDocument();
  });
});
