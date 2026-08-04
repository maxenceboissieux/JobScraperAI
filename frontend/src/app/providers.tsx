import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { useState, type PropsWithChildren } from "react";

type AppProvidersProps = PropsWithChildren<{
  queryClient?: QueryClient;
}>;

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function AppProviders({ children, queryClient }: AppProvidersProps) {
  const [appQueryClient] = useState(() => queryClient ?? createAppQueryClient());
  return (
    <BrowserRouter>
      <QueryClientProvider client={appQueryClient}>{children}</QueryClientProvider>
    </BrowserRouter>
  );
}
