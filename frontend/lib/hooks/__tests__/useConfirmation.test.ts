/**
 * useConfirmation hook tests.
 */

import { renderHook, act } from "@testing-library/react";
import { useConfirmation } from "../useConfirmation";

describe("useConfirmation", () => {
  it("starts with dialog closed", () => {
    const { result } = renderHook(() => useConfirmation());
    expect(result.current.dialogProps.open).toBe(false);
  });

  it("opens dialog when confirm() is called", async () => {
    const { result } = renderHook(() => useConfirmation());

    act(() => {
      result.current.confirm({
        title: "Delete?",
        message: "This cannot be undone.",
      });
    });

    expect(result.current.dialogProps.open).toBe(true);
    expect(result.current.dialogProps.title).toBe("Delete?");
    expect(result.current.dialogProps.message).toBe("This cannot be undone.");
  });

  it("resolves true when onConfirm is called", async () => {
    const { result } = renderHook(() => useConfirmation());
    let resolved: boolean | undefined;

    act(() => {
      result.current.confirm({ title: "Test", message: "Confirm?" }).then((v) => {
        resolved = v;
      });
    });

    expect(result.current.dialogProps.open).toBe(true);

    act(() => {
      result.current.dialogProps.onConfirm();
    });

    // Wait for promise resolution
    await act(async () => {
      await Promise.resolve();
    });

    expect(resolved).toBe(true);
    expect(result.current.dialogProps.open).toBe(false);
  });

  it("resolves false when onCancel is called", async () => {
    const { result } = renderHook(() => useConfirmation());
    let resolved: boolean | undefined;

    act(() => {
      result.current.confirm({ title: "Test", message: "Confirm?" }).then((v) => {
        resolved = v;
      });
    });

    act(() => {
      result.current.dialogProps.onCancel();
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(resolved).toBe(false);
    expect(result.current.dialogProps.open).toBe(false);
  });

  it("passes through optional props (confirmLabel, cancelLabel, severity)", async () => {
    const { result } = renderHook(() => useConfirmation());

    act(() => {
      result.current.confirm({
        title: "Title",
        message: "Message",
        confirmLabel: "Yes, delete",
        cancelLabel: "No, keep",
        severity: "error",
      });
    });

    expect(result.current.dialogProps.confirmLabel).toBe("Yes, delete");
    expect(result.current.dialogProps.cancelLabel).toBe("No, keep");
    expect(result.current.dialogProps.severity).toBe("error");
  });

  it("closes dialog after confirmation and allows re-opening", async () => {
    const { result } = renderHook(() => useConfirmation());

    // First confirmation
    act(() => {
      result.current.confirm({ title: "First", message: "First?" });
    });
    act(() => {
      result.current.dialogProps.onConfirm();
    });
    await act(async () => { await Promise.resolve(); });

    expect(result.current.dialogProps.open).toBe(false);

    // Second confirmation
    act(() => {
      result.current.confirm({ title: "Second", message: "Second?" });
    });
    expect(result.current.dialogProps.open).toBe(true);
    expect(result.current.dialogProps.title).toBe("Second");
  });
});
