/**
 * Config page — server component wrapper.
 *
 * This file is intentionally a React Server Component (no "use client"
 * directive). It provides:
 *   - Static page metadata exported for Next.js head injection
 *   - A thin server-rendered shell that immediately renders ConfigPageClient
 *
 * The interactive form logic lives in ConfigPageClient, which is a
 * "use client" island. This follows the RSC island pattern: the static
 * outer shell is server-rendered (zero JS cost), while only the
 * interactive inner island is hydrated on the client.
 *
 * Why not make the whole page a server component?
 * The config form uses useRouter, useState, useEffect, and Zustand stores —
 * all of which require client-side execution. Those hooks cannot run in an
 * RSC. The solution is to push the client boundary inward (to ConfigPageClient)
 * rather than having it at the page root.
 */

import type { Metadata } from "next";
import { ConfigPageClient } from "./ConfigPageClient";

export const metadata: Metadata = {
  title: "Configuration — Starboard AI",
  description: "Configure conversation model, temperature, and token settings",
};

/**
 * Config page server component.
 *
 * Renders the ConfigPageClient island. Next.js will server-render this
 * component and stream the HTML to the browser; React hydration will
 * then activate the client island.
 */
export default function ConfigPage() {
  return <ConfigPageClient />;
}
