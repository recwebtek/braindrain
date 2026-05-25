import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { fetchAuthSession, login, type AuthSession, type LoginPayload } from "@/api";
import { LoginScreen } from "@/components/LoginScreen";
interface AuthGateProps {
  children: ReactNode;
}

async function loadSession() {
  try {
    return await fetchAuthSession();
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
    mutationFn: (payload: LoginPayload) => login(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "session"] });
      await queryClient.invalidateQueries({ queryKey: ["ldash"] });
    },
  });

  if (sessionQuery.isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4 py-8">
        <div className="rounded-[10px] border border-white/10 bg-black/80 px-6 py-4 text-sm text-slate-200 backdrop-blur-md">
          Checking session...
        </div>
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
