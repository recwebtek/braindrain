import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { defaultClient } from "@livingdash/ui-shared";
import type { AuthSession, LoginPayload } from "@livingdash/ui-shared";
import { LoginScreen } from "@/components/LoginScreen";

interface AuthGateProps {
  children: ReactNode;
}

async function loadSession() {
  try {
    return await defaultClient.fetchAuthSession();
  } catch {
    return { authenticated: false } satisfies AuthSession;
  }
}

export function AuthGate({ children }: AuthGateProps) {
  const queryClient = useQueryClient();
  const sessionQuery = useQuery({
    queryKey: ["auth", "session"],
    queryFn: loadSession,
    staleTime: 5_000,
  });

  const loginMutation = useMutation({
    mutationFn: (payload: LoginPayload) => defaultClient.login(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "session"] });
      await queryClient.invalidateQueries({ queryKey: ["livingdash"] });
    },
  });

  if (sessionQuery.isLoading) {
    return (
      <main className="nexus-auth-wrap">
        <div className="nexus-loading-pill">Checking secure session...</div>
      </main>
    );
  }

  if (!sessionQuery.data?.authenticated) {
    return (
      <LoginScreen
        busy={loginMutation.isPending}
        error={loginMutation.error instanceof Error ? loginMutation.error.message : null}
        onLogin={async (payload) => {
          await loginMutation.mutateAsync(payload);
        }}
      />
    );
  }

  return <>{children}</>;
}
