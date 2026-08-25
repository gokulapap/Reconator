import { afterEach, describe, expect, it, vi } from "vitest";

import { api, apiKeyStore } from "@/lib/api";

describe("API client", () => {
  afterEach(() => apiKeyStore.clear());

  it("normalizes FastAPI validation errors into actionable messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: [{ loc: ["body", "authorization_confirmed"], msg: "must be true" }],
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      api.createTarget({ url: "example.com", authorization_confirmed: false }),
    ).rejects.toThrow("authorization_confirmed: must be true");
  });

  it("adds the deployment key without exposing it in the request URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ name: "Reconator", version: "3", env: "test", auth_required: true, notifications: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    apiKeyStore.set("deployment-test-key");

    await api.systemInfo();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain("deployment-test-key");
    expect(init.headers).toMatchObject({ "X-API-Key": "deployment-test-key" });
  });
});
