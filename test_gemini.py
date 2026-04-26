import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("NO KEY FOUND IN .ENV")
    exit(1)

genai.configure(api_key=api_key)
try:
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("Reply with the word 'SUCCESS'")
    print(f"API TEST RESULT: {response.text.strip()}")
except Exception as e:
    print(f"API TEST ERROR: {str(e)}")
