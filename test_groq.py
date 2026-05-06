import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

# Get API key
api_key = os.getenv("GROQ_API_KEY")

if not api_key or api_key == "your_groq_api_key_here":
    print("ERROR: GROQ_API_KEY is missing or invalid in your .env file.")
    print("   Please sign up at https://console.groq.com and paste your key in the .env file.")
    exit(1)

print("Found GROQ_API_KEY in .env file.")
print("Connecting to Groq...")

try:
    # Initialize client
    client = Groq(api_key=api_key)
    
    # Send a quick test message
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "user", "content": "Analyze this: The contractor shall indemnify the client. Answer in one sentence."}
        ],
        temperature=0.1,
        max_tokens=50
    )
    
    print("\n--------------------------------------------------")
    print("Groq AI Response:")
    print(response.choices[0].message.content)
    print("--------------------------------------------------\n")
    print("SUCCESS! Your Groq API key is working perfectly.")
    print("Next step: Run 'streamlit run app.py'")

except Exception as e:
    print(f"\nFAILED! Could not connect to Groq API.")
    print(f"Error details: {e}")
