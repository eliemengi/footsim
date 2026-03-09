# Champions League ML Prediction
FootSim
Champions League Match Predictor








Live Application

Open the web app here

https://www.footsim.de

FootSim predicts Champions League match outcomes based on recent team performance and historical match data.

Overview

FootSim is a web application that estimates the probability of match outcomes in Champions League games.

Users can select two teams and instantly receive predicted probabilities for:

Home win
Draw
Away win

The system analyzes recent match data and converts team performance into numerical indicators used for prediction.

This project demonstrates how sports data can be transformed into predictive insights using Python and a simple web architecture.

Features

Champions League match predictions
Probability based match outcomes
Real match data from football-data.org API
Responsive web interface
Fast API powered backend
Production deployment on VPS

How The Prediction Works

The application analyzes the recent performance of both teams.

For each team the system collects recent match statistics such as:

Recent match results
Goals scored
Goals conceded
Win and loss patterns
Overall form trend

These metrics are transformed into numerical features which are then used to estimate the probability distribution for the match outcome.

The prediction result returns three probabilities:

Home win probability
Draw probability
Away win probability

This approach simulates simplified sports analytics models used in real world data science.

Tech Stack

Backend
Python
Flask

Frontend
HTML
CSS
JavaScript

Data Source
football-data.org API

Deployment
Linux VPS
Nginx reverse proxy
Gunicorn WSGI server
Systemd service management

Version Control
Git
GitHub

Project Structure
footsim
│
├── app.py
├── football_api.py
├── predictor.py
│
├── templates
│   └── index.html
│
├── static
│   ├── style.css
│   └── script.js
│
└── requirements.txt
Main Components

app.py
Main Flask application and API routes

football_api.py
Handles communication with the football-data.org API

predictor.py
Contains the prediction logic

templates
HTML templates for the web interface

static
Frontend assets such as CSS and JavaScript

API Endpoint

The frontend communicates with the backend through a simple API endpoint.

Example

/api/matches

This endpoint returns match data and prediction results used by the web interface.

Running the Project Locally

For developers who want to run the project locally.

1 Clone the repository
git clone https://github.com/elieMengi/footsim.git
cd footsim
2 Create a virtual environment
python -m venv venv

Activate the environment

Linux / macOS

source venv/bin/activate

Windows

venv\Scripts\activate
3 Install dependencies
pip install -r requirements.txt
4 Add your API key

Create a .env file in the project root.

Example

FOOTBALL_API_KEY=your_api_key_here

You can get an API key from

https://www.football-data.org/

5 Run the application
python app.py

Open the application in your browser

http://127.0.0.1:5000
Production Deployment

The live version of FootSim runs on a Linux VPS.

Architecture

Browser
→ Nginx reverse proxy
→ Gunicorn WSGI server
→ Flask application

Deployment workflow

Local changes are pushed to GitHub and then pulled on the server.

git push
ssh root@server
git pull
systemctl restart footsim
Future Improvements

Possible improvements for the project

Advanced machine learning models
Expanded historical team data
League wide simulations
Prediction confidence indicators
Team strength rating system

Disclaimer

This project is built for educational and demonstration purposes.

Predictions are statistical estimates and should not be interpreted as guaranteed outcomes.

Author

Elie Mengi