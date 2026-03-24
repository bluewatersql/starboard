/**
 * Zustand store for conversation configuration management.
 *
 * Manages user-configurable settings for new conversations including
 * model selection, temperature, token limits, and reasoning parameters.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ConversationConfig, SupportedModel, LoggingLevel } from "@/lib/types/api";

interface ConfigState {
  // Configuration values
  model: SupportedModel;
  temperature: number;
  maxTokens: number;
  useMaxModelTokens: boolean;
  budgetEnforced: boolean;
  maxSteps: number;
  loggingLevel: LoggingLevel;
  domainModels: Record<string, SupportedModel>;  // Per-domain model overrides
  domainTemperatures: Record<string, number>;  // Per-domain temperature overrides
  offlineMode: boolean;  // Force OFFLINE mode for diagnostic agent (no API calls)
  
  // Actions
  setModel: (model: SupportedModel) => void;
  setTemperature: (temperature: number) => void;
  setMaxTokens: (maxTokens: number) => void;
  setUseMaxModelTokens: (useMaxModelTokens: boolean) => void;
  setBudgetEnforced: (budgetEnforced: boolean) => void;
  setMaxSteps: (maxSteps: number) => void;
  setLoggingLevel: (loggingLevel: LoggingLevel) => void;
  setDomainModel: (domain: string, model: SupportedModel | null) => void;
  setDomainTemperature: (domain: string, temperature: number | null) => void;
  clearDomainModels: () => void;
  clearDomainTemperatures: () => void;
  setOfflineMode: (offlineMode: boolean) => void;
  
  // Convert to API format
  toConversationConfig: () => ConversationConfig;
  
  // Reset to defaults
  reset: () => void;
}

const defaultState = {
  model: "databricks-claude-sonnet-4-5" as SupportedModel,
  temperature: 0.4,
  maxTokens: 25000,
  useMaxModelTokens: false,
  budgetEnforced: false,
  maxSteps: 20,
  loggingLevel: "INFO" as LoggingLevel,
  domainModels: {} as Record<string, SupportedModel>,
  domainTemperatures: {} as Record<string, number>,
  offlineMode: false,
};

/**
 * Configuration store.
 *
 * Persists user's conversation configuration preferences in localStorage
 * and provides methods to update individual settings.
 *
 * @example
 * ```tsx
 * const { model, setModel, toConversationConfig } = useConfigStore();
 *
 * // Update model
 * setModel("databricks-claude-sonnet-4-5");
 *
 * // Get config for API
 * const config = toConversationConfig();
 * ```
 */
export const useConfigStore = create<ConfigState>()(
  persist(
    (set, get) => ({
      ...defaultState,

      setModel: (model) => set({ model }),

      setTemperature: (temperature) => set({ temperature }),

      setMaxTokens: (maxTokens) => set({ maxTokens }),

      setUseMaxModelTokens: (useMaxModelTokens) => set({ useMaxModelTokens }),

      setBudgetEnforced: (budgetEnforced) => set({ budgetEnforced }),

      setMaxSteps: (maxSteps) => set({ maxSteps }),

      setLoggingLevel: (loggingLevel) => set({ loggingLevel }),

      setDomainModel: (domain, model) =>
        set((state) => {
          const newDomainModels = { ...state.domainModels };
          if (model === null) {
            delete newDomainModels[domain];
          } else {
            newDomainModels[domain] = model;
          }
          return { domainModels: newDomainModels };
        }),

      setDomainTemperature: (domain, temperature) =>
        set((state) => {
          const newDomainTemperatures = { ...state.domainTemperatures };
          if (temperature === null) {
            delete newDomainTemperatures[domain];
          } else {
            newDomainTemperatures[domain] = temperature;
          }
          return { domainTemperatures: newDomainTemperatures };
        }),

      clearDomainModels: () => set({ domainModels: {} }),

      clearDomainTemperatures: () => set({ domainTemperatures: {} }),

      setOfflineMode: (offlineMode) => set({ offlineMode }),

      toConversationConfig: () => {
        const state = get();
        // Build base config
        const config: ConversationConfig = {
          model: state.model,
          temperature: state.temperature,
          max_tokens: state.maxTokens,
          use_max_model_tokens: state.useMaxModelTokens,
          budget_enforced: state.budgetEnforced,
          max_steps: state.maxSteps,
          logging_level: state.loggingLevel,
          streaming: true,
          safe_mode: false,
        };
        
        // Add offline_mode as extended property (not in generated types yet)
        // This will be passed to the backend and used by diagnostic agent
        if (state.offlineMode) {
          (config as Record<string, unknown>)["offline_mode"] = true;
        }
        
        // Add domain model overrides if any are set
        if (Object.keys(state.domainModels).length > 0) {
          config.domain_model_overrides = state.domainModels;
        }
        
        // Add domain temperature overrides if any are set
        if (Object.keys(state.domainTemperatures).length > 0) {
          config.domain_temperature_overrides = state.domainTemperatures;
        }
        
        return config;
      },

      reset: () => set(defaultState),
    }),
    {
      name: "starboard-config-storage",
    }
  )
);

