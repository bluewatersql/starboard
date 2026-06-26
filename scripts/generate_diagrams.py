#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Generate all diagrams from text sources.

This script generates PNG images from Mermaid (.mmd) and PlantUML (.puml) diagram
source files.

Usage:
    python scripts/generate_diagrams.py [--verbose] [--quality high|medium|low]

Requirements:
    - mmdc (Mermaid CLI): npm install -g @mermaid-js/mermaid-cli
    - plantuml: brew install plantuml (or apt-get install plantuml)

Quality Presets:
    - high: 2400x1800, 2x scale (best for detailed architecture diagrams)
    - medium: 1600x1200, 1.5x scale (balanced for most diagrams)
    - low: 800x600, 1x scale (fast generation, smaller files)
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

# Directories
DOCS_DIR = Path("docs")
DIAGRAMS_SOURCE_DIR = DOCS_DIR / "diagrams" / "source"
DIAGRAMS_OUTPUT_DIR = DOCS_DIR / "diagrams" / "generated"


class QualityPreset(TypedDict):
    """Quality preset configuration."""

    width: int
    height: int
    scale: float
    plantuml_limit: int


# Quality presets for different use cases
QUALITY_PRESETS: dict[str, QualityPreset] = {
    "high": {
        "width": 2400,
        "height": 1800,
        "scale": 2,
        "plantuml_limit": 16384,
    },
    "medium": {
        "width": 1600,
        "height": 1200,
        "scale": 1.5,
        "plantuml_limit": 8192,
    },
    "low": {
        "width": 800,
        "height": 600,
        "scale": 1,
        "plantuml_limit": 4096,
    },
}

# Mermaid configuration for better diagram layouts
MERMAID_CONFIG = {
    "flowchart": {
        "nodeSpacing": 80,  # Increased from 50 for better readability
        "rankSpacing": 100,  # Increased from 70 for better readability
        "curve": "basis",
        "padding": 20,
    },
    "sequence": {
        "diagramMarginX": 50,
        "diagramMarginY": 30,
        "actorMargin": 80,
        "boxMargin": 20,
        "boxTextMargin": 10,
        "noteMargin": 15,
        "messageMargin": 45,
    },
    "themeVariables": {
        "fontSize": "16px",  # Increased from 14px for better readability
        "fontFamily": "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
    },
}


def generate_mermaid_diagrams(
    verbose: bool = False,
    quality: str = "high",
    theme: str = "default",
) -> list[tuple[Path, bool, str]]:
    """Generate PNG from all .mmd files.

    Args:
        verbose: Print detailed output
        quality: Quality preset name (high, medium, low)
        theme: Theme name (default, dark, neutral, forest)

    Returns:
        List of tuples containing (source_file, success, message)
    """
    results = []
    mmd_files = list(DIAGRAMS_SOURCE_DIR.glob("**/*.mmd"))
    preset = QUALITY_PRESETS[quality]

    if not mmd_files:
        if verbose:
            print("ℹ️  No Mermaid diagrams found")
        return results

    # Create temporary config file for Mermaid
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
    ) as config_file:
        json.dump(MERMAID_CONFIG, config_file)
        config_path = config_file.name

    # Determine background color based on theme
    backgrounds = {
        "default": "white",
        "dark": "#0d1117",
        "neutral": "white",
        "forest": "#f0f9f4",
    }
    background_color = backgrounds.get(theme, "white")

    try:
        for mmd_file in mmd_files:
            # Create output path maintaining directory structure
            relative_path = mmd_file.relative_to(DIAGRAMS_SOURCE_DIR)
            output_file = DIAGRAMS_OUTPUT_DIR / relative_path.with_suffix(".png")
            output_file.parent.mkdir(parents=True, exist_ok=True)

            cmd = [
                "mmdc",
                "-i",
                str(mmd_file),
                "-o",
                str(output_file),
                "-t",
                theme,
                "-b",
                background_color,
                "-w",
                str(preset["width"]),
                "-H",
                str(preset["height"]),
                "-s",
                str(preset["scale"]),
                "-c",
                config_path,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,  # Increased timeout for larger diagrams
                )
                success = result.returncode == 0

                if success:
                    message = f"Generated {output_file.relative_to(DOCS_DIR)}"
                else:
                    message = (
                        f"Failed to generate {mmd_file.name}: {result.stderr[:100]}"
                    )

                results.append((mmd_file, success, message))

            except subprocess.TimeoutExpired:
                results.append((mmd_file, False, f"Timeout generating {mmd_file.name}"))
            except FileNotFoundError:
                results.append(
                    (
                        mmd_file,
                        False,
                        "mmdc not found. Install with: npm install -g @mermaid-js/mermaid-cli",
                    )
                )
                break  # No point continuing if tool is missing
    finally:
        # Clean up temp config file
        Path(config_path).unlink(missing_ok=True)

    return results


