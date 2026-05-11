## 2025-05-11 - Refresh Mechanism in Fallback States
**Learning:** When a UI presents a fallback or error state that requires the user to perform an out-of-band action (like a manual build command), providing an explicit "refresh" or "check" mechanism is critical. It closes the interaction loop and provides a clear next step once the user completes the external task, without requiring a manual browser refresh.
**Action:** Always include a re-check or refresh button in fallback/empty states that depend on external environment changes.

## 2025-05-11 - Robust DOM Selection in JavaScript
**Learning:** Using `document.getElementById()` or unique IDs for critical interactive elements (like copy-to-clipboard targets) is more robust than relative DOM navigation (e.g., `nextElementSibling`). This prevents regressions when the visual layout or HTML structure is adjusted.
**Action:** Prioritize unique IDs for JavaScript targets in UI components to ensure layout changes don't break functionality.
