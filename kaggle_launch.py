"""
kaggle_launch.py — starts api.py on Kaggle and exposes it publicly.

Kaggle notebooks have no reachable public port by default (this is why
app.py's Gradio launch uses share=True). FastAPI has no equivalent built in,
so this script opens an ngrok tunnel to the same effect.

Usage on Kaggle (after pip install -r requirements.txt):
    python kaggle_launch.py
"""

import uvicorn
from pyngrok import ngrok

PORT = 8000

if __name__ == "__main__":
    public_url = ngrok.connect(PORT, "http")
    print(f"\n{'=' * 60}")
    print(f"  verify_docs API is public at: {public_url}")
    print(f"  Set VERIFY_SERVICE_URL={public_url} in the Loan Networks backend/.env")
    print(f"{'=' * 60}\n")

    uvicorn.run("api:app", host="0.0.0.0", port=PORT)
