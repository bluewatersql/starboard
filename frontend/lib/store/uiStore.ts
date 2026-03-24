/**
 * Zustand store for UI state management.
 *
 * Manages UI-specific state like sidebar visibility,
 * modals, notifications, and loading indicators.
 */

import { create } from "zustand";

interface UIState {
  // Sidebar
  sidebarOpen: boolean;
  sidebarWidth: number;

  // Modals
  settingsModalOpen: boolean;
  deleteConfirmModalOpen: boolean;
  deleteTarget: string | null;

  // Notifications
  notifications: Notification[];

  // Loading indicators
  globalLoading: boolean;

  // Actions
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setSidebarWidth: (width: number) => void;
  openSettingsModal: () => void;
  closeSettingsModal: () => void;
  openDeleteConfirm: (target: string) => void;
  closeDeleteConfirm: () => void;
  addNotification: (notification: Omit<Notification, "id">) => void;
  removeNotification: (id: string) => void;
  clearNotifications: () => void;
  setGlobalLoading: (loading: boolean) => void;
  reset: () => void;
}

interface Notification {
  id: string;
  message: string;
  type: "success" | "error" | "warning" | "info";
  duration?: number;
}

export const SIDEBAR_WIDTH_OPEN = 280;
export const SIDEBAR_WIDTH_COLLAPSED = 60;

const initialState = {
  sidebarOpen: true,
  sidebarWidth: SIDEBAR_WIDTH_OPEN,
  settingsModalOpen: false,
  deleteConfirmModalOpen: false,
  deleteTarget: null,
  notifications: [],
  globalLoading: false,
};

/**
 * UI store.
 *
 * Manages application UI state including sidebar, modals,
 * and notifications.
 *
 * @example
 * ```tsx
 * const { sidebarOpen, toggleSidebar, addNotification } = useUIStore();
 *
 * // Toggle sidebar
 * toggleSidebar();
 *
 * // Show notification
 * addNotification({
 *   message: "Message sent successfully",
 *   type: "success",
 *   duration: 3000
 * });
 * ```
 */
export const useUIStore = create<UIState>((set) => ({
  ...initialState,

  setSidebarOpen: (open) => set({ 
    sidebarOpen: open,
    sidebarWidth: open ? SIDEBAR_WIDTH_OPEN : SIDEBAR_WIDTH_COLLAPSED,
  }),

  toggleSidebar: () => set((state) => ({ 
    sidebarOpen: !state.sidebarOpen,
    sidebarWidth: !state.sidebarOpen ? SIDEBAR_WIDTH_OPEN : SIDEBAR_WIDTH_COLLAPSED,
  })),

  setSidebarWidth: (width) => set({ sidebarWidth: width }),

  openSettingsModal: () => set({ settingsModalOpen: true }),

  closeSettingsModal: () => set({ settingsModalOpen: false }),

  openDeleteConfirm: (target) =>
    set({ deleteConfirmModalOpen: true, deleteTarget: target }),

  closeDeleteConfirm: () =>
    set({ deleteConfirmModalOpen: false, deleteTarget: null }),

  addNotification: (notification) =>
    set((state) => ({
      notifications: [
        ...state.notifications,
        {
          ...notification,
          id: `notification-${Date.now()}-${Math.random()}`,
        },
      ],
    })),

  removeNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),

  clearNotifications: () => set({ notifications: [] }),

  setGlobalLoading: (loading) => set({ globalLoading: loading }),

  reset: () => set(initialState),
}));

/**
 * Export notification type for external use.
 */
export type { Notification };

