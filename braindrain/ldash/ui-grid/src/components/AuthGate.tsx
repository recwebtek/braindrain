import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { defaultClient, type AuthSession, type LoginPayload } from "@livingdash/ui-shared";
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
      <main className="grid min-h-screen place-items-center bg-[var(--ld-bg)] p-4">
        <div className="rounded-md border border-white/10 bg-black/50 px-4 py-3 text-sm text-[var(--ld-text-secondary)]">Checking session...</div>
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
