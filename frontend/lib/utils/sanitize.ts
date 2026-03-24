/**
 * HTML sanitization utilities using DOMPurify.
 *
 * Provides defense-in-depth XSS protection for HTML rendered via
 * `dangerouslySetInnerHTML`. Primary use case: Shiki syntax-highlighted
 * code output, which is trusted but sanitized as a precaution.
 *
 * SSR guard: Returns input unchanged on the server (DOMPurify requires
 * a DOM environment). Client-side sanitization runs on hydration.
 */
import DOMPurify from "dompurify";

/** Tags allowed in sanitized Shiki HTML output. */
const ALLOWED_TAGS = [
  "span",
  "pre",
  "code",
  "div",
  "p",
  "br",
  "em",
  "strong",
  "a",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tr",
  "th",
  "td",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "blockquote",
];

/** Attributes allowed in sanitized output. */
const ALLOWED_ATTR = [
  "class",
  "style",
  "href",
  "target",
  "rel",
  "title",
  "data-language",
  "data-line",
];

/**
 * Sanitize Shiki-generated HTML for safe rendering via dangerouslySetInnerHTML.
 *
 * - Server-side (SSR): returns input unchanged (no DOM available).
 * - Client-side: strips disallowed tags/attributes via DOMPurify.
 *
 * @param html - Raw HTML string from Shiki highlighter
 * @returns Sanitized HTML string safe for rendering
 */
export function sanitizeShikiHtml(html: string): string {
  // SSR guard: DOMPurify requires window/document
  if (typeof window === "undefined") {
    return html;
  }

  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: true,
  });
}
