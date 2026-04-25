#!/usr/bin/env python3
"""
TensorART Image Generator
- Reads prompts from .ods file
- Tracks usage per prompt per channel
- Skips prompts with >5 uses per channel
- Uses TensorART API with flux.1 model and LoRA
- Appends ":Oil painting,Expressive brushstroke," to all prompts
- Saves images to specified folder
"""

import os
import sys
import json
import time
import random
import requests
import opendocument
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from odf import opendocument, table, text
from odf.opendocument import load


class ODSPromptManager:
    """Manages prompts and usage tracking in ODS file"""

    def __init__(self, ods_path: str):
        self.ods_path = ods_path
        self.prompts = []
        self.usage_data = {}  # {prompt_index: {channel: count}}

        if os.path.exists(ods_path):
            self.load_from_ods()
        else:
            raise FileNotFoundError(f"ODS file not found: {ods_path}")

    def load_from_ods(self):
        """Load prompts and usage data from ODS file"""
        doc = load(self.ods_path)
        sheet = doc.spreadsheet.getElementsByType(table.Table)[0]
        rows = sheet.getElementsByType(table.TableRow)

        # Expected format:
        # Row 0: Headers (Prompt, Channel1_Usage, Channel2_Usage, ...)
        # Row 1+: Data

        if len(rows) == 0:
            raise ValueError("ODS file is empty")

        # Parse header row to find column positions
        header_row = rows[0]
        header_cells = header_row.getElementsByType(table.TableCell)
        headers = []
        for cell in header_cells:
            cell_text = ""
            for p in cell.getElementsByType(text.P):
                cell_text += str(p)
            headers.append(cell_text.strip())

        # Find prompt column and channel usage columns
        prompt_col_idx = -1
        channel_columns = {}  # {channel_name: column_index}

        for idx, header in enumerate(headers):
            if header.lower() == "prompt":
                prompt_col_idx = idx
            elif "_usage" in header.lower():
                channel_name = header.replace("_usage", "").replace("_Usage", "").strip()
                channel_columns[channel_name] = idx

        if prompt_col_idx == -1:
            raise ValueError("No 'Prompt' column found in ODS file")

        # Read data rows
        for row_idx in range(1, len(rows)):
            row = rows[row_idx]
            cells = row.getElementsByType(table.TableCell)

            if len(cells) <= prompt_col_idx:
                continue

            # Get prompt text
            prompt_cell = cells[prompt_col_idx]
            prompt_text = ""
            for p in prompt_cell.getElementsByType(text.P):
                prompt_text += str(p)
            prompt_text = prompt_text.strip()

            if not prompt_text:
                continue

            self.prompts.append(prompt_text)

            # Get usage counts for each channel
            prompt_idx = len(self.prompts) - 1
            self.usage_data[prompt_idx] = {}

            for channel_name, col_idx in channel_columns.items():
                if col_idx < len(cells):
                    usage_cell = cells[col_idx]
                    usage_text = ""
                    for p in usage_cell.getElementsByType(text.P):
                        usage_text += str(p)
                    usage_text = usage_text.strip()

                    try:
                        count = int(usage_text) if usage_text else 0
                    except ValueError:
                        count = 0

                    self.usage_data[prompt_idx][channel_name] = count

        print(f"Loaded {len(self.prompts)} prompts from {self.ods_path}")

    def get_available_prompts(self, channel: str) -> List[Tuple[int, str]]:
        """Get prompts that haven't been used more than 5 times for this channel"""
        available = []
        for idx, prompt in enumerate(self.prompts):
            usage_count = self.usage_data.get(idx, {}).get(channel, 0)
            if usage_count < 5:
                available.append((idx, prompt))
        return available

    def get_random_prompt(self, channel: str) -> Optional[Tuple[int, str]]:
        """Get a random available prompt for the channel"""
        available = self.get_available_prompts(channel)
        if not available:
            return None
        return random.choice(available)

    def increment_usage(self, prompt_idx: int, channel: str):
        """Increment usage count for a prompt in a channel"""
        if prompt_idx not in self.usage_data:
            self.usage_data[prompt_idx] = {}

        if channel not in self.usage_data[prompt_idx]:
            self.usage_data[prompt_idx][channel] = 0

        self.usage_data[prompt_idx][channel] += 1
        self.save_to_ods()

    def save_to_ods(self):
        """Save updated usage data back to ODS file"""
        doc = load(self.ods_path)
        sheet = doc.spreadsheet.getElementsByType(table.Table)[0]
        rows = sheet.getElementsByType(table.TableRow)

        # Parse header to find channel columns
        header_row = rows[0]
        header_cells = header_row.getElementsByType(table.TableCell)
        headers = []
        for cell in header_cells:
            cell_text = ""
            for p in cell.getElementsByType(text.P):
                cell_text += str(p)
            headers.append(cell_text.strip())

        channel_columns = {}
        for idx, header in enumerate(headers):
            if "_usage" in header.lower():
                channel_name = header.replace("_usage", "").replace("_Usage", "").strip()
                channel_columns[channel_name] = idx

        # Update usage counts in cells
        for prompt_idx in range(len(self.prompts)):
            if prompt_idx + 1 >= len(rows):
                break

            row = rows[prompt_idx + 1]
            cells = row.getElementsByType(table.TableCell)

            for channel_name, col_idx in channel_columns.items():
                if col_idx < len(cells):
                    usage_count = self.usage_data.get(prompt_idx, {}).get(channel_name, 0)
                    cell = cells[col_idx]

                    # Clear existing content
                    for p in cell.getElementsByType(text.P):
                        cell.removeChild(p)

                    # Add new content
                    p = text.P(text=str(usage_count))
                    cell.addElement(p)

        doc.save(self.ods_path)


