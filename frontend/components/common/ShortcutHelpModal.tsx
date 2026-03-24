"use client";

import React from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Table,
  TableBody,
  TableRow,
  TableCell,
  Typography,
  Chip,
} from "@mui/material";

interface ShortcutHelpModalProps {
  open: boolean;
  onClose: () => void;
}

const isMac = typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.userAgent);
const modKey = isMac ? "⌘" : "Ctrl";

const shortcuts = [
  { keys: [`${modKey}`, "K"], description: "Search conversations" },
  { keys: [`${modKey}`, "N"], description: "New conversation" },
  { keys: [`${modKey}`, "Enter"], description: "Send message" },
  { keys: ["Esc"], description: "Cancel / Close" },
  { keys: ["?"], description: "Show this help" },
];

export function ShortcutHelpModal({ open, onClose }: ShortcutHelpModalProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Keyboard Shortcuts</DialogTitle>
      <DialogContent>
        <Table size="small">
          <TableBody>
            {shortcuts.map((s) => (
              <TableRow key={s.description}>
                <TableCell sx={{ border: "none", py: 0.75 }}>
                  {s.keys.map((k, i) => (
                    <React.Fragment key={k}>
                      {i > 0 && <Typography component="span" variant="caption" sx={{ mx: 0.5 }}>+</Typography>}
                      <Chip label={k} size="small" sx={{ fontFamily: "monospace", fontWeight: 600 }} />
                    </React.Fragment>
                  ))}
                </TableCell>
                <TableCell sx={{ border: "none", py: 0.75 }}>
                  <Typography variant="body2">{s.description}</Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
