/**
 * Jest automatic mock for react-hotkeys-hook.
 *
 * The package ships pure ESM which Jest cannot transform.
 * This mock provides no-op stubs so tests that transitively
 * import the hook (via barrel exports) do not crash.
 */

export const useHotkeys = jest.fn();
export const isHotkeyPressed = jest.fn(() => false);
