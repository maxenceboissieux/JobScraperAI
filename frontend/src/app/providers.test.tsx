import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it } from "vitest";

import { AppProviders } from "./providers";

type CaptureProps = {
  onClient: (client: QueryClient) => void;
};

function CaptureClient({ onClient }: CaptureProps) {
  const client = useQueryClient();
  useEffect(() => {
    onClient(client);
  }, [client, onClient]);
  return null;
}

describe("AppProviders", () => {
  it("isole le cache entre deux montages tout en partageant le client d’un montage", async () => {
    const firstClients: QueryClient[] = [];
    const rememberFirst = (client: QueryClient) => {
      firstClients.push(client);
      client.setQueryData(["recherches"], ["cache du premier montage"]);
    };
    const first = render(
      <AppProviders>
        <CaptureClient onClient={rememberFirst} />
        <CaptureClient onClient={rememberFirst} />
      </AppProviders>,
    );
    await waitFor(() => expect(firstClients).toHaveLength(2));
    expect(firstClients[0]).toBe(firstClients[1]);
    first.unmount();

    let secondClient: QueryClient | undefined;
    const second = render(
      <AppProviders>
        <CaptureClient
          onClient={(client) => {
            secondClient = client;
          }}
        />
      </AppProviders>,
    );
    await waitFor(() => expect(secondClient).toBeDefined());

    expect(secondClient).not.toBe(firstClients[0]);
    expect(secondClient?.getQueryData(["recherches"])).toBeUndefined();
    expect(secondClient?.getDefaultOptions().queries).toMatchObject({
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    });
    second.unmount();
  });
});