def generate_plantuml_diagrams(
    verbose: bool = False,
    quality: str = "high",
) -> list[tuple[Path, bool, str]]:
    """Generate PNG from all .puml files.

    Args:
        verbose: Print detailed output
        quality: Quality preset name (high, medium, low)

    Returns:
        List of tuples containing (source_file, success, message)
    """
    results = []
    puml_files = list(DIAGRAMS_SOURCE_DIR.glob("**/*.puml"))
    preset = QUALITY_PRESETS[quality]

    if not puml_files:
        if verbose:
            print("ℹ️  No PlantUML diagrams found")
        return results

    for puml_file in puml_files:
        # Create output path maintaining directory structure
        relative_path = puml_file.relative_to(DIAGRAMS_SOURCE_DIR)
        output_dir = DIAGRAMS_OUTPUT_DIR / relative_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # PlantUML uses PLANTUML_LIMIT_SIZE env var and -D flags for quality
        cmd = [
            "plantuml",
            "-tpng",
            f"-DPLANTUML_LIMIT_SIZE={preset['plantuml_limit']}",
            "-o",
            str(output_dir.absolute()),
            str(puml_file.absolute()),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # Increased timeout for larger diagrams
            )
            success = result.returncode == 0

            if success:
                output_file = output_dir / puml_file.with_suffix(".png").name
                message = f"Generated {output_file.relative_to(DOCS_DIR)}"
            else:
                message = f"Failed to generate {puml_file.name}: {result.stderr[:100]}"

            results.append((puml_file, success, message))

        except subprocess.TimeoutExpired:
            results.append((puml_file, False, f"Timeout generating {puml_file.name}"))
        except FileNotFoundError:
            results.append(
                (
                    puml_file,
                    False,
                    "plantuml not found. Install with: brew install plantuml",
                )
            )
            break  # No point continuing if tool is missing

    return results


def main():
    """Generate all diagrams."""
    parser = argparse.ArgumentParser(
        description="Generate documentation diagrams from Mermaid and PlantUML sources",
        epilog="""
Quality Presets:
  high   - 2400x1800, 2x scale (best for detailed architecture diagrams)
  medium - 1600x1200, 1.5x scale (balanced for most diagrams)
  low    - 800x600, 1x scale (fast generation, smaller files)
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output showing all generated files",
    )
    parser.add_argument(
        "--quality",
        "-q",
        choices=["high", "medium", "low"],
        default="high",
        help="Output quality preset (default: high)",
    )
    parser.add_argument(
        "--theme",
        "-t",
        choices=["default", "dark", "neutral", "forest"],
        default="default",
        help="Theme for diagrams (default: default)",
    )
    args = parser.parse_args()

    preset = QUALITY_PRESETS[args.quality]
    print(f"🎨 Generating diagrams (quality: {args.quality}, theme: {args.theme})...")
    print(
        f"   Resolution: {preset['width']}x{preset['height']} @ {preset['scale']}x scale"
    )

    # Create output directory
    DIAGRAMS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate diagrams
    mermaid_results = generate_mermaid_diagrams(args.verbose, args.quality, args.theme)
    plantuml_results = generate_plantuml_diagrams(args.verbose, args.quality)

    # Report results
    all_results = mermaid_results + plantuml_results

    if not all_results:
        print("\n⚠️  No diagram source files found in", DIAGRAMS_SOURCE_DIR)
        print(
            "   Create .mmd (Mermaid) or .puml (PlantUML) files to generate diagrams."
        )
        return

    successes = [r for r in all_results if r[1]]
    failures = [r for r in all_results if not r[1]]

    # Print details
    if args.verbose or failures:
        for _source, success, message in all_results:
            symbol = "✓" if success else "✗"
            print(f"  {symbol} {message}")

    # Summary
    print(f"\n📊 Summary: {len(successes)} succeeded, {len(failures)} failed")

    if failures:
        print("\n❌ Some diagrams failed to generate. See errors above.")
        sys.exit(1)
    else:
        print("✅ All diagrams generated successfully!")


if __name__ == "__main__":
    main()