class TensorARTClient:
    """TensorART API client"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.tensor.art/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def generate_image(
        self,
        prompt: str,
        model_id: str = "757279507095956705",
        lora_id: str = "832298395185001638",
        lora_weight: float = 0.8,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0
    ) -> Dict:
        """Generate an image using TensorART API"""

        # Prepare the request payload
        payload = {
            "model_id": f"flux.1:{model_id}",
            "prompt": prompt,
            "negative_prompt": "low quality, blurry, distorted",
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "loras": [
                {
                    "id": lora_id,
                    "weight": lora_weight
                }
            ]
        }

        print(f"\nGenerating image with TensorART...")
        print(f"Prompt: {prompt}")
        print(f"Model: flux.1:{model_id}")
        print(f"LoRA: {lora_id} (weight: {lora_weight})")

        # Submit generation request
        response = requests.post(
            f"{self.base_url}/txt2img",
            headers=self.headers,
            json=payload
        )

        if response.status_code != 200:
            raise Exception(f"TensorART API error: {response.status_code} - {response.text}")

        result = response.json()

        # Check if we need to poll for results (async)
        if "task_id" in result:
            return self._poll_task(result["task_id"])

        return result

    def _poll_task(self, task_id: str, max_wait: int = 300, poll_interval: int = 5) -> Dict:
        """Poll for task completion"""
        print(f"Polling task {task_id}...")

        start_time = time.time()
        while time.time() - start_time < max_wait:
            response = requests.get(
                f"{self.base_url}/task/{task_id}",
                headers=self.headers
            )

            if response.status_code != 200:
                raise Exception(f"Task polling error: {response.status_code} - {response.text}")

            result = response.json()
            status = result.get("status", "")

            if status == "completed":
                print("Generation completed!")
                return result
            elif status == "failed":
                raise Exception(f"Generation failed: {result.get('error', 'Unknown error')}")

            print(f"Status: {status}... waiting {poll_interval}s")
            time.sleep(poll_interval)

        raise Exception(f"Task {task_id} timed out after {max_wait}s")

    def download_image(self, image_url: str, save_path: str) -> str:
        """Download image from URL to save_path"""
        print(f"Downloading image to {save_path}...")

        response = requests.get(image_url, stream=True)
        if response.status_code != 200:
            raise Exception(f"Failed to download image: {response.status_code}")

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Image saved successfully!")
        return save_path


class TensorARTGenerator:
    """Main generator class"""

    def __init__(self, api_key: str, ods_path: str, output_folder: str):
        self.client = TensorARTClient(api_key)
        self.prompt_manager = ODSPromptManager(ods_path)
        self.output_folder = output_folder

        # Create output folder if it doesn't exist
        os.makedirs(output_folder, exist_ok=True)

    def generate_for_channel(
        self,
        channel: str,
        count: int = 1,
        model_id: str = "757279507095956705",
        lora_id: str = "832298395185001638",
        lora_weight: float = 0.8
    ) -> List[str]:
        """Generate images for a specific channel"""

        generated_files = []

        for i in range(count):
            print(f"\n{'='*60}")
            print(f"Generating image {i+1}/{count} for channel: {channel}")
            print(f"{'='*60}")

            # Get random available prompt
            prompt_data = self.prompt_manager.get_random_prompt(channel)

            if prompt_data is None:
                print(f"WARNING: No available prompts for channel '{channel}'")
                print(f"All prompts have been used 5+ times for this channel.")
                continue

            prompt_idx, base_prompt = prompt_data

            # Append required style tags
            full_prompt = f"{base_prompt}:Oil painting,Expressive brushstroke,"

            print(f"\nSelected prompt (index {prompt_idx}): {base_prompt}")
            print(f"Full prompt: {full_prompt}")

            # Generate image
            try:
                result = self.client.generate_image(
                    prompt=full_prompt,
                    model_id=model_id,
                    lora_id=lora_id,
                    lora_weight=lora_weight
                )

                # Extract image URL from result
                image_url = None
                if "images" in result and len(result["images"]) > 0:
                    image_url = result["images"][0].get("url")
                elif "image_url" in result:
                    image_url = result["image_url"]
                elif "url" in result:
                    image_url = result["url"]

                if not image_url:
                    print(f"ERROR: No image URL in response: {result}")
                    continue

                # Generate filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{channel}_{timestamp}_{prompt_idx}.png"
                save_path = os.path.join(self.output_folder, filename)

                # Download image
                self.client.download_image(image_url, save_path)

                # Update usage count
                self.prompt_manager.increment_usage(prompt_idx, channel)

                generated_files.append(save_path)

                print(f"\nSuccess! Image saved to: {save_path}")

            except Exception as e:
                print(f"ERROR generating image: {str(e)}")
                continue

        return generated_files


def main():
    """Main entry point"""

    print("=" * 60)
    print("TensorART Image Generator")
    print("=" * 60)

    # Configuration
    API_KEY = os.environ.get("TENSORART_API_KEY", "")

    if not API_KEY:
        print("\nERROR: Please set TENSORART_API_KEY environment variable")
        print("Example: export TENSORART_API_KEY='your-api-key-here'")
        sys.exit(1)

    # Get ODS file path
    ods_path = input("\nEnter path to prompts ODS file: ").strip()
    if not ods_path:
        print("ERROR: ODS file path is required")
        sys.exit(1)

    if not os.path.exists(ods_path):
        print(f"ERROR: File not found: {ods_path}")
        sys.exit(1)

    # Get output folder
    output_folder = input("Enter output folder path: ").strip()
    if not output_folder:
        print("ERROR: Output folder path is required")
        sys.exit(1)

    # Get channel name
    channel = input("Enter channel name: ").strip()
    if not channel:
        print("ERROR: Channel name is required")
        sys.exit(1)

    # Get number of images to generate
    try:
        count = int(input("Number of images to generate (default 1): ").strip() or "1")
    except ValueError:
        count = 1

    # Initialize generator
    try:
        generator = TensorARTGenerator(API_KEY, ods_path, output_folder)
    except Exception as e:
        print(f"\nERROR initializing generator: {str(e)}")
        sys.exit(1)

    # Generate images
    print("\n" + "=" * 60)
    print(f"Starting generation of {count} image(s) for channel '{channel}'")
    print("=" * 60)

    generated_files = generator.generate_for_channel(
        channel=channel,
        count=count,
        model_id="757279507095956705",
        lora_id="832298395185001638",
        lora_weight=0.8
    )

    # Summary
    print("\n" + "=" * 60)
    print("Generation Complete!")
    print("=" * 60)
    print(f"Successfully generated {len(generated_files)} image(s):")
    for filepath in generated_files:
        print(f"  - {filepath}")

    # Show remaining available prompts
    available = generator.prompt_manager.get_available_prompts(channel)
    print(f"\nRemaining available prompts for '{channel}': {len(available)}")


if __name__ == "__main__":
    main()
