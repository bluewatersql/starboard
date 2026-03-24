/**
 * Authentication hook for getting current user context.
 *
 * Provides access to authenticated user information and auth state.
 */

import { useQuery } from "@tanstack/react-query";

export interface UserContext {
  user_id: string;
  username?: string;
  display_name?: string;
}

/**
 * Hook to get current user context.
 *
 * Fetches user information from the /me endpoint.
 *
 * @returns User context and loading state
 *
 * @example
 * ```tsx
 * function UserProfile() {
 *   const { user, isLoading } = useAuth();
 *   
 *   if (isLoading) return <Spinner />;
 *   if (!user) return <div>Not authenticated</div>;
 *   
 *   return <div>Welcome, {user.username}!</div>;
 * }
 * ```
 */
export function useAuth() {
  // Fetch user info from /me endpoint
  const { data: user, isLoading } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: async () => {
      const response = await fetch("/api/chat/me", {
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error("Failed to fetch user info");
      }
      return response.json() as Promise<UserContext>;
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
    retry: 1,
  });

  return {
    user: user || null,
    isLoading,
    isAuthenticated: !!user,
  };
}

