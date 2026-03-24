/**
 * Copyright (c) 2025 Starboard AI
 * Licensed under the MIT License (see LICENSE file in the root directory)
 */

import type { Metadata } from "next";
import { EmotionRegistry } from "@/lib/theme/EmotionRegistry";
import { ThemeProvider } from "@/lib/theme/ThemeProvider";
import { QueryProvider } from "@/lib/api/QueryProvider";
import { NotificationSnackbar } from "@/components/common/NotificationSnackbar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Starboard AI Chat",
  description: "AI-powered chat interface for Databricks workload analysis",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* SECURITY: Safe — hardcoded inline script for theme flash prevention.
            Content is a static string literal, not user-controlled. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('theme-mode');
                  var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  var shouldBeDark = theme === 'dark' || (!theme && prefersDark);
                  
                  if (shouldBeDark) {
                    document.documentElement.classList.add('dark');
                    document.documentElement.setAttribute('data-theme', 'dark');
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
      </head>
      <body>
        <EmotionRegistry>
          <QueryProvider>
            <ThemeProvider>
              {children}
              <NotificationSnackbar />
            </ThemeProvider>
          </QueryProvider>
        </EmotionRegistry>
      </body>
    </html>
  );
}
