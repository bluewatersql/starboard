/**
 * Tests for file download utilities.
 */

import { generateFilename } from "../file-download";

// Mock DOM APIs
const mockCreateObjectURL = jest.fn(() => "blob:mock-url");
const mockRevokeObjectURL = jest.fn();
const mockAppendChild = jest.fn();
const mockRemoveChild = jest.fn();
const mockClick = jest.fn();

// Store original implementations
const originalURL = global.URL;

beforeEach(() => {
  jest.clearAllMocks();

  // Mock URL
  global.URL = {
    ...originalURL,
    createObjectURL: mockCreateObjectURL,
    revokeObjectURL: mockRevokeObjectURL,
  } as unknown as typeof URL;

  // Mock document.createElement to return a mock anchor
  const mockAnchor = {
    href: "",
    download: "",
    click: mockClick,
  };

  jest.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);
  jest.spyOn(document.body, "appendChild").mockImplementation(mockAppendChild);
  jest.spyOn(document.body, "removeChild").mockImplementation(mockRemoveChild);
});

afterEach(() => {
  global.URL = originalURL;
  jest.restoreAllMocks();
});

describe("generateFilename", () => {
  beforeEach(() => {
    // Mock Date to return a fixed date
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2024-01-15T12:00:00Z"));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("generates filename with timestamp", () => {
    const result = generateFilename("report", "pdf");
    expect(result).toBe("report-2024-01-15.pdf");
  });

  it("sanitizes special characters", () => {
    const result = generateFilename("My Report!", "pdf");
    expect(result).toBe("my-report-2024-01-15.pdf");
  });

  it("converts to lowercase", () => {
    const result = generateFilename("UPPERCASE", "txt");
    expect(result).toBe("uppercase-2024-01-15.txt");
  });

  it("collapses multiple dashes", () => {
    const result = generateFilename("a---b---c", "txt");
    expect(result).toBe("a-b-c-2024-01-15.txt");
  });

  it("removes leading and trailing dashes", () => {
    const result = generateFilename("--test--", "txt");
    expect(result).toBe("test-2024-01-15.txt");
  });

  it("handles spaces", () => {
    const result = generateFilename("Sales Data Q4", "csv");
    expect(result).toBe("sales-data-q4-2024-01-15.csv");
  });

  it("handles complex names", () => {
    const result = generateFilename("Cost Analysis: 2024 (v2)", "json");
    expect(result).toBe("cost-analysis-2024-v2-2024-01-15.json");
  });
});

describe("downloadFile", () => {
  // Import dynamically to ensure mocks are in place
  let downloadFile: typeof import("../file-download").downloadFile;

  beforeEach(async () => {
    // eslint-disable-next-line @next/next/no-assign-module-variable
    const module = await import("../file-download");
    downloadFile = module.downloadFile;
  });

  it("creates blob from string content", () => {
    downloadFile({
      content: "test content",
      filename: "test.txt",
      mimeType: "text/plain",
    });

    expect(mockCreateObjectURL).toHaveBeenCalled();
    expect(mockClick).toHaveBeenCalled();
    expect(mockRevokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });

  it("uses blob directly when provided", () => {
    const blob = new Blob(["test"], { type: "text/plain" });

    downloadFile({
      content: blob,
      filename: "test.txt",
    });

    expect(mockCreateObjectURL).toHaveBeenCalledWith(blob);
    expect(mockClick).toHaveBeenCalled();
  });

  it("cleans up after download", () => {
    downloadFile({
      content: "test",
      filename: "test.txt",
      mimeType: "text/plain",
    });

    expect(mockAppendChild).toHaveBeenCalled();
    expect(mockRemoveChild).toHaveBeenCalled();
    expect(mockRevokeObjectURL).toHaveBeenCalled();
  });
});

describe("downloadFromUrl", () => {
  let downloadFromUrl: typeof import("../file-download").downloadFromUrl;

  beforeEach(async () => {
    // eslint-disable-next-line @next/next/no-assign-module-variable
    const module = await import("../file-download");
    downloadFromUrl = module.downloadFromUrl;
  });

  it("uses provided URL directly", () => {
    const mockAnchor = {
      href: "",
      download: "",
      click: mockClick,
    };
    jest.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);

    downloadFromUrl("blob:existing-url", "chart.png");

    expect(mockAnchor.href).toBe("blob:existing-url");
    expect(mockAnchor.download).toBe("chart.png");
    expect(mockClick).toHaveBeenCalled();
  });

  it("does not create or revoke object URL", () => {
    downloadFromUrl("blob:existing-url", "chart.png");

    expect(mockCreateObjectURL).not.toHaveBeenCalled();
    expect(mockRevokeObjectURL).not.toHaveBeenCalled();
  });
});

describe("convenience wrappers", () => {
  let downloadJson: typeof import("../file-download").downloadJson;
  let downloadCsv: typeof import("../file-download").downloadCsv;
  let downloadMarkdown: typeof import("../file-download").downloadMarkdown;

  beforeEach(async () => {
    // eslint-disable-next-line @next/next/no-assign-module-variable
    const module = await import("../file-download");
    downloadJson = module.downloadJson;
    downloadCsv = module.downloadCsv;
    downloadMarkdown = module.downloadMarkdown;
  });

  it("downloadJson adds .json extension if missing", () => {
    const mockAnchor = { href: "", download: "", click: mockClick };
    jest.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);

    downloadJson({ test: true }, "data");

    expect(mockAnchor.download).toBe("data.json");
  });

  it("downloadJson preserves .json extension if present", () => {
    const mockAnchor = { href: "", download: "", click: mockClick };
    jest.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);

    downloadJson({ test: true }, "data.json");

    expect(mockAnchor.download).toBe("data.json");
  });

  it("downloadCsv adds .csv extension if missing", () => {
    const mockAnchor = { href: "", download: "", click: mockClick };
    jest.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);

    downloadCsv("a,b\n1,2", "data");

    expect(mockAnchor.download).toBe("data.csv");
  });

  it("downloadMarkdown adds .md extension if missing", () => {
    const mockAnchor = { href: "", download: "", click: mockClick };
    jest.spyOn(document, "createElement").mockReturnValue(mockAnchor as unknown as HTMLAnchorElement);

    downloadMarkdown("# Title", "doc");

    expect(mockAnchor.download).toBe("doc.md");
  });
});

