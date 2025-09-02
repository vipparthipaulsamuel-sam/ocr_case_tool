from app import app

if __name__ == "__main__":
    # Production mode — no debug, listen on all interfaces
    app.run(host="0.0.0.0", port=5000)
