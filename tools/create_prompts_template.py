#!/usr/bin/env python3
"""
Create a template ODS file for TensorART Generator
This script creates an example prompts.ods file with the correct structure
"""

from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TableColumnProperties, TableRowProperties, TextProperties
from odf.table import Table, TableColumn, TableRow, TableCell
from odf.text import P
import sys


def create_template(output_path: str, channels: list = None):
    """Create an ODS template file for prompts and usage tracking"""

    if channels is None:
        channels = ["Channel1", "Channel2", "Channel3"]

    # Create a new spreadsheet
    doc = OpenDocumentSpreadsheet()

    # Create a table (sheet)
    prompts_table = Table(name="Prompts")

    # Add columns
    prompts_table.addElement(TableColumn())  # Prompt column
    for _ in channels:
        prompts_table.addElement(TableColumn())  # Usage columns

    # Create header row
    header_row = TableRow()

    # Prompt header
    prompt_header_cell = TableCell()
    prompt_header_cell.addElement(P(text="Prompt"))
    header_row.addElement(prompt_header_cell)

    # Channel usage headers
    for channel in channels:
        channel_header_cell = TableCell()
        channel_header_cell.addElement(P(text=f"{channel}_Usage"))
        header_row.addElement(channel_header_cell)

    prompts_table.addElement(header_row)

    # Add example prompts
    example_prompts = [
        "A serene mountain landscape at sunset",
        "A bustling city street in the rain",
        "A peaceful forest with sunlight filtering through trees",
        "An old library filled with ancient books",
        "A cozy coffee shop on a rainy day",
        "A majestic waterfall in a tropical jungle",
        "A vintage car parked on a cobblestone street",
        "A lighthouse standing tall against stormy seas",
        "A colorful market filled with fresh fruits",
        "A snowy cabin in the woods at night"
    ]

    for prompt_text in example_prompts:
        data_row = TableRow()

        # Prompt cell
        prompt_cell = TableCell()
        prompt_cell.addElement(P(text=prompt_text))
        data_row.addElement(prompt_cell)

        # Usage count cells (initialized to 0)
        for _ in channels:
            usage_cell = TableCell()
            usage_cell.addElement(P(text="0"))
            data_row.addElement(usage_cell)

        prompts_table.addElement(data_row)

    # Add the table to the document
    doc.spreadsheet.addElement(prompts_table)

    # Save the document
    doc.save(output_path)
    print(f"Template created successfully: {output_path}")
    print(f"\nStructure:")
    print(f"  - Column 1: Prompt (text prompts)")
    print(f"  - Columns 2+: {', '.join([f'{ch}_Usage' for ch in channels])}")
    print(f"\nExample prompts: {len(example_prompts)}")
    print(f"\nYou can now:")
    print(f"  1. Open this file in LibreOffice Calc or Excel")
    print(f"  2. Edit the prompts to your liking")
    print(f"  3. Add or remove channels by adding/removing columns")
    print(f"  4. Make sure column headers end with '_Usage' for channel columns")


def main():
    output_path = input("Enter output file path (e.g., prompts.ods): ").strip()

    if not output_path:
        output_path = "prompts.ods"

    if not output_path.endswith('.ods'):
        output_path += '.ods'

    # Ask for channel names
    channels_input = input("Enter channel names separated by commas (default: Channel1,Channel2,Channel3): ").strip()

    if channels_input:
        channels = [ch.strip() for ch in channels_input.split(',')]
    else:
        channels = ["Channel1", "Channel2", "Channel3"]

    create_template(output_path, channels)


if __name__ == "__main__":
    main()
