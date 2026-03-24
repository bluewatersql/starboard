/**
 * Tests for sanitizeShikiHtml utility.
 *
 * @jest-environment jsdom
 */
import { sanitizeShikiHtml } from "../sanitize";

describe("sanitizeShikiHtml", () => {
  it("preserves safe Shiki HTML (spans with class/style)", () => {
    const html =
      '<pre class="shiki"><code><span style="color:#fff">const</span></code></pre>';
    expect(sanitizeShikiHtml(html)).toBe(html);
  });

  it("strips <script> tags", () => {
    const html = '<span>hello</span><script>alert("xss")</script>';
    const result = sanitizeShikiHtml(html);
    expect(result).not.toContain("<script>");
    expect(result).toContain("<span>hello</span>");
  });

  it("strips event handler attributes", () => {
    const html = '<span onmouseover="alert(1)">hover me</span>';
    const result = sanitizeShikiHtml(html);
    expect(result).not.toContain("onmouseover");
    expect(result).toContain("<span>hover me</span>");
  });

  it("strips <iframe> tags", () => {
    const html = '<span>ok</span><iframe src="evil.html"></iframe>';
    const result = sanitizeShikiHtml(html);
    expect(result).not.toContain("<iframe>");
    expect(result).toContain("<span>ok</span>");
  });

  it("strips <object> tags", () => {
    const html = '<span>ok</span><object data="evil.swf"></object>';
    const result = sanitizeShikiHtml(html);
    expect(result).not.toContain("<object>");
  });

  it("preserves data-language and data-line attributes", () => {
    const html = '<pre data-language="typescript"><code data-line="1">test</code></pre>';
    expect(sanitizeShikiHtml(html)).toBe(html);
  });

  it("preserves allowed block elements", () => {
    const html = "<div><p>paragraph</p><ul><li>item</li></ul></div>";
    expect(sanitizeShikiHtml(html)).toBe(html);
  });

  it("strips <img> tags (not in allowlist)", () => {
    const html = '<span>text</span><img src="x" onerror="alert(1)">';
    const result = sanitizeShikiHtml(html);
    expect(result).not.toContain("<img");
  });
});
