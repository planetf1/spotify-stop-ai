#!/usr/bin/env python3
"""Direct test of Ollama API response format."""

import json
import httpx


def test_ollama_direct():
    """Test Ollama API directly."""
    prompt = """You are a music expert. Return ONLY valid JSON (no markdown, no explanation).

{
  "label": "human",
  "is_artificial": false,
  "confidence": 0.9,
  "reason": "This is a test",
  "citations": []
}"""

    payload = {
        "model": "granite4:tiny-h",
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "seed": 42, "num_predict": 128},
        "keep_alive": "5m",
    }

    print("Testing Ollama API...")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    response = httpx.post(
        "http://127.0.0.1:11434/api/generate", json=payload, timeout=10
    )

    if response.status_code == 200:
        result = response.json()
        print("\n=== Raw Response ===")
        print(json.dumps(result, indent=2))

        print("\n=== Response Field (raw) ===")
        raw_response = result.get("response", "")
        print(repr(raw_response))

        print("\n=== Attempting to parse ===")
        response_text = raw_response.strip()

        # Try direct parse
        try:
            output = json.loads(response_text)
            print("✓ Direct parse succeeded!")
            print(json.dumps(output, indent=2))
        except json.JSONDecodeError as e:
            print(f"✗ Direct parse failed: {e}")

            # Try with markdown stripping
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            elif response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            print("\n=== After markdown stripping ===")
            print(repr(response_text))

            try:
                output = json.loads(response_text)
                print("✓ Parse after stripping succeeded!")
                print(json.dumps(output, indent=2))
            except json.JSONDecodeError as e2:
                print(f"✗ Parse after stripping failed: {e2}")
                print(f"First 500 chars: {response_text[:500]}")
    else:
        print(f"✗ API error: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    test_ollama_direct()
