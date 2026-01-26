import httpx
import os
import time
import json

def test_httpx_direct():
    # Hardcode key for testing if env var fails, or load from .env file manually
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # Fallback to reading .env directly if environment variable is not passed correctly
        try:
            with open(".env", "r") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

    base_url = os.getenv("OPENAI_API_BASE", "https://api.ai-mediator.ru/v1")
    
    if not api_key:
        print("Error: OPENAI_API_KEY not found")
        return

    print(f"Testing direct httpx request to {base_url}...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "gemini-3-flash-preview",
        "messages": [{"role": "user", "content": "Why is the sky blue?"}]
    }
    
    start_time = time.time()
    try:
        # Using a new client instance
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{base_url}/chat/completions", headers=headers, json=data)
            
        elapsed = time.time() - start_time
        print(f"Request completed in {elapsed:.2f} seconds")
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("Response:", json.dumps(response.json(), indent=2))
        else:
            print("Error Response:", response.text)
            
    except Exception as e:
        print(f"Exception occurred: {e}")

if __name__ == "__main__":
    test_httpx_direct()