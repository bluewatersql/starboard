/**
 * React Query provider configuration.
 *
 * Configures QueryClient with retry policies, cache settings,
 * and dev tools for API state management.
 */

"use client";

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";

/**
 * Create QueryClient with custom configuration.
 */
const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        // Retry configuration
        retry: (failureCount, error) => {
          // Don't retry on 4xx errors (client errors)
          if (error instanceof Error && error.message.includes("HTTP 4")) {
            return false;
          }
          // Retry up to 2 times for other errors
          return failureCount < 2;
        },
        retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),

        // Cache configuration
        staleTime: 1000 * 60 * 5, // 5 minutes
        gcTime: 1000 * 60 * 30, // 30 minutes (formerly cacheTime)

        // Refetch configuration
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        refetchOnMount: true,
      },
      mutations: {
        // Retry mutations once on network error
        retry: (failureCount, error) => {
          if (error instanceof Error && error.message.includes("Network")) {
            return failureCount < 1;
          }
          return false;
        },
      },
    },
  });

let browserQueryClient: QueryClient | undefined = undefined;

/**
 * Get QueryClient (singleton on client, new instance on server).
 */
function getQueryClient() {
  if (typeof window === "undefined") {
    // Server: always create new QueryClient
    return createQueryClient();
  } else {
    // Browser: reuse QueryClient
    if (!browserQueryClient) {
      browserQueryClient = createQueryClient();
    }
    return browserQueryClient;
  }
}

interface QueryProviderProps {
  children: React.ReactNode;
}

/**
 * Query provider component.
 *
 * Wraps the app with React Query provider and dev tools.
 *
 * @param props - Component props
 * @returns Query provider component
 *
 * @example
 * ```tsx
 * <QueryProvider>
 *   <App />
 * </QueryProvider>
 * ```
 */
export function QueryProvider({ children }: QueryProviderProps) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}

