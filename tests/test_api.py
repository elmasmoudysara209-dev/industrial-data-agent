from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client()   # lit automatiquement GEMINI_API_KEY dans .env
r = client.models.generate_content(
    model="gemini-3.5-flash",
    contents="Dis bonjour en une phrase.",
)
print(r.text)