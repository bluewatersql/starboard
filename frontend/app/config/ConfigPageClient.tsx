/**
 * ConfigPageClient — interactive client island for the config page.
 *
 * This component holds all interactive state (Zustand stores, React hooks,
 * router navigation). It is imported by the thin server-component wrapper
 * in page.tsx which provides static layout metadata.
 *
 * Keeping the client boundary here (rather than at page.tsx root) follows
 * the RSC pattern: push "use client" as deep as possible so the static
 * outer shell can be server-rendered.
 */

"use client";

import React from "react";
import {
  Box,
  Container,
  Typography,
  Paper,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Slider,
  TextField,
  FormControlLabel,
  Checkbox,
  Button,
  Divider,
  Stack,
  IconButton,
  AppBar,
  Toolbar,
  SelectChangeEvent,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import SaveIcon from "@mui/icons-material/Save";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import { useRouter } from "next/navigation";
import { useConfigStore } from "@/lib/store/configStore";
import { SUPPORTED_MODELS, LOGGING_LEVELS, SupportedModel, LoggingLevel } from "@/lib/types/api";
import { DomainModelSelector } from "@/components/config";
import { api } from "@/lib/api/client";

export function ConfigPageClient() {
  const router = useRouter();
  const {
    model,
    temperature,
    maxTokens,
    useMaxModelTokens,
    budgetEnforced,
    maxSteps,
    loggingLevel,
    domainModels,
    domainTemperatures,
    setModel,
    setTemperature,
    setMaxTokens,
    setUseMaxModelTokens,
    setBudgetEnforced,
    setMaxSteps,
    setLoggingLevel,
    setDomainModel,
    setDomainTemperature,
    reset,
  } = useConfigStore();

  //const [localMaxTokens, setLocalMaxTokens] = React.useState(maxTokens);
  const [localMaxTokens, setLocalMaxTokens] = React.useState(75000);
  const [localMaxSteps, setLocalMaxSteps] = React.useState(maxSteps);
  const [serverDomainOverrides, setServerDomainOverrides] = React.useState<Record<string, string>>({});
  const [serverTemperatureOverrides, setServerTemperatureOverrides] = React.useState<Record<string, number>>({});
  const [serverDefaultMaxTokens, setServerDefaultMaxTokens] = React.useState(75000);

  // Load server config on mount
  React.useEffect(() => {
    api.getServerConfig()
      .then((config) => {
        setServerDomainOverrides(config.domain_model_overrides || {});
        setServerTemperatureOverrides(config.domain_temperature_overrides || {});
        // Store server default for reset functionality
        if (config.default_max_tokens) {
          setServerDefaultMaxTokens(config.default_max_tokens);
        }
      })
      .catch((error) => {
        console.error("Failed to load server config:", error);
      });
  }, []);

  const handleSave = () => {
    setMaxTokens(localMaxTokens);
    setMaxSteps(localMaxSteps);
    router.push("/");
  };

  const handleReset = () => {
    reset();
    setLocalMaxTokens(serverDefaultMaxTokens);
    setLocalMaxSteps(20);
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      {/* Header */}
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar>
          <IconButton
            edge="start"
            color="inherit"
            onClick={() => router.push("/")}
            sx={{ mr: 2 }}
          >
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            Configuration
          </Typography>
          <Button
            variant="outlined"
            startIcon={<RestartAltIcon />}
            onClick={handleReset}
            sx={{ mr: 2 }}
          >
            Reset
          </Button>
          <Button
            variant="contained"
            startIcon={<SaveIcon />}
            onClick={handleSave}
          >
            Save
          </Button>
        </Toolbar>
      </AppBar>

      {/* Content */}
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Paper sx={{ p: 4 }}>
          <Typography variant="h5" gutterBottom>
            Conversation Settings
          </Typography>
          <Typography variant="body2" color="text.secondary" paragraph>
            Configure default settings for new conversations. These settings will
            be applied when starting a new session.
          </Typography>

          <Divider sx={{ my: 3 }} />

          <Stack spacing={4}>
            {/* Model Selection */}
            <FormControl fullWidth>
              <InputLabel id="model-select-label">LLM Model</InputLabel>
              <Select
                labelId="model-select-label"
                id="model-select"
                value={model}
                label="LLM Model"
                onChange={(e: SelectChangeEvent<string>) => setModel(e.target.value as SupportedModel)}
              >
                {SUPPORTED_MODELS.map((m) => (
                  <MenuItem key={m} value={m}>
                    {m}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {/* Temperature */}
            <Box>
              <Typography gutterBottom>
                Temperature: {temperature.toFixed(2)}
              </Typography>
              <Typography variant="caption" color="text.secondary" paragraph>
                Lower values make output more deterministic. Range: 0.1 to 1.0
              </Typography>
              <Slider
                value={temperature}
                onChange={(_, value) => setTemperature(value as number)}
                min={0.1}
                max={1.0}
                step={0.1}
                marks={[
                  { value: 0.1, label: "0.1" },
                  { value: 0.5, label: "0.5" },
                  { value: 1.0, label: "1.0" },
                ]}
                valueLabelDisplay="auto"
              />
            </Box>

            {/* Max Tokens */}
            <Box>
              <TextField
                fullWidth
                label="Max Tokens"
                type="number"
                value={localMaxTokens}
                onChange={(e) =>
                  setLocalMaxTokens(parseInt(e.target.value) || serverDefaultMaxTokens)
                }
                inputProps={{ step: 1000 }}
                helperText="Maximum tokens per response (default: 75,000)"
                disabled={useMaxModelTokens}
              />
            </Box>

            {/* Use Max Model Tokens */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={useMaxModelTokens}
                  onChange={(e) => setUseMaxModelTokens(e.target.checked)}
                />
              }
              label={
                <Box>
                  <Typography>Use Max Model Tokens</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Automatically use the model&apos;s maximum output token limit (e.g., 16K for GPT-4o, 65K for GPT-5)
                  </Typography>
                </Box>
              }
            />

            {/* Budget Enforced */}
            <FormControlLabel
              control={
                <Checkbox
                  checked={budgetEnforced}
                  onChange={(e) => setBudgetEnforced(e.target.checked)}
                />
              }
              label={
                <Box>
                  <Typography>Budget Enforcement</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Enforce session token budget limits
                  </Typography>
                </Box>
              }
            />

            {/* Max Steps */}
            <Box>
              <TextField
                fullWidth
                label="Max Steps"
                type="number"
                value={localMaxSteps}
                onChange={(e) =>
                  setLocalMaxSteps(
                    Math.min(25, Math.max(5, parseInt(e.target.value) || 5))
                  )
                }
                inputProps={{ min: 5, max: 25, step: 1 }}
                helperText="Maximum reasoning steps. Range: 5 to 25"
              />
            </Box>

            {/* Logging Level */}
            <FormControl fullWidth>
              <InputLabel id="logging-level-label">Logging Level</InputLabel>
              <Select
                labelId="logging-level-label"
                id="logging-level-select"
                value={loggingLevel}
                label="Logging Level"
                onChange={(e: SelectChangeEvent<string>) => setLoggingLevel(e.target.value as LoggingLevel)}
              >
                {LOGGING_LEVELS.map((level) => (
                  <MenuItem key={level} value={level}>
                    {level}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Stack>

          <Divider sx={{ my: 3 }} />

          {/* Domain-Specific Model & Temperature Configuration */}
          <DomainModelSelector
            domainModels={domainModels}
            domainTemperatures={domainTemperatures}
            onSetDomainModel={setDomainModel}
            onSetDomainTemperature={setDomainTemperature}
            defaultModel={model}
            defaultTemperature={temperature}
            serverDomainOverrides={serverDomainOverrides}
            serverTemperatureOverrides={serverTemperatureOverrides}
          />

          <Divider sx={{ my: 3 }} />

          <Typography variant="caption" color="text.secondary">
            API endpoints and authentication tokens are managed internally and not
            exposed in this interface.
          </Typography>
        </Paper>
      </Container>
    </Box>
  );
}
