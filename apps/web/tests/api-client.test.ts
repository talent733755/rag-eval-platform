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

  it("lists project documents with encoded filters", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ items: [], next_cursor: null, summary: { total: 0 } }), { status: 200 }),
    );
    const client = createApiClient({ baseUrl: "https://api.example.test", fetchImpl });

    await client.listDocuments("project/one", { query: { q: "合同 草案", parse_status: "failed" } });

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.example.test/api/projects/project%2Fone/documents?q=%E5%90%88%E5%90%8C+%E8%8D%89%E6%A1%88&parse_status=failed",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("uploads a bounded multipart batch with an idempotency key", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ items: [] }), { status: 207 }),
    );
    const client = createApiClient({ baseUrl: "https://api.example.test", fetchImpl });
    const file = new File(["内容"], "说明.md", { type: "text/markdown" });

    await client.uploadDocuments("project-id", [file], { idempotencyKey: "batch-key" });

    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe("https://api.example.test/api/projects/project-id/documents/batch-upload");
    expect(init).toEqual(expect.objectContaining({ method: "POST" }));
    expect(init?.headers).toEqual(expect.objectContaining({ "Idempotency-Key": "batch-key" }));
    expect(init?.body).toBeInstanceOf(FormData);
    expect(Array.from((init?.body as FormData).getAll("files"))).toHaveLength(1);
  });

  it("creates an adapter without sending credential material", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ id: "adapter-1", name: "RAG", kind: "http" }), { status: 201 }),
    );
    const client = createApiClient({ baseUrl: "https://api.example.test", fetchImpl });

    await client.createAdapter("project-id", {
      name: "RAG",
      kind: "http",
      endpoint: "https://adapter.example.test",
      credential_ref: "RAG_TOKEN",
      adapter_version: "adapter-v1",
      trace_level: "minimal",
      timeout_seconds: 30,
      retry_count: 0,
      enabled: false,
    });

    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init?.body).toContain("RAG_TOKEN");
    expect(init?.body).not.toContain("secret-value");
  });
});
