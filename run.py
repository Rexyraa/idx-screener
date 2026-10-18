"""One-command launcher: python run.py → http://localhost:8000"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("idxscreener.web.app:app", host="127.0.0.1", port=8000, reload=False)
