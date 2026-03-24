/**
 * DomainModelSelector component.
 *
 * Allows users to configure different models for specific domains
 * in the multi-agent system.
 */

"use client";

import React from "react";
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Chip,
  IconButton,
  Paper,
  Stack,
  TextField,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { SUPPORTED_MODELS, type SupportedModel } from "@/lib/types/api";

interface DomainModelSelectorProps {
  domainModels: Record<string, SupportedModel>;
  domainTemperatures: Record<string, number>;
  onSetDomainModel: (domain: string, model: SupportedModel | null) => void;
  onSetDomainTemperature: (domain: string, temperature: number | null) => void;
  defaultModel: SupportedModel;
  defaultTemperature: number;
  serverDomainOverrides?: Record<string, string>;  // From backend env vars
  serverTemperatureOverrides?: Record<string, number>;  // From backend env vars
}

// Available domains for configuration
const DOMAINS = [
  { key: "query", label: "Query Optimization" },
  { key: "job", label: "Job Analysis" },
  { key: "table", label: "Table & Lineage" },
  { key: "cluster", label: "Cluster Resources" },
  { key: "warehouse", label: "Warehouse Analysis" },
  { key: "diagnostic", label: "Diagnostics & Troubleshooting" },
] as const;

/**
 * Domain model selector component.
 *
 * Displays a list of domains and allows users to configure
 * a specific model and temperature for each domain, overriding the defaults.
 *
 * @param props - Component props
 * @returns Domain model selector component
 *
 * @example
 * ```tsx
 * <DomainModelSelector
 *   domainModels={domainModels}
 *   domainTemperatures={domainTemperatures}
 *   onSetDomainModel={setDomainModel}
 *   onSetDomainTemperature={setDomainTemperature}
 *   defaultModel="databricks-claude-sonnet-4-5"
 *   defaultTemperature={0.4}
 * />
 * ```
 */
export function DomainModelSelector({
  domainModels,
  domainTemperatures,
  onSetDomainModel,
  onSetDomainTemperature,
  defaultModel,
  defaultTemperature,
  serverDomainOverrides = {},
  serverTemperatureOverrides = {},
}: DomainModelSelectorProps) {
  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Domain-Specific Models & Temperatures
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Override the default model and temperature for specific domains. Server defaults
        are from environment configuration (DOMAIN_MODEL_OVERRIDES and
        DOMAIN_TEMPERATURE_OVERRIDES).
      </Typography>

      <Stack spacing={2}>
        {DOMAINS.map(({ key, label }) => {
          const domainModel = domainModels[key];
          const domainTemperature = domainTemperatures[key];
          const serverModelDefault = serverDomainOverrides[key];
          const serverTemperatureDefault = serverTemperatureOverrides[key];
          const effectiveModelDefault = serverModelDefault || defaultModel;
          const effectiveTemperatureDefault =
            serverTemperatureDefault ?? defaultTemperature;
          const isUsingDefaultModel = !domainModel;
          const isUsingDefaultTemperature = domainTemperature === undefined;

          return (
            <Paper key={key} variant="outlined" sx={{ p: 2 }}>
              <Box>
                <Box sx={{ display: "flex", alignItems: "center", gap: 2, mb: 1 }}>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="subtitle2" gutterBottom>
                      {label}
                    </Typography>
                    <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
                      {isUsingDefaultModel && (
                        <Chip
                          label={
                            serverModelDefault
                              ? `Server Model: ${serverModelDefault}`
                              : `Default Model: ${defaultModel}`
                          }
                          size="small"
                          variant="outlined"
                          color={serverModelDefault ? "primary" : "default"}
                        />
                      )}
                      {isUsingDefaultTemperature && (
                        <Chip
                          label={
                            serverTemperatureDefault !== undefined
                              ? `Server Temp: ${serverTemperatureDefault}`
                              : `Default Temp: ${defaultTemperature}`
                          }
                          size="small"
                          variant="outlined"
                          color={
                            serverTemperatureDefault !== undefined
                              ? "primary"
                              : "default"
                          }
                        />
                      )}
                    </Box>
                  </Box>
                </Box>

                <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <FormControl sx={{ minWidth: 300 }} size="small">
                    <InputLabel id={`domain-model-${key}-label`}>
                      Model
                    </InputLabel>
                    <Select
                      labelId={`domain-model-${key}-label`}
                      value={domainModel || effectiveModelDefault}
                      label="Model"
                      onChange={(e) => {
                        const value = e.target.value as string;
                        // If selecting the effective default, clear the override
                        if (value === effectiveModelDefault) {
                          onSetDomainModel(key, null);
                        } else {
                          onSetDomainModel(key, value as SupportedModel);
                        }
                      }}
                    >
                      {SUPPORTED_MODELS.map((m) => (
                        <MenuItem key={m} value={m}>
                          {m}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>

                  <TextField
                    label="Temperature"
                    type="number"
                    size="small"
                    value={
                      domainTemperature !== undefined
                        ? domainTemperature
                        : effectiveTemperatureDefault
                    }
                    onChange={(e) => {
                      const value = parseFloat(e.target.value);
                      if (!isNaN(value)) {
                        // If setting to effective default, clear the override
                        if (value === effectiveTemperatureDefault) {
                          onSetDomainTemperature(key, null);
                        } else {
                          onSetDomainTemperature(key, value);
                        }
                      }
                    }}
                    inputProps={{
                      step: 0.1,
                      min: 0,
                      max: 2,
                    }}
                    sx={{ width: 150 }}
                  />

                  {(domainModel || domainTemperature !== undefined) && (
                    <IconButton
                      size="small"
                      onClick={() => {
                        onSetDomainModel(key, null);
                        onSetDomainTemperature(key, null);
                      }}
                      aria-label={`Clear ${label} overrides`}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  )}
                </Box>
              </Box>
            </Paper>
          );
        })}
      </Stack>
    </Box>
  );
}

