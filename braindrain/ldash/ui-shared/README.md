# LivingDash UI Shared

Shared frontend contract layer for LivingDash variants.

## Contents

- `src/contract.ts`: canonical TypeScript API contracts for sidecar `2.1`.
- `src/client.ts`: cookie-authenticated fetch client for `/api/*`.
- `src/hooks.ts`: React Query hooks and query keys.
- `src/tokens.ts` + `src/tokens.css`: shared design tokens.

This package is read-only for variant implementations (`ui-nexus`, `ui-pilot`, `ui-grid`).
