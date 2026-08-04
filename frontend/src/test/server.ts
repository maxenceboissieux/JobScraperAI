import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer(
  http.get("http://localhost:3000/api/jobs", () =>
    HttpResponse.json({ items: [], total: 0, limit: 24, offset: 0 }),
  ),
);
