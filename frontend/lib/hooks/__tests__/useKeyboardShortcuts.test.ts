import { renderHook } from "@testing-library/react";
import { useKeyboardShortcuts } from "../useKeyboardShortcuts";

// Mock react-hotkeys-hook
jest.mock("react-hotkeys-hook", () => ({
  useHotkeys: jest.fn(),
}));

describe("useKeyboardShortcuts", () => {
  it("registers without throwing", () => {
    const callbacks = {
      onSearch: jest.fn(),
      onNewChat: jest.fn(),
      onSendMessage: jest.fn(),
      onCancel: jest.fn(),
      onShowHelp: jest.fn(),
    };

    expect(() => {
      renderHook(() => useKeyboardShortcuts(callbacks));
    }).not.toThrow();
  });

  it("accepts empty callbacks", () => {
    expect(() => {
      renderHook(() => useKeyboardShortcuts({}));
    }).not.toThrow();
  });
});
