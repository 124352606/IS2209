CryptoTrack — Live Crypto Price Dashboard

IS2209 Group 30 — DeployHub Project

A Flask-based web application that aggregates live cryptocurrency price data from the CoinGecko API and stores user watchlist data in a Supabase-hosted PostgreSQL database. The application is containerised with Docker and deployed automatically to Render via a GitHub Actions CI/CD pipeline.

Live Deployment: [INSERT RENDER URL]
GitHub Repository: https://github.com/124352606/IS2209

Team
Charlie 124352606 Project Lead 
Danny 124353601-star Backend Developer
Colm Colm-Clifford Database Engineer
Ryan Ryan McCarthy Frontend Developer

Tech Stack

Python 3.11 — application language
Flask — web framework
CoinGecko API — live cryptocurrency price data
Supabase / PostgreSQL — cloud-hosted database for watchlist storage
Docker — containerisation
GitHub Actions — CI/CD pipeline
GitHub Container Registry (GHCR) — Docker image hosting
Render — cloud deployment platform


Setup Instructions
Prerequisites

Python 3.11+
Docker Desktop
A CoinGecko Demo API key (free at https://www.coingecko.com/en/api)
A Supabase project with the watchlist table created

1. Clone the repository
git clone https://github.com/124352606/IS2209.git
cd IS2209

2. Create a virtual environment

3. Install dependencies
pip install -r requirements.txt

4. Set up environment variables

5. Set up the database
Run the following SQL in your Supabase SQL editor:
sqlCREATE TABLE IF NOT EXISTS watchlist (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    coin_id TEXT NOT NULL,
    coin_name TEXT NOT NULL,
    added_at TIMESTAMP DEFAULT NOW()
);

6. Run the application
Open your browser at http://localhost:5000

Environment Variables
See .env.example for the template.

Branching Strategy
The team used trunk-based development with short-lived feature branches. All branches were merged into main via pull requests requiring a passing CI build and at least one peer review before merge. Main was kept deployable at all times.

