import httpx
import os
import time
import socket

# Патч для принудительного использования IPv4
def force_ipv4_dns():
    old_getaddrinfo = socket.getaddrinfo
    def new_getaddrinfo(*args, **kwargs):
        responses = old_getaddrinfo(*args, **kwargs)
        return [response for response in responses if response[0] == socket.AF_INET]
    socket.getaddrinfo = new_getaddrinfo

def test_httpx_ipv4():
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_API_BASE", "https://api.ai-mediator.ru/v1")
    
    if not api_key:
        # Fallback to reading .env directly
        try:
            with open(".env", "r") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass

    if not api_key:
        print("Error: OPENAI_API_KEY not found")
        return

    print(f"Testing httpx request with forced IPv4 to {base_url}...")
    force_ipv4_dns()
    
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
        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{base_url}/chat/completions", headers=headers, json=data)
            
        elapsed = time.time() - start_time
        print(f"Request completed in {elapsed:.2f} seconds")
        print(f"Status Code: {response.status_code}")
            
    except Exception as e:
        print(f"Exception occurred: {e}")

if __name__ == "__main__":
    test_httpx_ipv4()