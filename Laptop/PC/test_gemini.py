import os
import google.generativeai as genai
from dotenv import load_dotenv

# 1. Load API Key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: No API Key found in .env file!")
    exit()

print(f"🔑 API Key found (starts with: {api_key[:4]}...)")

# 2. Configure
genai.configure(api_key=api_key)

# 3. List All Available Models
print("\n📋 Scanning for available models...")
try:
    # We use the raw list_models to see everything
    for m in genai.list_models():
        if "generateContent" in m.supported_generation_methods:
            print(f"   - {m.name}")
            
    print("\n✅ Scan complete.")
except Exception as e:
    print(f"❌ Error listing models: {e}")

# 4. Test Flash Connection
print("\n⚡ Testing 'gemini-1.5-flash' connection...")
try:
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content("Say 'Hello Robot'")
    print(f"✅ SUCCESS! Gemini replied: {response.text}")
except Exception as e:
    print(f"❌ CONNECTION FAILED: {e}")