# TensorART Image Generator

An automated image generation tool that uses the TensorART API to create images from prompts stored in an ODS spreadsheet, with intelligent channel-based usage tracking.

## Features

- Reads prompts from an ODS (.ods) file
- Automatically tracks usage count per prompt per channel
- Prevents overuse: skips prompts used 5+ times for a specific channel
- Uses TensorART API with Flux.1 model and custom LoRA
- Automatically appends ":Oil painting,Expressive brushstroke," to all prompts
- Saves generated images to a folder of your choice
- Organizes files by channel and timestamp

## Requirements

Install the required dependencies:

```bash
pip install odfpy requests
```

Or install from requirements.txt:

```bash
pip install -r requirements.txt
```

## Setup

### 1. Get TensorART API Key

You need a TensorART API key. Get one from https://tensor.art

Set it as an environment variable:

```bash
export TENSORART_API_KEY='your-api-key-here'
```

On Windows:
```cmd
set TENSORART_API_KEY=your-api-key-here
```

### 2. Create Prompts ODS File

You can create a prompts file in two ways:

#### Option A: Use the template generator

```bash
python tools/create_prompts_template.py
```

This will create an example `prompts.ods` file with the correct structure.

#### Option B: Create manually

Create an ODS file (using LibreOffice Calc or Excel) with this structure:

| Prompt | Channel1_Usage | Channel2_Usage | Channel3_Usage |
|--------|----------------|----------------|----------------|
| A serene mountain landscape at sunset | 0 | 0 | 0 |
| A bustling city street in the rain | 0 | 0 | 0 |
| A peaceful forest with sunlight | 0 | 0 | 0 |

**Important:**
- First column must be named "Prompt"
- Channel columns must end with "_Usage" (e.g., "MyChannel_Usage")
- Initialize all usage counts to 0
- You can add as many channels as you need
- You can add as many prompts as you want

### 3. Create Output Folder

Create a folder where generated images will be saved:

```bash
mkdir output/tensorart_images
```

## Usage

Run the generator:

```bash
python tools/tensorart_generator.py
```

You will be prompted for:

1. **Path to prompts ODS file**: e.g., `prompts.ods`
2. **Output folder path**: e.g., `output/tensorart_images`
3. **Channel name**: e.g., `Channel1` (must match a channel in your ODS file)
4. **Number of images**: How many images to generate (default: 1)

### Example Session

```
============================================================
TensorART Image Generator
============================================================

Enter path to prompts ODS file: prompts.ods
Enter output folder path: output/tensorart_images
Enter channel name: Channel1
Number of images to generate (default 1): 3

============================================================
Starting generation of 3 image(s) for channel 'Channel1'
============================================================

============================================================
Generating image 1/3 for channel: Channel1
============================================================

Selected prompt (index 2): A peaceful forest with sunlight
Full prompt: A peaceful forest with sunlight:Oil painting,Expressive brushstroke,

Generating image with TensorART...
Model: flux.1:757279507095956705
LoRA: 832298395185001638 (weight: 0.8)

Polling task abc123...
Status: processing... waiting 5s
Status: completed!

Downloading image to output/tensorart_images/Channel1_20250116_143022_2.png...
Image saved successfully!

Success! Image saved to: output/tensorart_images/Channel1_20250116_143022_2.png

...
```

## How It Works

### Prompt Selection

1. The program reads all prompts from your ODS file
2. For the specified channel, it finds prompts that have been used less than 5 times
3. It randomly selects one available prompt
4. It appends ":Oil painting,Expressive brushstroke," to the prompt
5. It sends the request to TensorART API

### Usage Tracking

After each successful generation:

1. The usage count for that prompt and channel is incremented in the ODS file
2. The ODS file is automatically saved
3. If a prompt reaches 5 uses for a channel, it won't be selected again for that channel
4. The same prompt can still be used up to 5 times for each different channel

### Image Naming

Generated images are named with this format:
```
{channel}_{timestamp}_{prompt_index}.png
```

Example: `Channel1_20250116_143022_2.png`
- Channel: Channel1
- Timestamp: 2025-01-16 14:30:22
- Prompt index: 2 (the 3rd prompt in your ODS file)

## Model Configuration

The generator uses these TensorART settings:

- **Model**: `flux.1:757279507095956705`
- **LoRA**: `832298395185001638`
- **LoRA Weight**: 0.8
- **Style suffix**: ":Oil painting,Expressive brushstroke,"

These are hardcoded in the `generate_for_channel()` call in the main script. To change them, edit the values in `tensorart_generator.py`.

## ODS File Structure

### Header Row (Required)

- **Prompt** (column 1): Contains the text prompts
- **{ChannelName}_Usage** (columns 2+): Usage counters for each channel

### Data Rows

Each row represents one prompt with its usage counts across all channels.

### Example

```
| Prompt                              | Gaming_Usage | Travel_Usage | Food_Usage |
|-------------------------------------|--------------|--------------|------------|
| A serene mountain landscape         | 2            | 0            | 1          |
| A bustling city street              | 5            | 3            | 0          |
| A peaceful forest                   | 0            | 5            | 2          |
```

In this example:
- "A bustling city street" won't be used for Gaming (5 uses)
- "A peaceful forest" won't be used for Travel (5 uses)
- Other prompts are still available for their respective channels

## Troubleshooting

### "No available prompts for channel"

All prompts have been used 5+ times for this channel. Options:
1. Add more prompts to your ODS file
2. Manually reset usage counts to 0 in the ODS file
3. Use a different channel name

### "TENSORART_API_KEY environment variable not set"

Set your API key:
```bash
export TENSORART_API_KEY='your-key'
```

### "ODS file not found"

Make sure you provide the correct path to your .ods file. Use absolute paths if needed:
```
/home/user/Documents/prompts.ods
```

### "No 'Prompt' column found"

Your ODS file must have a column named exactly "Prompt" (case-insensitive).

### Generation fails or times out

- Check your TensorART API key is valid
- Check your internet connection
- The TensorART API may be experiencing issues

## Advanced Usage

### Programmatic Usage

You can also import and use the generator in your own Python scripts:

```python
from tools.tensorart_generator import TensorARTGenerator

# Initialize
generator = TensorARTGenerator(
    api_key="your-tensorart-api-key",
    ods_path="prompts.ods",
    output_folder="output/images"
)

# Generate 5 images for a channel
files = generator.generate_for_channel(
    channel="MyChannel",
    count=5,
    model_id="757279507095956705",
    lora_id="832298395185001638",
    lora_weight=0.8
)

print(f"Generated {len(files)} images")
```

### Custom Model/LoRA

To use different models or LoRAs, modify the parameters in the `generate_for_channel()` call:

```python
files = generator.generate_for_channel(
    channel="MyChannel",
    count=1,
    model_id="your-model-id",
    lora_id="your-lora-id",
    lora_weight=0.5  # Adjust weight between 0 and 1
)
```

## Files

- `tensorart_generator.py` - Main generator script
- `create_prompts_template.py` - Helper to create ODS template
- `TENSORART_README.md` - This documentation

## License

Part of the WeJaWi Desktop v3 project.
