import { afterEach, describe, expect, it, vi } from "vitest";

import { createApiClient } from "../src/lib/api/client";

describe("API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists projects from the FastAPI contract with the configured base URL", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: "11111111-1111-4111-8111-111111111111",
            organization_id: "22222222-2222-4222-8222-222222222222",
            name: "平台项目",
            slug: "platform",
            description: null,
            archived_at: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ]),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const client = createApiClient({ baseUrl: "https://api.example.test/", fetchImpl });
    const signal = new AbortController().signal;

    const projects = await client.listProjects({ signal });

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.example.test/api/projects",
      expect.objectContaining({ method: "GET", signal }),
    );
    expect(projects[0]?.slug).toBe("platform");
  });

  it("turns the API error envelope into a typed error", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "permission_denied", message: "拒绝访问" } }), {
        status: 403,
        headers: { "content-type": "application/json" },
      }),
    );
    const client = createApiClient({ baseUrl: "http://localhost:8000", fetchImpl });

    await expect(client.listProjects()).rejects.toMatchObject({
      status: 403,
      code: "permission_denied",
      message: "拒绝访问",
    });
  });
});
