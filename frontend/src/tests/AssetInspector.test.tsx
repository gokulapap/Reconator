import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AssetInspector } from "@/components/AssetInspector";
import type { Asset, AssetIntelligence } from "@/lib/api";

const now = "2026-08-25T00:00:00Z";
const asset = (id: number, kind: string, value: string): Asset => ({
  id,
  kind,
  value,
  canonical_value: value,
  attributes: {},
  priority_score: 50,
  first_seen_at: now,
  last_seen_at: now,
  last_changed_at: now,
  active: true,
});

describe("AssetInspector", () => {
  it("shows provenance bounds and supports relationship pivots", () => {
    const onSelectRelated = vi.fn();
    const intelligence: AssetIntelligence = {
      asset: asset(1, "domain", "example.com"),
      observations: [
        {
          id: 10,
          target_id: 5,
          asset_id: 1,
          task_id: 3,
          source_module: "toolbox.subfinder",
          source_name: "crtsh",
          confidence: 0.9,
          evidence: { source: "fixture" },
          snapshot: {},
          first_observed_at: now,
          last_observed_at: now,
          observation_count: 2,
        },
      ],
      relationships: [
        {
          relationship: {
            id: 12,
            source_asset_id: 1,
            target_asset_id: 2,
            relationship_type: "has_subdomain",
            attributes: {},
            confidence: 0.9,
            first_seen_at: now,
            last_seen_at: now,
          },
          direction: "outgoing",
          related_asset: asset(2, "domain", "api.example.com"),
        },
      ],
      observations_truncated: true,
      relationships_truncated: true,
    };

    render(
      <AssetInspector
        intelligence={intelligence}
        loading={false}
        onSelectRelated={onSelectRelated}
      />,
    );

    expect(screen.getByText("toolbox.subfinder")).toBeInTheDocument();
    expect(screen.getByText(/Only the newest provenance/)).toBeInTheDocument();
    expect(screen.getByText(/Only a bounded relationship/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("api.example.com"));
    expect(onSelectRelated).toHaveBeenCalledWith(2);
  });
});
