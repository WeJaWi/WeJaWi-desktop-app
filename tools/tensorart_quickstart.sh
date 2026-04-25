#!/bin/bash
# TensorART Generator Quick Start Script

echo "============================================================"
echo "TensorART Image Generator - Quick Start"
echo "============================================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3 first"
    exit 1
fi

echo "Step 1: Installing dependencies..."
pip3 install odfpy requests

echo ""
echo "Step 2: Setting up TensorART API Key"
echo "Please enter your TensorART API key:"
read -r api_key

if [ -z "$api_key" ]; then
    echo "ERROR: API key is required"
    exit 1
fi

export TENSORART_API_KEY="$api_key"

echo ""
echo "Step 3: Creating prompts template"
echo "Creating default prompts.ods file..."

python3 -c "
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableColumn, TableRow, TableCell
from odf.text import P

doc = OpenDocumentSpreadsheet()
prompts_table = Table(name='Prompts')

# Add columns
for _ in range(4):
    prompts_table.addElement(TableColumn())

# Header row
header_row = TableRow()
for header in ['Prompt', 'Channel1_Usage', 'Channel2_Usage', 'Channel3_Usage']:
    cell = TableCell()
    cell.addElement(P(text=header))
    header_row.addElement(cell)
prompts_table.addElement(header_row)

# Example prompts
prompts = [
    'A serene mountain landscape at sunset',
    'A bustling city street in the rain',
    'A peaceful forest with sunlight filtering through trees',
    'An old library filled with ancient books',
    'A cozy coffee shop on a rainy day',
    'A majestic waterfall in a tropical jungle',
    'A vintage car parked on a cobblestone street',
    'A lighthouse standing tall against stormy seas',
    'A colorful market filled with fresh fruits',
    'A snowy cabin in the woods at night'
]

for prompt in prompts:
    row = TableRow()
    cell = TableCell()
    cell.addElement(P(text=prompt))
    row.addElement(cell)
    for _ in range(3):
        cell = TableCell()
        cell.addElement(P(text='0'))
        row.addElement(cell)
    prompts_table.addElement(row)

doc.spreadsheet.addElement(prompts_table)
doc.save('prompts.ods')
print('Created prompts.ods successfully!')
"

echo ""
echo "Step 4: Creating output directory"
mkdir -p output/tensorart_images
echo "Created output/tensorart_images/"

echo ""
echo "============================================================"
echo "Setup Complete!"
echo "============================================================"
echo ""
echo "Files created:"
echo "  - prompts.ods (10 example prompts)"
echo "  - output/tensorart_images/ (output directory)"
echo ""
echo "Your API key has been set for this session."
echo ""
echo "To run the generator:"
echo "  python3 tools/tensorart_generator.py"
echo ""
echo "When prompted:"
echo "  - ODS file: prompts.ods"
echo "  - Output folder: output/tensorart_images"
echo "  - Channel: Channel1 (or Channel2, Channel3)"
echo "  - Number of images: 1 (or any number)"
echo ""
echo "Ready to generate images!"
echo "============================================================"
