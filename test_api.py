"""
test_api.py — Quick sanity check for your Gemini API key.

Run this BEFORE starting the full app:
    python test_api.py

If it prints a Gemini response, your key works and the app will work.
If it raises an error, fix your .env file first.
"""

import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY", "").strip()
if not api_key:
    print("ERROR: GEMINI_API_KEY not found in .env file!")
    print("  Create a .env file in this folder with:")
    print("  GEMINI_API_KEY=your_key_here")
    exit(1)

print(f"API key loaded: {api_key[:8]}...{api_key[-4:]}")
print("Sending test request to Gemini 2.0 Flash...")

try:
    client   = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents="Say hello in exactly 5 words.",
    )
    print(f"\nGemini response: {response.text.strip()}")
    print("\nSUCCESS: API key is working!")
    print("You can now run: streamlit run app.py")
except Exception as e:
    print(f"\nFAILED: API call failed: {e}")
    print("Check that your API key is valid at: https://aistudio.google.com/app/apikey")
